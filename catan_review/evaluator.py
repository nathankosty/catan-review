"""Win-probability evaluator: "Stockfish for Catan" (brief §3).

The one question this answers: *for a given state, what is each player's
probability of winning from here?*  WP(state, player) in [0,1], summing to 1
across players (§3.1), the only metric that's meaningful in a stochastic,
multiplayer, hidden-info game.

v1 method (recorded in DECISIONS.md): **Monte-Carlo rollouts to terminal** under
the fixed reference rollout policy (§3.2a, the validated "playouts property").
This needs no training, is faithful, and yields honest confidence intervals.
A learned value function is the documented growth path for speed (§3.2b).

Honesty (§10): every estimate carries a 95% confidence half-width derived from
the rollout count. ``PERFECT_INFO`` is True for v1, so rollouts see the true
hidden state (opponent hands, deck order). This is a *flagged approximation*;
the determinization hook (§3.3) is where a belief model will plug in.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from catanatron import Game, Color, Action

from .policy import ROLLOUT

# v1 evaluates with full information and labels it as such in the UI (§3.3, §10).
PERFECT_INFO = True
ROLLOUT_WATCHDOG = 5000
_Z95 = 1.96


@dataclass
class WPEstimate:
    """Per-player win probability with uncertainty."""

    wp: Dict[str, float]                 # color.value -> win probability
    ci: Dict[str, float]                 # color.value -> 95% half-width
    n: int                               # rollouts behind the estimate
    perfect_info: bool = PERFECT_INFO
    policy: str = "reference(eps=0.30)"

    def of(self, color) -> float:
        return self.wp.get(color.value if isinstance(color, Color) else color, 0.0)

    def ci_of(self, color) -> float:
        return self.ci.get(color.value if isinstance(color, Color) else color, 0.0)

    def to_json(self) -> dict:
        return {
            "wp": self.wp,
            "ci": self.ci,
            "n": self.n,
            "perfect_info": self.perfect_info,
            "policy": self.policy,
        }


def _rollout_winner(src: Game, seed: int) -> Optional[Color]:
    # Catanatron's dice/draws use the *global* `random`, so we seed it per rollout
    # to make every estimate a pure function of (state, seed), giving reproducible runs
    # (§10). The policy gets its own independent stream.
    random.seed(seed)
    rng = random.Random((seed * 2654435761) & 0xFFFFFFFFFFFF)
    g = src.copy()
    steps = 0
    while g.winning_color() is None and steps < ROLLOUT_WATCHDOG:
        g.execute(ROLLOUT(g, rng))
        steps += 1
    return g.winning_color()


def determinize(game: Game, rng: random.Random) -> Game:
    """Hidden-information hook (§3.3).

    v1: perfect-information approximation: return the true state unchanged and
    let the caller flag it. A determinizer (resample opponent hands / deck order
    consistent with public info) drops in here without touching callers."""
    return game


def evaluate_state(
    game: Game,
    n: int = 60,
    base_seed: int = 0,
    determinize_samples: int = 1,
) -> WPEstimate:
    """Estimate WP for every player by Monte-Carlo rollout to terminal.

    ``determinize_samples`` averages over K determinized worlds (v1: 1 world,
    perfect info). Each rollout uses an independent rng so dice/decisions vary."""
    colors = list(game.state.colors)
    wins: Dict[str, float] = {c.value: 0.0 for c in colors}
    total = 0
    for d in range(max(1, determinize_samples)):
        world = determinize(game, random.Random(base_seed * 7919 + d))
        for i in range(n):
            w = _rollout_winner(world, base_seed * 1_000_003 + d * 1009 + i)
            total += 1
            if w is not None:
                wins[w.value] += 1.0
    denom = float(total) if total else 1.0
    wp = {c: wins[c] / denom for c in wins}
    ci = {c: _Z95 * math.sqrt(max(wp[c] * (1 - wp[c]), 1e-9) / denom) for c in wp}
    return WPEstimate(wp=wp, ci=ci, n=total)


def evaluate_action(
    game: Game,
    action: Action,
    n: int = 60,
    base_seed: int = 0,
    determinize_samples: int = 1,
) -> WPEstimate:
    """WP of the position *after* applying ``action`` (validation off, since the
    action came from this state's legal set)."""
    g = game.copy()
    g.execute(action, validate_action=False)
    return evaluate_state(g, n=n, base_seed=base_seed + 17, determinize_samples=determinize_samples)
