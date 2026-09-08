"""Fast learned value function: instant WP for live play (brief §3.2b).

The Monte-Carlo evaluator (evaluator.py) is the calibration ground truth, but at
~10-25 ms per rollout it cannot give feedback *as you play*, especially in the
browser (Pyodide/WASM), where live play runs. This module is the documented
growth path: a small model, trained offline on self-play outcomes, that maps a
state to per-player win probability in microseconds.

Design constraints:
  * **Pure-Python inference.** No numpy at runtime, so the same file runs
    unchanged in Pyodide without pulling a 7 MB wheel. Training (numpy) lives
    in scripts/train_value.py; this file only extracts features and does the
    forward pass.
  * **Permutation-equivariant.** One shared scorer s(f_i) per player, then a
    softmax across however many players are seated, so WP sums to 1 by
    construction (§3.1) and 3- and 4-player games share one model.
  * **Honesty (§10).** The model's pairwise-ranking error vs rollout ground
    truth is measured offline and stored in the model file (``sigma_pair``);
    the classifier uses it as the confidence interval, so value-net labels
    keep the same noise discipline as rollout labels.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional

from catanatron import Game, Color, Action
import catanatron.state_functions as sf
from catanatron.models.decks import (
    SETTLEMENT_COST_FREQDECK, CITY_COST_FREQDECK, ROAD_COST_FREQDECK,
    DEVELOPMENT_CARD_COST_FREQDECK, freqdeck_contains,
)

RESOURCES = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"]

FEATURE_NAMES: List[str] = [
    "vp", "public_vp", "settlements", "cities",
    "prod_wood", "prod_brick", "prod_sheep", "prod_wheat", "prod_ore",
    "prod_total", "prod_diversity",
    "has_3to1", "ports_2to1_useful",
    "road_len", "has_longest_road",
    "knights", "has_largest_army",
    "dev_in_hand", "hand_size", "over_7",
    "can_settle", "can_city", "can_dev", "can_road",
    "expansion_spots",
    "vp_gap", "prod_gap", "is_current",
]


def _pip(number: Optional[int]) -> float:
    """Probability a token number is rolled on 2d6."""
    return 0.0 if number is None else (6.0 - abs(7.0 - number)) / 36.0


def _production(game: Game, color: Color) -> List[float]:
    """Expected cards/roll per resource, robber-aware (blocked hex yields 0)."""
    s, b = game.state, game.state.board
    m = b.map
    robber_tile = m.land_tiles.get(b.robber_coordinate)
    robber_id = robber_tile.id if robber_tile is not None else None
    prod = [0.0] * 5
    for kind, mult in (("SETTLEMENT", 1.0), ("CITY", 2.0)):
        for nid in sf.get_player_buildings(s, color, kind):
            for tile in m.adjacent_tiles[nid]:
                res = getattr(tile, "resource", None)
                if res is None or getattr(tile, "id", None) == robber_id:
                    continue
                prod[RESOURCES.index(res)] += mult * _pip(tile.number)
    return prod


def extract_features(game: Game, color: Color, *, _cache: Optional[dict] = None) -> List[float]:
    """The per-player feature vector (see FEATURE_NAMES). ``_cache`` shares
    per-state aggregates (e.g. every player's production) across the players
    of one state so a 4-player extraction does the board walk once each."""
    s = game.state
    b = s.board
    cache = _cache if _cache is not None else {}

    if "prods" not in cache:
        cache["prods"] = {c: _production(game, c) for c in s.colors}
        cache["vps"] = {c: sf.get_actual_victory_points(s, c) for c in s.colors}
        cache["current"] = s.current_color()
        cache["la_color"] = (sf.get_largest_army(s) or (None,))[0]
        cache["lr_color"] = sf.get_longest_road_color(s)
    prods: Dict[Color, List[float]] = cache["prods"]
    vps: Dict[Color, int] = cache["vps"]

    prod = prods[color]
    prod_total = sum(prod)
    key = sf.player_key(s, color)
    hand = [s.player_state[f"{key}_{r}_IN_HAND"] for r in RESOURCES]
    hand_size = sum(hand)

    ports = set(b.get_player_port_resources(color))
    useful_2to1 = sum(
        1 for i, r in enumerate(RESOURCES) if r in ports and prod[i] > 0.05
    )

    n_settle = len(sf.get_player_buildings(s, color, "SETTLEMENT"))
    n_city = len(sf.get_player_buildings(s, color, "CITY"))
    road_len = sf.get_longest_road_length(s, color)
    vp = vps[color]
    max_other_vp = max((v for c, v in vps.items() if c != color), default=0)
    max_other_prod = max(
        (sum(p) for c, p in prods.items() if c != color), default=0.0
    )

    return [
        vp / 10.0,
        sf.get_visible_victory_points(s, color) / 10.0,
        n_settle / 5.0,
        n_city / 4.0,
        prod[0] / 0.35, prod[1] / 0.35, prod[2] / 0.35, prod[3] / 0.35, prod[4] / 0.35,
        prod_total / 1.2,
        sum(1 for p in prod if p > 0.02) / 5.0,
        1.0 if None in ports else 0.0,
        useful_2to1 / 2.0,
        road_len / 15.0,
        1.0 if cache["lr_color"] == color else 0.0,
        sf.get_played_dev_cards(s, color, "KNIGHT") / 4.0,
        1.0 if cache["la_color"] == color else 0.0,
        sf.get_dev_cards_in_hand(s, color) / 5.0,
        hand_size / 10.0,
        1.0 if hand_size > 7 else 0.0,
        1.0 if freqdeck_contains(hand, SETTLEMENT_COST_FREQDECK) else 0.0,
        1.0 if freqdeck_contains(hand, CITY_COST_FREQDECK) else 0.0,
        1.0 if freqdeck_contains(hand, DEVELOPMENT_CARD_COST_FREQDECK) else 0.0,
        1.0 if freqdeck_contains(hand, ROAD_COST_FREQDECK) else 0.0,
        min(len(b.buildable_node_ids(color)), 6) / 6.0,
        (vp - max_other_vp) / 10.0,
        (prod_total - max_other_prod) / 1.2,
        1.0 if cache["current"] == color else 0.0,
    ]


class ValueModel:
    """Shared-scorer MLP + softmax over seated players. Pure-Python forward."""

    def __init__(self, params: dict):
        self.W1: List[List[float]] = params["W1"]  # [hidden][n_features]
        self.b1: List[float] = params["b1"]
        self.W2: List[float] = params["W2"]        # [hidden]
        self.b2: float = params["b2"]
        self.meta: dict = params.get("meta", {})
        self.sigma_pair: float = float(self.meta.get("sigma_pair", 0.05))
        if len(self.W1[0]) != len(FEATURE_NAMES):
            raise ValueError(
                f"model expects {len(self.W1[0])} features, code has {len(FEATURE_NAMES)}"
            )

    @staticmethod
    def load(path: str) -> "ValueModel":
        with open(path) as f:
            return ValueModel(json.load(f))

    def score(self, feats: List[float]) -> float:
        h_sum = self.b2
        for j, (row, bj) in enumerate(zip(self.W1, self.b1)):
            a = bj
            for w, x in zip(row, feats):
                a += w * x
            if a > 0.0:  # ReLU
                h_sum += self.W2[j] * a
        return h_sum

    def predict_wp(self, game: Game) -> Dict[str, float]:
        """Per-player win probability for the current state (sums to 1)."""
        w = game.winning_color()
        colors = list(game.state.colors)
        if w is not None:
            return {c.value: (1.0 if c == w else 0.0) for c in colors}
        cache: dict = {}
        scores = [self.score(extract_features(game, c, _cache=cache)) for c in colors]
        mx = max(scores)
        exps = [math.exp(s - mx) for s in scores]
        z = sum(exps)
        return {c.value: e / z for c, e in zip(colors, exps)}

    def predict_after(self, game: Game, action: Action) -> Dict[str, float]:
        """WP after applying ``action`` (single sample of any randomness,
        e.g. which card a robber steal takes; documented approximation)."""
        g = game.copy()
        g.execute(action, validate_action=False)
        return self.predict_wp(g)
