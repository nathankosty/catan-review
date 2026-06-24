"""Generate (or load) a game and analyze it into a review JSON (brief §6, §8 M5).

Usage:
    python -m scripts.analyze_game --seed 123 --out data/games/sample
    python -m scripts.analyze_game --log data/games/foo.log.json --out data/games/foo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Pin hash seed so Catanatron's hash-ordered action enumeration (and thus our
# seeded games) reproduce identically across processes/runs (§10).
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

from catan_review.engine import GameConfig, run_game
from catan_review.policy import REFERENCE
from catan_review.gamelog import GameLog
from catan_review.analyze import analyze_trajectory


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=123)
    ap.add_argument("--players", type=int, default=4)
    ap.add_argument("--out", type=str, default="data/games/sample")
    ap.add_argument("--n-before", type=int, default=60)
    ap.add_argument("--n-alt", type=int, default=45)
    ap.add_argument("--topk", type=int, default=4)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--max-decisions", type=int, default=None)
    args = ap.parse_args()

    cfg = GameConfig(num_players=args.players, seed=args.seed)
    print(f"Generating game (seed={args.seed}) ...")
    traj = run_game(cfg, REFERENCE)
    n_dec = sum(p.is_decision for p in traj.plies)
    print(f"  winner={traj.winner.value if traj.winner else None}  turns={traj.num_turns}  decisions={n_dec}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    GameLog.from_trajectory(traj).save(args.out + ".log.json")

    print(f"Analyzing {n_dec} decisions (n_before={args.n_before}, n_alt={args.n_alt}, topk={args.topk}) ...")
    t0 = time.time()
    review = analyze_trajectory(
        traj, n_before=args.n_before, n_alt=args.n_alt, topk=args.topk,
        workers=args.workers, max_decisions=args.max_decisions,
        progress=lambda d, n: print(f"  {d}/{n} decisions ({time.time()-t0:.0f}s)", flush=True),
    )
    with open(args.out + ".review.json", "w") as f:
        json.dump(review, f)
    print(f"\nDone in {time.time()-t0:.0f}s -> {args.out}.review.json")

    # Quick textual summary.
    print("\nReport cards:")
    for c, rc in review["report_cards"].items():
        print(f"  {c:6} acc={rc['accuracy']:5}  decisions={rc['decisions']:3}  {rc['label_counts']}")
    print("\nTop critical moments:")
    for m in review["critical_moments"][:5]:
        print(f"  T{m['turn']:>3} {m['actor']:6} {m['label']:9} -{m['wp_loss']:.2f}  {m['annotation'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
