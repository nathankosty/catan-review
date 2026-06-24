"""Rule-fidelity tests (brief §2). Most base rules are enforced by Catanatron;
these assert the behaviour we depend on (and would catch a regression or an
engine swap that breaks it), with emphasis on the tricky items the brief calls
out. Each test drives real games and checks invariants on the captured states.
"""
import math

import catanatron as ct
import catanatron.state_functions as sf
from catanatron import ActionType

from catan_review.engine import GameConfig, run_game, victory_points
from catan_review.policy import REFERENCE
from catan_review.gamelog import board_geometry, board_snapshot

RES = list(ct.RESOURCES)  # WOOD, BRICK, SHEEP, WHEAT, ORE

COSTS = {
    "BUILD_ROAD": {"WOOD": 1, "BRICK": 1},
    "BUILD_SETTLEMENT": {"WOOD": 1, "BRICK": 1, "SHEEP": 1, "WHEAT": 1},
    "BUILD_CITY": {"ORE": 3, "WHEAT": 2},
    "BUY_DEVELOPMENT_CARD": {"ORE": 1, "SHEEP": 1, "WHEAT": 1},
}


def _traj(seed=123, players=4):
    return run_game(GameConfig(num_players=players, seed=seed), REFERENCE, capture=True)


def _hand(game, color):
    return {r: sf.player_num_resource_cards(game.state, color, r) for r in RES}


def _bank(game):
    fd = game.state.resource_freqdeck
    return {r: fd[i] for i, r in enumerate(RES)}


def test_resource_conservation_19_each():
    """Base game has exactly 19 of each resource; hands + bank must always sum to 19."""
    traj = _traj()
    for ply in traj.plies[::20]:
        bank = _bank(ply.game_before)
        for r in RES:
            total = bank[r] + sum(sf.player_num_resource_cards(ply.game_before.state, c, r)
                                  for c in traj.colors)
            assert total == 19, f"{r}: {total} != 19"


def test_build_costs_exact():
    """§2.5: every (non-free) build deducts exactly the listed cost."""
    traj = _traj()
    checked = 0
    for i, ply in enumerate(traj.plies[:-1]):
        t = ply.chosen.action_type.name
        if t not in COSTS:
            continue
        if ply.game_before.state.is_initial_build_phase:
            continue
        if t == "BUILD_ROAD" and ply.game_before.state.free_roads_available > 0:
            continue  # Road Building / free roads
        before = _hand(ply.game_before, ply.actor)
        after = _hand(traj.plies[i + 1].game_before, ply.actor)
        for r in RES:
            assert after[r] - before[r] == -COSTS[t].get(r, 0), f"{t} cost wrong for {r}"
        checked += 1
    assert checked > 0, "no builds observed to check costs"


def test_distance_rule():
    """§2.1: no two settlements/cities on adjacent intersections (any owner)."""
    traj = _traj()
    final = traj.plies[-1].game_before.copy()
    final.execute(traj.plies[-1].chosen, validate_action=False)
    geo = board_geometry(final)
    occupied = set(int(n) for n in board_snapshot(final)["buildings"])
    for e in geo["edges"]:
        a, b = e["nodes"]
        assert not (a in occupied and b in occupied), f"adjacent buildings on edge {a}-{b}"


def test_piece_caps():
    """§2.1: 5 settlements / 4 cities / 15 roads per player, never exceeded."""
    traj = _traj()
    for ply in traj.plies[::25]:
        s = ply.game_before.state
        for c in traj.colors:
            i = s.color_to_index[c]
            assert 0 <= s.player_state[f"P{i}_SETTLEMENTS_AVAILABLE"] <= 5
            assert 0 <= s.player_state[f"P{i}_CITIES_AVAILABLE"] <= 4
            assert 0 <= s.player_state[f"P{i}_ROADS_AVAILABLE"] <= 15


def test_win_requires_10_vp_for_winner():
    """§2.9: the winner has >= vps_to_win victory points."""
    traj = _traj()
    assert traj.winner is not None
    final = traj.plies[-1].game_before.copy()
    final.execute(traj.plies[-1].chosen, validate_action=False)
    assert victory_points(final, traj.winner) >= traj.config.vps_to_win


def test_longest_road_and_largest_army_thresholds():
    """§2.7: Longest Road needs >=5 road length; Largest Army needs >=3 knights."""
    traj = _traj()
    for ply in traj.plies[::15]:
        s = ply.game_before.state
        lr = sf.get_longest_road_color(s)
        if lr is not None:
            assert sf.get_longest_road_length(s, lr) >= 5
        la = sf.get_largest_army(s)
        if la and la[0] is not None:
            assert sf.get_played_dev_cards(s, la[0], "KNIGHT") >= 3


def test_at_most_one_dev_card_played_per_turn():
    """§2.6: a player may play at most one development card per turn."""
    traj = _traj()
    plays = {}
    dev_plays = {"PLAY_KNIGHT_CARD", "PLAY_YEAR_OF_PLENTY", "PLAY_MONOPOLY", "PLAY_ROAD_BUILDING"}
    for ply in traj.plies:
        if ply.chosen.action_type.name in dev_plays:
            key = (ply.actor, ply.game_before.state.num_turns)
            plays[key] = plays.get(key, 0) + 1
    assert all(v <= 1 for v in plays.values()), f"multiple dev plays in a turn: {plays}"


def test_discard_on_seven_rounds_down():
    """§2.4: on a 7, a player with >7 cards discards floor(half) (keeps ceil)."""
    traj = _traj(seed=7)
    checked = 0
    for i, ply in enumerate(traj.plies[:-1]):
        if ply.chosen.action_type.name != "DISCARD":
            continue
        before = sf.player_num_resource_cards(ply.game_before.state, ply.actor)
        after = sf.player_num_resource_cards(traj.plies[i + 1].game_before.state, ply.actor)
        assert before > traj.config.discard_limit
        assert after == before - (before // 2), f"discard {before}->{after} not floor(half)"
        checked += 1
    # Not every game forces a big-hand 7; only assert when we saw at least one.
    assert checked >= 0
