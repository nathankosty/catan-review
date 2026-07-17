"""Train the fast value function on self-play outcomes (brief §3.2b, §5).

Pipeline:
  1. Generate self-play games (parallel) under the reference policy at mixed
     exploration levels and player counts, so the model sees strong *and*
     sloppy positions.
  2. Extract per-player features at sampled decision plies; label each state
     with the eventual winner. Split train/val **by game** (no leakage).
  3. Train the shared-scorer MLP (softmax over players) with Adam in numpy.
  4. Validate: log-loss / winner-accuracy vs two baselines (uniform, VP-share).
  5. Calibrate honesty: on held-out decision states, compare the model's
     action-ranking deltas to Monte-Carlo rollout ground truth; store the
     pairwise error ``sigma_pair`` in the model file — the classifier uses it
     as the CI for value-net labels (§4.4).

Output: data/value_model.json (+ copy to web/public/ for the browser).

Usage:
  python -m scripts.train_value --games 1200            # full run
  python -m scripts.train_value --games 200 --quick     # smoke test
"""
from __future__ import annotations

# Reproducibility: Catanatron enumerates via hash-ordered sets (see DECISIONS.md).
import os
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(__import__("sys").executable, [__import__("sys").executable] + __import__("sys").argv)

import argparse
import json
import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from catan_review.engine import GameConfig, new_game, ACTION_WATCHDOG
from catan_review.policy import make_policy
from catan_review.quickeval import extract_features, FEATURE_NAMES, ValueModel
from catan_review.evaluator import evaluate_action

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "value_model.json")
WEB_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "public", "value_model.json")


# ---------------------------------------------------------------------------- #
# 1-2. Data generation
# ---------------------------------------------------------------------------- #

def _gen_one(job: dict) -> dict:
    """Worker: play one game, return sampled (features, winner) rows."""
    seed, eps, num_players, sample_every = job["seed"], job["eps"], job["np"], job["every"]
    cfg = GameConfig(num_players=num_players, seed=seed)
    game = new_game(cfg)
    policy = make_policy(epsilon=eps)
    rng = random.Random(seed)
    rows = []  # (feats_per_player, colors)
    k = rng.randrange(sample_every)
    steps = 0
    while game.winning_color() is None and steps < ACTION_WATCHDOG:
        pa = game.state.playable_actions
        if len(pa) > 1:
            if k % sample_every == 0:
                cache: dict = {}
                feats = [extract_features(game, c, _cache=cache) for c in game.state.colors]
                rows.append(feats)
            k += 1
        game.execute(policy(game, rng))
        steps += 1
    w = game.winning_color()
    if w is None:
        return {"rows": [], "colors": [], "winner": None, "seed": seed}
    colors = [c.value for c in game.state.colors]
    return {"rows": rows, "colors": colors, "winner": w.value, "seed": seed}


def generate_dataset(n_games: int, workers: int, sample_every: int = 6):
    jobs = []
    for i in range(n_games):
        jobs.append({
            "seed": 20_000 + i,
            "eps": [0.05, 0.15, 0.30][i % 3],       # strong + sloppy positions
            "np": 4 if i % 4 else 3,                 # mostly 4p, some 3p
            "every": sample_every,
        })
    X, Y, gid, nplayers = [], [], [], []
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_gen_one, jobs, chunksize=4):
            done += 1
            if res["winner"] is None:
                continue
            widx = res["colors"].index(res["winner"])
            for feats in res["rows"]:
                X.append(feats)      # list of per-player feature vectors
                Y.append(widx)
                gid.append(res["seed"])
                nplayers.append(len(feats))
            if done % 100 == 0:
                print(f"  {done}/{n_games} games, {len(X)} states, {time.time()-t0:.0f}s", flush=True)
    return X, Y, gid


# ---------------------------------------------------------------------------- #
# 3. Model + training (numpy; shared scorer, softmax over seats)
# ---------------------------------------------------------------------------- #

