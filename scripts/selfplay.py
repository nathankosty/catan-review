"""Self-play harness + anti-deadlock check (brief §5, §2.8a test).

Runs a batch of all-bot games and asserts every one *finishes* in bounded time
(no watchdog trips, a real winner). With no domestic trading yet there is no
negotiation to loop, but the watchdog and this batch test are the harness the
trade subsystem will have to pass before it ships.

Usage:
    python -m scripts.selfplay --games 2000           # termination stress test
    python -m scripts.selfplay --games 5 --emit data/games   # save sample logs
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

from catan_review.engine import GameConfig, run_game
from catan_review.policy import REFERENCE
from catan_review.gamelog import GameLog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--players", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--emit", type=str, default=None, help="dir to write sample game logs")
    args = ap.parse_args()

    wins = Counter()
    turns = []
    failures = []
    t0 = time.time()
    for i in range(args.games):
        cfg = GameConfig(num_players=args.players, seed=args.seed + i)
        capture = args.emit is not None
        traj = run_game(cfg, REFERENCE, capture=capture)
        if traj.hit_watchdog or traj.winner is None:
            failures.append((i, traj.hit_watchdog, traj.winner))
        else:
            wins[traj.winner.value] += 1
            turns.append(traj.num_turns)
        if args.emit:
            GameLog.from_trajectory(traj).save(os.path.join(args.emit, f"selfplay_seed{cfg.seed}.log.json"))

    dt = time.time() - t0
    print(f"\nRan {args.games} games in {dt:.1f}s ({args.games/dt:.0f} games/sec)")
    print(f"Win distribution: {dict(wins)}")
    if turns:
        print(f"Turns: min={min(turns)} avg={sum(turns)/len(turns):.1f} max={max(turns)}")
    if failures:
        print(f"\n*** TERMINATION FAILURES: {len(failures)} game(s) hung/stalled ***")
        for f in failures[:10]:
            print("   game", f)
        return 1
    print("\n✓ All games terminated cleanly (no watchdog trips, every game has a winner).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
