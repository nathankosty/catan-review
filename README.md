# Catan Review

**Play Settlers of Catan in your browser and learn from every move** — a
chess.com-style experience for Catan. Every decision you make is graded
instantly (**Brilliant / Great / Best / Excellent / Good / Book / Inaccuracy /
Mistake / Miss / Blunder**) with a plain-English explanation and the engine's
suggested better move. You can **take a move back** after seeing its label
(same dice on the replay — you can't fish for rolls), watch a **live
win-probability chart**, and when the game ends, **walk through the full game
review** exactly like chess.com: move list with icons, eval graph, per-player
accuracy report cards, and critical moments.

Because Catan is stochastic, multiplayer, and hidden-information, the
evaluation unit is **win probability**, not centipawns — and every estimate is
honest about its uncertainty: labels within the engine's error margin are
marked low-confidence. See [DECISIONS.md](DECISIONS.md) for the full rationale
and the list of approximations.

## How it works

- **Rules engine:** [Catanatron](https://github.com/bcollazo/catanatron)
  (complete base game), wrapped in `catan_review/`. In the browser it runs
  under **Pyodide (WASM)** at near-native speed — the deployed app is a static
  site with the *same tested Python engine* running client-side. No backend.
- **Live evaluation:** a **trained value function** (self-play data, softmax
  over players, pure-Python inference) scores every legal action in
  milliseconds. Its measured error vs Monte-Carlo ground truth is stored with
  the model and drives the label confidence (`sigma_pair`).
- **Deep analysis:** the offline analyzer uses **Monte-Carlo rollouts to game
  end** with confidence intervals (the bundled sample review was generated
  this way).

```
catan_review/
  engine.py      thin wrapper over Catanatron (rules / simulation core)
  policy.py      reference + rollout policies (the opponent model)
  evaluator.py   deep WP via Monte-Carlo rollouts, with confidence intervals
  quickeval.py   fast WP via the trained value function (browser-safe, no numpy)
  webplay.py     live play session: feedback, take-backs, incremental review
  classifier.py  WP-loss -> chess.com taxonomy (noise-disciplined)
  annotate.py    plain-English explanations ("feeding the leader" detection)
  analyze.py     full game -> review JSON (parallel across cores)
  gamelog.py     versioned JSON game format + board geometry
  api.py         FastAPI service (local dev convenience)
web/             React + Vite app: home / play mode / review walkthrough
  src/engine.js  Pyodide bridge (vendored wheels, bundled Python sources)
scripts/         selfplay, analyze_game, calibrate, train_value
tests/           rule-fidelity + termination + live-play test suite
data/            sample game, analyzed review, calibration, value model
```

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
( cd web && npm install )
./run.sh          # FastAPI (:8000) + Vite dev server (:5173)
```

Open **http://localhost:5173** → *Play a game* (the engine loads in-browser,
~10 MB first visit) or *Open sample review*.

## Deploy (Vercel)

Static site — [`vercel.json`](vercel.json) builds `web/` and serves `web/dist`.
Import the repo at vercel.com; every push to `main` redeploys. The play mode,
value model, sample review, and Python wheels all ship as static assets.

## Retrain / regenerate

```bash
python -m scripts.train_value --games 1500      # value model (+ rollout calibration)
python -m scripts.analyze_game --seed 123 --out data/games/sample   # deep sample review
python -m scripts.calibrate --games 4           # threshold/accuracy calibration
pytest -q                                       # 20 tests: rules, termination, live play
```

## Status

- ✅ M1–M5: rules engine + tests, MC-rollout evaluator with CIs, self-play
  calibration, classifier, review UI
- ✅ M6: **play in the browser** vs bots with instant move grading, take-backs,
  live win% chart, and post-game review of your own game
- ⏳ Deferred: the domestic-trade subsystem (§2.8/§2.8a — Catanatron has no
  player-to-player trades; layered design documented) and hidden-information
  determinization. Honest approximations listed in
  [DECISIONS.md](DECISIONS.md#known-limitations-honest-list--see-also-ui-disclaimer).