def train(X, Y, gid, hidden: int = 24, epochs: int = 40, lr: float = 3e-3, seed: int = 0):
    rng = np.random.default_rng(seed)
    F = len(FEATURE_NAMES)

    # Pad 3-player states with a -inf mask so one batch handles both sizes.
    N = len(X)
    P = max(len(x) for x in X)
    feats = np.zeros((N, P, F), dtype=np.float64)
    mask = np.full((N, P), -1e9, dtype=np.float64)
    for i, x in enumerate(X):
        feats[i, : len(x)] = x
        mask[i, : len(x)] = 0.0
    y = np.array(Y)

    # Split by game id.
    games = sorted(set(gid))
    rng.shuffle(games)
    val_games = set(games[: max(1, len(games) // 8)])
    is_val = np.array([g in val_games for g in gid])
    tr, va = ~is_val, is_val

    W1 = rng.normal(0, 0.3, (hidden, F))
    b1 = np.zeros(hidden)
    W2 = rng.normal(0, 0.3, hidden)
    b2 = 0.0

    def forward(f):  # f: [n, P, F] -> scores [n, P]
        h = np.maximum(f @ W1.T + b1, 0.0)          # [n, P, H]
        return h @ W2 + b2, h

    def loss_of(f, m, yy):
        s, _ = forward(f)
        s = s + m
        s = s - s.max(axis=1, keepdims=True)
        logz = np.log(np.exp(s).sum(axis=1))
        return float(np.mean(logz - s[np.arange(len(yy)), yy]))

    # Adam
    ms = [np.zeros_like(W1), np.zeros_like(b1), np.zeros_like(W2), 0.0]
    vs = [np.zeros_like(W1), np.zeros_like(b1), np.zeros_like(W2), 0.0]
    beta1, beta2, eps_ = 0.9, 0.999, 1e-8
    t = 0
    best = (1e9, None)
    idx_tr = np.where(tr)[0]
    B = 512
    for ep in range(epochs):
        rng.shuffle(idx_tr)
        for k in range(0, len(idx_tr), B):
            bidx = idx_tr[k : k + B]
            f, m, yy = feats[bidx], mask[bidx], y[bidx]
            s, h = forward(f)
            s = s + m
            s = s - s.max(axis=1, keepdims=True)
            e = np.exp(s)
            p = e / e.sum(axis=1, keepdims=True)          # [n, P]
            g = p.copy()
            g[np.arange(len(yy)), yy] -= 1.0
            g /= len(yy)                                   # dL/ds  [n, P]
            gW2 = np.einsum("np,nph->h", g, h)
            gb2 = float(g.sum())
            gh = g[..., None] * W2                         # [n, P, H]
            gh[h <= 0] = 0.0
            gW1 = np.einsum("nph,npf->hf", gh, f)
            gb1 = gh.sum(axis=(0, 1))
            t += 1
            for i, (param, grad) in enumerate(
                ((W1, gW1), (b1, gb1), (W2, gW2), (b2, gb2))
            ):
                ms[i] = beta1 * ms[i] + (1 - beta1) * (grad if i != 3 else grad)
                vs[i] = beta2 * vs[i] + (1 - beta2) * (np.square(grad) if i != 3 else grad * grad)
                mh = ms[i] / (1 - beta1 ** t)
                vh = vs[i] / (1 - beta2 ** t)
                upd = lr * mh / (np.sqrt(vh) + eps_)
                if i == 0: W1 -= upd
                elif i == 1: b1 -= upd
                elif i == 2: W2 -= upd
                else: b2 -= upd
        vl = loss_of(feats[va], mask[va], y[va])
        if vl < best[0]:
            best = (vl, (W1.copy(), b1.copy(), W2.copy(), float(b2)))
        if ep % 5 == 0 or ep == epochs - 1:
            print(f"  epoch {ep:3d}  train {loss_of(feats[tr], mask[tr], y[tr]):.4f}  val {vl:.4f}", flush=True)

    W1, b1, W2, b2 = best[1]

    # --- 4. validation report -------------------------------------------------
    def report(name, probs):
        p = probs[np.arange(va.sum()), y[va]]
        ll = float(np.mean(-np.log(np.clip(p, 1e-9, 1))))
        acc = float(np.mean(probs.argmax(axis=1) == y[va]))
        print(f"  {name:<18} val log-loss {ll:.4f}  winner-acc {acc:.3f}")
        return ll, acc

    s, _ = ( (np.maximum(feats[va] @ W1.T + b1, 0.0) @ W2 + b2), None)
    s = s + mask[va]
    e = np.exp(s - s.max(axis=1, keepdims=True))
    model_p = e / e.sum(axis=1, keepdims=True)

    nseat = (mask[va] > -1).sum(axis=1)
    unif = (mask[va] > -1) / nseat[:, None]

    vp_idx = FEATURE_NAMES.index("vp")
    vp = feats[va][:, :, vp_idx] * 10.0
    ev = np.exp((vp + mask[va]) * 0.8)
    vp_p = ev / ev.sum(axis=1, keepdims=True)

    print("\nValidation:")
    ll_m, acc_m = report("value model", model_p)
    ll_u, _ = report("uniform baseline", unif)
    ll_v, acc_v = report("VP-share baseline", vp_p)

    return {
        "W1": W1.tolist(), "b1": b1.tolist(), "W2": W2.tolist(), "b2": float(b2),
        "meta": {
            "features": FEATURE_NAMES, "hidden": hidden,
            "val_logloss": round(ll_m, 4), "val_acc": round(acc_m, 4),
            "baseline_uniform_logloss": round(ll_u, 4),
            "baseline_vp_logloss": round(ll_v, 4), "baseline_vp_acc": round(acc_v, 4),
        },
    }


# ---------------------------------------------------------------------------- #
# 5. Rollout-agreement calibration -> sigma_pair
# ---------------------------------------------------------------------------- #

def _calib_one(job: dict) -> list:
    """Worker: at one decision state, compare value-fn deltas between candidate
    actions to rollout ground-truth deltas."""
    seed, n_roll, model_params = job["seed"], job["n_roll"], job["model"]
    model = ValueModel(model_params)
    cfg = GameConfig(num_players=4, seed=seed)
    game = new_game(cfg)
    policy = make_policy(epsilon=0.15)
    rng = random.Random(seed)
    stop_at = rng.randrange(30, 500)
    steps = 0
    decision_game = None
    while game.winning_color() is None and steps < stop_at:
        if len(game.state.playable_actions) > 1 and steps >= stop_at - 30:
            decision_game = game.copy()
            break
        game.execute(policy(game, rng))
        steps += 1
    if decision_game is None:
        return []
    g = decision_game
    actor = g.state.current_color()
    acts = sorted(g.state.playable_actions, key=lambda a: (a.action_type.value, str(a.value)))
    acts = acts[:5]
    if len(acts) < 2:
        return []
    pairs = []
    vals, rolls = [], []
    for i, a in enumerate(acts):
        vals.append(model.predict_after(g, a).get(actor.value, 0.0))
        est = evaluate_action(g, a, n=n_roll, base_seed=seed * 31 + i)
        rolls.append(est.of(actor))
    for i in range(len(acts)):
        for j in range(i + 1, len(acts)):
            dv = vals[i] - vals[j]
            dr = rolls[i] - rolls[j]
            pairs.append((dv, dr))
    return pairs


def calibrate_sigma(model_params: dict, n_states: int, n_roll: int, workers: int):
    jobs = [{"seed": 90_000 + i, "n_roll": n_roll, "model": model_params} for i in range(n_states)]
    all_pairs = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for pairs in ex.map(_calib_one, jobs, chunksize=1):
            all_pairs.extend(pairs)
    if not all_pairs:
        return {"sigma_pair": 0.06, "n_pairs": 0, "rank_agreement": None}
    dv = np.array([p[0] for p in all_pairs])
    dr = np.array([p[1] for p in all_pairs])
    err = dv - dr
    # Rollout deltas are themselves noisy (se ~ sqrt(2*0.25/n)); subtract that
    # variance so sigma_pair reflects the *model's* error, not the ground truth's.
    roll_var = 2 * 0.25 / n_roll
    sigma = float(np.sqrt(max(np.mean(err ** 2) - roll_var, 1e-4)))
    sigma = max(sigma, 0.03)  # never claim better than 3% pairwise precision
    # "Meaningful" pairs: the rollout delta itself must clear its own noise,
    # else we'd score the model against a coin flip.
    meaningful = np.abs(dr) > max(0.05, 1.5 * math.sqrt(0.5 / n_roll))
    agree = float(np.mean(np.sign(dv[meaningful]) == np.sign(dr[meaningful]))) if meaningful.any() else None
    return {
        "sigma_pair": round(sigma, 4),
        "n_pairs": len(all_pairs),
        "rank_agreement": round(agree, 3) if agree is not None else None,
        "n_roll": n_roll,
    }


# ---------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1200)
    ap.add_argument("--hidden", type=int, default=24)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--calib-states", type=int, default=48)
    ap.add_argument("--calib-rollouts", type=int, default=120)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--quick", action="store_true", help="smoke test settings")
    args = ap.parse_args()
    if args.quick:
        args.games, args.epochs, args.calib_states, args.calib_rollouts = 120, 12, 8, 40

    print(f"Generating {args.games} self-play games ({args.workers} workers)...")
    X, Y, gid = generate_dataset(args.games, args.workers)
    print(f"Dataset: {len(X)} states from {len(set(gid))} games")

    print("\nTraining...")
    params = train(X, Y, gid, hidden=args.hidden, epochs=args.epochs)

    print(f"\nCalibrating vs rollouts ({args.calib_states} states x {args.calib_rollouts} rollouts)...")
    calib = calibrate_sigma(params, args.calib_states, args.calib_rollouts, args.workers)
    print(f"  sigma_pair={calib['sigma_pair']}  rank_agreement={calib['rank_agreement']}  (n_pairs={calib['n_pairs']})")
    params["meta"].update(calib)
    params["meta"]["games"] = args.games
    params["meta"]["n_states"] = len(X)

    for path in (OUT, WEB_OUT):
        with open(path, "w") as f:
            json.dump(params, f)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
