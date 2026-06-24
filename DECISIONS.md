# DECISIONS.md

Design decisions, the options compared, and the pivots made while building.
This is the §1 deliverable; it names every approximation honestly (§10).

Scope agreed with the user up front: **fast, pragmatic, full pipeline end-to-end
(M1→M5), trades deferred** to a later milestone. Target: a working, honest review
app in a day or two, not a research project. "A working, honest, slightly-different
system beats a faithful-to-the-brief one that doesn't run."

---

## 1. Rules engine: reuse vs. build

| Option | Pros | Cons |
|---|---|---|
| **Catanatron** (chosen) | MIT, pure-Python, complete base game, ~50 games/sec, seed-deterministic, `Game.copy()`, picklable, rich `state_functions` | **No domestic trade actions**; pip build omits the strong value bots |
| JSettlers2 (Java) | Mature, has trading | JVM bridge, heavier integration |
| From scratch | Full control incl. trades | Re-deriving + re-testing the entire rulebook — huge effort, exactly what Catanatron de-risks |

**Chosen: wrap Catanatron** as the rules/simulation core ([engine.py](catan_review/engine.py)).
Verified empirically before committing: installs clean (`catanatron==3.2.1`, only needs
`networkx`), 49 games/sec single-threaded, `seed=N` reproduces a game identically,
`Game.copy()` produces independent rollouts, `Game` pickles (~13 KB) for multiprocessing.

