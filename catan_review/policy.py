"""Reference & rollout policies: the "opponent model" (brief §3.4).

WP only means something relative to how players play (§3.1). We define ONE fixed,
reasonably-strong heuristic policy and use it consistently:

  * to generate sample self-play games,
  * as the rollout policy inside the Monte-Carlo evaluator, and
  * as the counterfactual opponent for "what if I'd played X" (§3.4).

The policy is a pure function of (state, rng) so the evaluator is reproducible.
A small epsilon injects the stochasticity Monte-Carlo needs to explore lines.
``random_policy`` is also provided: pure-random rollouts are the theoretically
validated baseline (Catanatron's "playouts property", §3.2a).
"""
from __future__ import annotations

import random
from typing import List

from catanatron import Game, Action, ActionType
import catanatron.state_functions as sf

AT = ActionType

# Coarse desirability of each action *kind*. Building/army beats trading beats
# passing; ROLL/DISCARD are effectively forced and just need to happen.
TYPE_PRIORITY = {
    AT.BUILD_CITY: 100.0,
    AT.BUILD_SETTLEMENT: 90.0,
    AT.MOVE_ROBBER: 72.0,
    AT.PLAY_YEAR_OF_PLENTY: 62.0,
    AT.PLAY_MONOPOLY: 60.0,
    AT.BUY_DEVELOPMENT_CARD: 58.0,
    AT.PLAY_KNIGHT_CARD: 56.0,
    AT.PLAY_ROAD_BUILDING: 54.0,
    AT.BUILD_ROAD: 50.0,
    AT.MARITIME_TRADE: 30.0,
    AT.ROLL: 80.0,
    AT.DISCARD: 80.0,
    AT.END_TURN: 1.0,
}


def _node_value(game: Game, node_id) -> float:
    """Expected resources/roll produced at a node (pip strength of the spot)."""
    prod = game.state.board.map.node_production.get(node_id)
    return float(sum(prod.values())) if prod else 0.0


def _robber_value(game: Game, action: Action) -> float:
    """Prefer robbing a high-VP / card-rich opponent; avoid a no-steal placement."""
    coord, victim, _card = action.value
    if victim is None:
        return -5.0
    try:
        return 2.0 * sf.get_actual_victory_points(game.state, victim) + 0.5 * sf.player_num_resource_cards(
            game.state, victim
        )
    except Exception:
        return 0.0


def _score(game: Game, action: Action) -> float:
    t = action.action_type
    base = TYPE_PRIORITY.get(t, 10.0)
    if t in (AT.BUILD_SETTLEMENT, AT.BUILD_CITY):
        return base + 12.0 * _node_value(game, action.value)
    if t == AT.MOVE_ROBBER:
        return base + _robber_value(game, action)
    return base


def make_policy(epsilon: float = 0.0):
    """Return a policy(game, rng) -> Action.

    ``epsilon`` is the probability of an exploratory (score-weighted random)
    choice; 0 = greedy. Ties are broken by ``rng`` so reproducibility holds."""

    def policy(game: Game, rng: random.Random) -> Action:
        # Canonicalize order so choices don't depend on hash-set iteration order
        # (reproducible across processes regardless of PYTHONHASHSEED).
        actions: List[Action] = sorted(
            game.state.playable_actions, key=lambda a: (a.action_type.value, str(a.value))
        )
        if len(actions) == 1:
            return actions[0]
        scores = [_score(game, a) for a in actions]
        if epsilon and rng.random() < epsilon:
            # Softmax-ish exploration: weight by score so it stays plausible.
            lo = min(scores)
            weights = [max(s - lo, 0.0) + 1.0 for s in scores]
            return rng.choices(actions, weights=weights, k=1)[0]
        best = max(scores)
        top = [a for a, s in zip(actions, scores) if s >= best - 1e-9]
        return rng.choice(top)

    return policy


def random_policy(game: Game, rng: random.Random) -> Action:
    """Uniform random over legal actions: the validated rollout baseline."""
    return rng.choice(game.state.playable_actions)


# The canonical reference policy used across generation and evaluation.
REFERENCE = make_policy(epsilon=0.05)        # near-greedy: for generating games
ROLLOUT = make_policy(epsilon=0.30)          # exploratory: for Monte-Carlo rollouts
