"""Game-format & reproducibility tests (brief §6.3)."""
import json
import os
import tempfile

from catan_review.engine import GameConfig, new_game, run_game
from catan_review.policy import REFERENCE
from catan_review.gamelog import (
    GameLog, board_geometry, action_to_dict, action_from_dict,
)


def test_seed_determinism():
    a = run_game(GameConfig(seed=321), REFERENCE)
    b = run_game(GameConfig(seed=321), REFERENCE)
    assert [action_to_dict(p.chosen) for p in a.plies] == [action_to_dict(p.chosen) for p in b.plies]
    assert a.winner == b.winner


def test_action_serialization_roundtrip():
    traj = run_game(GameConfig(seed=5), REFERENCE)
    for p in traj.plies:
        d = action_to_dict(p.chosen)
        again = action_to_dict(action_from_dict(d))
        assert again == d


def test_gamelog_save_load():
    traj = run_game(GameConfig(seed=9), REFERENCE)
    log = GameLog.from_trajectory(traj)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "g.log.json")
        log.save(path)
        loaded = GameLog.load(path)
    assert loaded.version == log.version
    assert loaded.actions == log.actions
    assert loaded.result["winner"] == (traj.winner.value if traj.winner else None)


def test_board_geometry_standard_counts():
    geo = board_geometry(new_game(GameConfig(seed=1)))
    assert len(geo["tiles"]) == 19          # 18 resource + 1 desert
    assert len(geo["nodes"]) == 54          # land intersections
    assert len(geo["edges"]) == 72          # land edges
    assert len(geo["ports"]) >= 5           # 5 resource groups (+ generic)
    # exactly one desert, correct terrain counts
    from collections import Counter
    res = Counter(t["resource"] for t in geo["tiles"])
    assert res[None] == 1                   # desert has no resource
    assert sum(v for k, v in res.items() if k) == 18
