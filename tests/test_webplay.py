"""Tests for the live-play session (webplay) and the fast value model."""
import json
import random

import pytest

from catan_review.quickeval import ValueModel, extract_features, FEATURE_NAMES
from catan_review.engine import GameConfig, new_game
from catan_review import webplay

MODEL_PATH = "data/value_model.json"
LABELS = {"Brilliant", "Great", "Best", "Excellent", "Good", "Book",
          "Inaccuracy", "Mistake", "Miss", "Blunder"}


@pytest.fixture(scope="module")
def model_json():
    with open(MODEL_PATH) as f:
        return f.read()


@pytest.fixture(scope="module")
def model(model_json):
    return ValueModel(json.loads(model_json))


def test_features_match_names():
    game = new_game(GameConfig(num_players=4, seed=3))
    feats = extract_features(game, game.state.colors[0])
    assert len(feats) == len(FEATURE_NAMES)
    assert all(isinstance(f, float) for f in feats)


def test_wp_sums_to_one(model):
    for np_ in (3, 4):
        game = new_game(GameConfig(num_players=np_, seed=11))
        wp = model.predict_wp(game)
        assert len(wp) == np_
        assert abs(sum(wp.values()) - 1.0) < 1e-9
        assert all(0.0 <= v <= 1.0 for v in wp.values())


def test_model_has_calibration(model):
    assert 0.02 <= model.sigma_pair <= 0.2, "sigma_pair missing or implausible"


def _play_scripted_game(model_json, seed=5, pick=0):
    """Play a full game clicking deterministically; return the final review."""
    state = json.loads(webplay.start_session(model_json, seed, "RED", 4))
    rng = random.Random(seed)
    guard = 0
    while not state["over"]:
        guard += 1
        assert guard < 5000, "game did not terminate"
        if state["is_human_turn"] and state["legal_actions"]:
            aid = rng.randrange(len(state["legal_actions"])) if pick is None else \
                min(pick, len(state["legal_actions"]) - 1)
            res = json.loads(webplay.submit_action(aid))
            assert "error" not in res
            if res["feedback"]:
                assert res["feedback"]["label"] in LABELS
            state = res["state"]
        else:
            state = json.loads(webplay.advance())
    return json.loads(webplay.final_review())


def test_full_game_and_review_schema(model_json):
    review = _play_scripted_game(model_json, seed=5, pick=None)
    for k in ("version", "config", "players", "winner", "num_turns", "geometry",
              "timeline", "eval_graph", "final_frame", "report_cards",
              "critical_moments", "icons", "meta"):
        assert k in review, f"review missing {k}"
    assert review["winner"] is not None
    assert len(review["eval_graph"]) == len(review["timeline"]) + 1
    for entry in review["timeline"]:
        assert entry["classification"]["label"] in LABELS
        # wp values are rounded to 4 dp in the entry, so allow rounding slack
        assert abs(sum(entry["wp_after"].values()) - 1.0) < 5e-4
    # Best must be the engine's top choice (no best_action suggested).
    for entry in review["timeline"]:
        if entry["classification"]["label"] == "Best":
            assert entry["classification"]["best_action"] is None


def test_take_back_restores_and_replays_identically(model_json):
    state = json.loads(webplay.start_session(model_json, 21, "RED", 4))
    # reach the human's first decision
    guard = 0
    while not (state["is_human_turn"] and len(state["legal_actions"]) > 1):
        state = json.loads(webplay.advance())
        guard += 1
        assert guard < 100
    n_actions = len(state["legal_actions"])
    step_before = state["step"]  # bots may already have recorded decisions
    res1 = json.loads(webplay.submit_action(2))
    wp1 = res1["feedback"]["wp_after"]
    label1 = res1["feedback"]["label"]

    state = json.loads(webplay.take_back())
    assert state["is_human_turn"]
    assert len(state["legal_actions"]) == n_actions, "take-back must restore options"
    assert state["step"] == step_before

    # Replaying the same move must give the same evaluation (RNG restored).
    res2 = json.loads(webplay.submit_action(2))
    assert res2["feedback"]["wp_after"] == wp1
    assert res2["feedback"]["label"] == label1

    review = json.loads(webplay.final_review())
    assert review["meta"]["takebacks"] == 1