### Concrete blocker found → pivot
Catanatron's action vocabulary is `ROLL, MOVE_ROBBER, DISCARD, BUILD_*, BUY/PLAY dev
cards, MARITIME_TRADE, END_TURN` — **there is no player-to-player trade**. The brief
makes domestic trade a headline feature (§2.8) and the hardest sub-problem (§0).
- **Pivot:** keep Catanatron for the well-tested 90% and build the trade subsystem
  (offer/counter/accept/reject + the §2.8a termination invariants + §3.5 acceptance
  policy) as a **meta-phase layered on top**, mutating Catanatron state through its
  public `state_functions`. Per the agreed order, trades are **deferred** — the rest of
  the pipeline is proven first. The anti-deadlock harness ([test_termination.py](tests/rules/test_termination.py))
  already exists as the gate the trade layer must pass.

### Other Catanatron findings (recorded for fidelity)
- **`DISCARD` is automated** (`value=None`): Catanatron picks *which* cards to discard.
  The discard *count* (floor half) is enforced and tested, but discard *choice* is not a
  classifiable decision in v1. Documented gap vs §2.4/§4.1.
- The pip package omits the value-function / AlphaBeta bots (GitHub `_experimental`
  extra, heavy deps). We build our own reference policy anyway (§3.4), so this is moot.

---

## 2. Evaluation engine

| Option | Verdict |
|---|---|
| (a) **Monte-Carlo rollouts to terminal** | **Shipped as v1.** No training, faithful, honest CIs. Validated by Catanatron's "playouts property". |
| (b) Learned value function | Documented **growth path** for speed; not needed to ship. |
| (c) MCTS | Overkill for v1; best-alternative search is done by enumerating legal actions + short rollouts. |
| (d) AlphaZero policy+value | Stretch goal, not v1. |

**Chosen blend:** MC rollouts for WP ([evaluator.py](catan_review/evaluator.py)); the
best-alternative is found by rolling out the top-K legal actions ranked by the greedy
heuristic. The metric is **win probability** WP∈[0,1], Σ=1 (§3.1), verified to sum to 1.
A learned value net would slot in behind `evaluate_state` without touching callers.

Performance: a full game (~150–200 decisions) analyzes in ~100 s on 8 cores at
`n_before=80, n_alt=60, topk=4`. Work fans out across processes (one self-contained task
per decision); `Game` pickles cleanly. Heavier rollouts can be reserved for critical
positions (§3.6) — not yet auto-tuned.

## 3. Hidden information

Options: determinization-by-sampling · belief model · **perfect-info approximation**.
**Chosen v1: perfect-info, explicitly flagged** (`PERFECT_INFO=True`, surfaced in the UI
disclaimer and `meta`). Rollouts see the true hidden state. `evaluator.determinize()` is
the seam where resampling opponents' hands/deck order drops in (§3.3) — a no-op for now.
This is the honest, documented approximation the brief permits for v1.

## 4. Trade modeling

Deferred (see §1 pivot). When built: heuristic counterparty-acceptance ("accept iff
WP-improving and not past a leader-feeding threshold"), swappable, with the §2.8a engine
invariants guaranteeing termination independent of bot logic. "Feeding the leader"
detection already exists in the annotator ([annotate.py](catan_review/annotate.py)) and
fires on maritime trades today.

## 5. Tech stack

Python rules/eval (Catanatron + numpy), **FastAPI** service ([api.py](catan_review/api.py)),
**React + Vite** frontend ([web/](web/)) with hand-rolled SVG board (Red Blob hex math)
and eval graph (no chart lib). SQLite not needed yet — flat JSON under `data/`.

---

## Classification & calibration (§4, §5)

- **Noise discipline is central (§4.4, §10).** `best_wp = max over noisy candidate
  estimates` is biased upward, so the *raw* loss overstates how bad a move was. We bucket
  and score on a **debiased loss**: `eff_loss = max(0, raw_loss − 1σ_diff)` — the loss we
  can distinguish from rollout noise. Moves whose apparent loss is mostly noise are
  flagged `low_confidence`, never labelled a confident Blunder.
  - *Pivot during build:* first tried subtracting the full 95% CI (1.96σ) — too
    conservative, it zeroed out **everything** (median eff_loss = 0, all moves "Best").
    Switched to **1σ** (the standard error of the difference): "more likely than not a
    real loss", which restores a realistic label spread while staying honest.
- **Thresholds** start from chess.com's Expected-Points bands ([classifier.py](catan_review/classifier.py)
  `THRESHOLDS`) and were **checked against our own self-play distribution**
  ([scripts/calibrate.py](scripts/calibrate.py) → [data/calibration.json](data/calibration.json)):
  setup mean eff_loss ≈ 0.055 (placements genuinely swing WP), mid ≈ 0.010, late ≈ 0.021;
  p90 ≈ 0.05. The bands line up sensibly; not yet recalibrated *per decision type*.
- **Accuracy formula:** `100·exp(−avg_eff_loss / scale)`. Calibration recommends
  `scale ≈ 0.049`; we use **0.05**, so a typical reference-policy player scores ≈ 75%
  with a real spread (≈56–90%). Documented, not borrowed blindly.
- **Special labels** (Book/Great/Brilliant/Miss) layer on top, all gated on confidence so
  noise can't mint a "Brilliant" or "Miss".

### Reference policy (§3.4)
One fixed heuristic greedy policy ([policy.py](catan_review/policy.py)) used consistently
for generation, rollouts, and counterfactuals. `REFERENCE` (ε=0.05) generates games;
`ROLLOUT` (ε=0.30) adds the exploration Monte-Carlo needs. It is deliberately simple
(production-pip placement, build/army priority, rob-the-leader); a stronger policy →
shorter, cleaner games is a clear improvement lever.

---

## Known limitations (honest list — see also UI disclaimer)
1. **Perfect-information** evaluation in v1 (flagged everywhere).
2. **No domestic trades** yet — only maritime; the subsystem is the next milestone.
3. **Discard choice** is engine-automated (count enforced, choice not classifiable).
4. **Earliest setup placements have the widest error bars** — rollouts there span the
   whole game (highest variance) and the max-over-candidates bias is largest; a few
   setup labels may overstate magnitude. CIs are shown; a future pass can spend extra
   rollouts on these.
5. **Reference policy is modest**, so "best alternative" is only as strong as it is.
6. Thresholds calibrated globally, **not yet per decision type**.

---

## Deployment (Vercel, static — pivot recorded 2026-06-24)

**User directive:** host the whole thing on Vercel, "like my other apps."

**Constraint:** §5's stack is a Python FastAPI backend + React frontend. Vercel's
serverless functions can't run the engine — WP comes from Monte-Carlo rollouts to
terminal (~100 s per game on 8 cores, multiprocessing), which blow past serverless
time/CPU/bundle limits. A live "analyze any game" backend is therefore **not
deployable on Vercel**.

**Chosen:** deploy the **React/Vite app as a static site** serving a **precomputed
review** — which is exactly what the app already does: `App.jsx` fetches the static
`sample.review.json` first and only falls back to `/api`. All heavy compute
(self-play, rollouts, classification, calibration) stays **offline** and is committed
as artifacts under `data/` + `web/public/`. This honours §10: we don't fake live deep
analysis where we can't run it — we precompute it and review it.

- **Deploys:** the full chess.com-style Game Review over the precomputed sample game
  (board replay, multi-player eval graph, move list, report cards, critical moments).
- **Does NOT deploy:** live `/api/analyze` and `/api/watch` (analyze a fresh seed /
  watch a new bot game in-app). Those stay local-only via `./run.sh`. To publish a
  *different* analyzed game, run `scripts/analyze_game.py` offline and commit its
  `.review.json` as the new static asset in `web/public/`.
- **Build:** [`vercel.json`](vercel.json) at repo root builds `web/`
  (`npm install && vite build`) and serves `web/dist` statically. No serverless
  functions, no Python at runtime — same shape as the other Vercel apps.
