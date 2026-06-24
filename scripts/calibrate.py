"""Calibrate classification thresholds & the accuracy scale to *Catan* (brief §4.2, §5).

The brief is explicit: don't borrow chess's numbers blindly. We measure the real
per-decision ``eff_loss`` distribution in self-play and pick an accuracy ``scale``
so a typical player lands in a sensible band. Results are written to
``data/calibration.json`` and summarized in DECISIONS.md.

Usage:  python -m scripts.calibrate --games 4
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

from catan_review.engine import GameConfig, run_game
from catan_review.policy import REFERENCE
from catan_review.analyze import analyze_trajectory


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--seed0", type=int, default=1)
    ap.add_argument("--n-before", type=int, default=70)
    ap.add_argument("--n-alt", type=int, default=50)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()

    all_eff = []
    per_player_avg = []
    by_phase = {}
    for k in range(args.games):
        seed = args.seed0 + k
        traj = run_game(GameConfig(seed=seed), REFERENCE)
        rev = analyze_trajectory(traj, n_before=args.n_before, n_alt=args.n_alt,
                                 topk=4, workers=args.workers)
        for t in rev["timeline"]:
            e = t["classification"]["eff_loss"]
            all_eff.append(e)
            by_phase.setdefault(t["phase"], []).append(e)
        for rc in rev["report_cards"].values():
            per_player_avg.append(rc["avg_wp_loss"])
        print(f"  game seed={seed}: winner={rev['winner']} decisions={len(rev['timeline'])}")

    all_eff.sort()
    n = len(all_eff)
    pct = lambda p: all_eff[min(n - 1, int(p * n))]
    mean_avg = st.mean(per_player_avg)
    # Choose scale so the typical (mean) player's avg loss maps to ~75% accuracy.
    target = 0.75
    scale = round(mean_avg / -math.log(target), 3) if mean_avg > 0 else 0.05

    summary = {
        "games": args.games,
        "rollouts": {"n_before": args.n_before, "n_alt": args.n_alt},
        "eff_loss": {"n": n, "mean": round(st.mean(all_eff), 4), "median": round(pct(0.5), 4),
                     "p75": round(pct(0.75), 4), "p90": round(pct(0.90), 4), "p95": round(pct(0.95), 4)},
        "per_player_avg_wp_loss": {"mean": round(mean_avg, 4),
                                   "min": round(min(per_player_avg), 4),
                                   "max": round(max(per_player_avg), 4)},
        "phase_mean_eff_loss": {ph: round(st.mean(v), 4) for ph, v in by_phase.items()},
        "recommended_accuracy_scale": scale,
        "accuracy_table": {f"scale={s}": round(100 * math.exp(-mean_avg / s)) for s in (0.05, 0.08, 0.1, 0.12, 0.15)},
    }
    os.makedirs("data", exist_ok=True)
    with open("data/calibration.json", "w") as f:
        json.dump(summary, f, indent=2)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\n--> set accuracy scale = {scale} (typical player ~= {target:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
