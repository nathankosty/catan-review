# Catan Review

A **chess.com-style "Game Review" for Settlers of Catan**. It takes a base-game
(3–4 player) game and labels every decision **Brilliant / Great / Best / Excellent /
Good / Book / Inaccuracy / Mistake / Miss / Blunder**, with a running **win-probability
eval graph** (one line per player, summing to 1), per-player **accuracy** and report
cards, suggested better moves, and plain-English annotations.

Because Catan is stochastic, multiplayer, and hidden-information, the evaluation unit is
**win probability** (Monte-Carlo rollouts to game end), not centipawns — every estimate
carries a confidence interval and labels within rollout noise are flagged. See
[DECISIONS.md](DECISIONS.md) for the full rationale and honest list of approximations.

![pipeline](https://img.shields.io/badge/pipeline-engine%E2%86%92WP%E2%86%92classify%E2%86%92review-blue)

## Architecture

```
catan_review/
  engine.py      thin wrapper over Catanatron (rules / simulation core)
  policy.py      reference + rollout policies (the opponent model)
  evaluator.py   win probability via Monte-Carlo rollouts, with confidence intervals
  classifier.py  per-decision WP-loss -> chess.com taxonomy (noise-disciplined)
  annotate.py    plain-English explanations ("feeding the leader" detection)
  analyze.py     full game -> review JSON (parallel across cores)
  gamelog.py     versioned JSON game format + board geometry
  api.py         FastAPI service
web/             React + Vite review UI (SVG board, eval graph, move list, report cards)
scripts/         selfplay (anti-deadlock), analyze_game, calibrate
tests/rules/     rule-fidelity + termination test suite
data/            sample games, analyzed reviews, calibration
```
The engine, classifier, and UI are decoupled — the evaluator can be upgraded
(rollouts → value net → AlphaZero) without touching the UI.

## Setup (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
( cd web && npm install )
```

## Run it

```bash
./run.sh          # starts FastAPI (:8000) + Vite dev server (:5173)
```
Then open **http://localhost:5173**. A pre-analyzed sample game loads immediately.

## Generate / analyze your own game

```bash
# Generate a seeded bot game and analyze every decision -> data/games/mygame.review.json
python -m scripts.analyze_game --seed 7 --out data/games/mygame

# Or via the API (the UI's "analyze" path):
curl -X POST localhost:8000/api/analyze -H 'content-type: application/json' \
     -d '{"seed":7,"n_before":80,"n_alt":60}'
```

## Tests & calibration

```bash
pytest -q                                   # rule-fidelity + format tests
pytest tests/rules/test_termination.py -q   # anti-deadlock: 100s of games must all finish
python -m scripts.selfplay --games 2000     # termination stress test (standalone)
python -m scripts.calibrate --games 4       # recompute thresholds/accuracy from self-play
```

## Deploy (Vercel)

Deploys to Vercel as a **static site** serving a precomputed review — no backend
(rationale + honest limits in [DECISIONS.md](DECISIONS.md#deployment-vercel-static--pivot-recorded-2026-06-24)).
[`vercel.json`](vercel.json) builds `web/` and serves `web/dist`. Import the repo at
vercel.com and deploy; every push to `main` redeploys. Live analyze/watch stay local
via `./run.sh`.

## Status

Milestones M1–M5 are in: rules engine + tests, WP evaluator with CIs, self-play
calibration, the full classifier, and the review UI. **Deferred:** the domestic-trade
subsystem (§2.8 / §2.8a) and play-vs-bot mode (M6). Current honest approximations are
listed in [DECISIONS.md](DECISIONS.md#known-limitations).
