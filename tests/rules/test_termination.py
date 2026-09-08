"""Anti-deadlock / termination stress test (brief §2.8a, release blocker).

The game must NEVER hang. We run a large batch of all-bot games and assert every
one finishes with a real winner and without tripping the action watchdog. With
no domestic trading yet there is no negotiation loop to hit, but this is the gate
the trade subsystem will have to pass when it lands.
"""
import pytest

from catan_review.engine import GameConfig, run_game, ACTION_WATCHDOG
from catan_review.policy import REFERENCE


@pytest.mark.parametrize("players", [3, 4])
def test_all_games_terminate(players):
    N = 200
    for i in range(N):
        traj = run_game(GameConfig(num_players=players, seed=10_000 * players + i),
                        REFERENCE, capture=False)
        assert not traj.hit_watchdog, f"game {i} tripped the action watchdog"
        assert traj.winner is not None, f"game {i} ended with no winner"


def test_action_count_bounded():
    # A clean game is far below the watchdog cap.
    traj = run_game(GameConfig(seed=42), REFERENCE, capture=True)
    assert len(traj.plies) < ACTION_WATCHDOG
    assert traj.num_turns < 1000
