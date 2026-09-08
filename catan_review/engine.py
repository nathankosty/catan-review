"""Thin wrapper over Catanatron: the rules/simulation core (brief §1.1, §7).

Why Catanatron: it already encodes the *complete* base game (board, production,
robber, dev cards, building, longest-road / largest-army, win condition), runs
~50 games/sec single-threaded, is seed-deterministic, and exposes ``Game.copy()``
and exactly what rollouts (§3.2a) and determinization (§3.3) need. We keep every
other layer behind this wrapper so the engine could be swapped wholesale.

Known gap (recorded in DECISIONS.md): Catanatron has no *domestic* (player-to-
player) trade actions. The trade subsystem (§2.8 / §2.8a) is layered on top
separately and is deferred per the agreed build order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence
import random

from catanatron import Game, Color, Action, ActionType
from catanatron.models.player import Player
import catanatron.state_functions as sf

# Canonical Catanatron seating order. We always read identity back from the
# live state rather than assuming, but need a stable list to construct games.
SEAT_ORDER = [Color.RED, Color.BLUE, Color.ORANGE, Color.WHITE]

RESOURCES = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"]
DEV_CARDS = ["KNIGHT", "YEAR_OF_PLENTY", "MONOPOLY", "ROAD_BUILDING", "VICTORY_POINT"]

# Hard safety net (brief §2.8a "per-turn action watchdog" / §3.5 "never hang").
# A legal base-game game is bounded; this only ever fires on a bug.
ACTION_WATCHDOG = 6000


# A policy maps (game, rng) -> a legal Action chosen from game.state.playable_actions.
Policy = Callable[[Game, random.Random], Action]


class _Seat(Player):
    """Placeholder player. We drive games ourselves via ``Game.execute`` so the
    engine's own decision loop is never consulted; this only fixes seat colors."""

    def decide(self, game, playable_actions):  # pragma: no cover - never called
        return playable_actions[0]


@dataclass
class GameConfig:
    """Game options. The toggles map straight onto Catanatron's constructor and
    onto the brief's configurable variants (§2.9)."""

    num_players: int = 4
    seed: Optional[int] = None
    discard_limit: int = 7      # cards above which a 7 forces a discard (§2.4)
    vps_to_win: int = 10        # victory points to win (§2.9 toggle)

    def colors(self) -> List[Color]:
        return SEAT_ORDER[: self.num_players]


def new_game(config: GameConfig) -> Game:
    players = [_Seat(c) for c in config.colors()]
    return Game(
        players,
        seed=config.seed,
        discard_limit=config.discard_limit,
        vps_to_win=config.vps_to_win,
    )


# --------------------------------------------------------------------------- #
# State accessors (everything downstream reads identity/score through these)
# --------------------------------------------------------------------------- #

def current_color(game: Game) -> Color:
    return game.state.current_color()


def playable_actions(game: Game) -> List[Action]:
    return list(game.state.playable_actions)


def is_decision(game: Game) -> bool:
    """A choice worth classifying. Forced moves (one legal action) are excluded
    from accuracy stats (§4.1 'Do not classify forced decisions')."""
    return len(game.state.playable_actions) > 1


def decision_prompt(game: Game) -> str:
    return str(getattr(game.state, "current_prompt", "PLAY_TURN")).split(".")[-1]


def winner(game: Game) -> Optional[Color]:
    return game.winning_color()


def victory_points(game: Game, color: Color) -> int:
    """True VP including hidden VP dev cards (used for win detection)."""
    return sf.get_actual_victory_points(game.state, color)


def public_victory_points(game: Game, color: Color) -> int:
    """VP visible to opponents (hidden VP cards excluded)."""
    return sf.get_visible_victory_points(game.state, color)


def player_summary(game: Game, color: Color) -> dict:
    s = game.state
    return {
        "color": color.value,
        "vp": victory_points(game, color),
        "public_vp": public_victory_points(game, color),
        "longest_road_len": sf.get_longest_road_length(s, color),
        "played_knights": sf.get_played_dev_cards(s, color, "KNIGHT"),
        "dev_cards_in_hand": sf.get_dev_cards_in_hand(s, color),
        "resources": sf.player_num_resource_cards(s, color),
        "has_longest_road": sf.get_longest_road_color(s) == color,
        "has_largest_army": (sf.get_largest_army(s) or (None,))[0] == color,
    }


# --------------------------------------------------------------------------- #
# Driving a whole game with our own policy (gives us the watchdog for free)
# --------------------------------------------------------------------------- #

@dataclass
class Ply:
    """One executed action. ``game`` is a *copy of the state before* the action,
    so the analyzer can re-evaluate alternatives from here."""

    index: int
    actor: Color
    prompt: str
    playable_actions: List[Action]
    chosen: Action
    game_before: Game
    is_decision: bool


@dataclass
class Trajectory:
    config: GameConfig
    colors: List[Color]
    plies: List[Ply]
    winner: Optional[Color]
    num_turns: int
    hit_watchdog: bool = False


def run_game(config: GameConfig, policy: Policy, capture: bool = True) -> Trajectory:
    """Play one complete game under ``policy``, capturing per-ply snapshots.

    Deterministic given ``config.seed`` (engine RNG) and a policy seeded from it.
    The watchdog guarantees termination regardless of policy bugs (§2.8a)."""
    game = new_game(config)
    rng = random.Random(config.seed if config.seed is not None else 0)
    plies: List[Ply] = []
    hit_watchdog = False

    while game.winning_color() is None:
        if len(game.state.actions) >= ACTION_WATCHDOG:
            hit_watchdog = True
            break
        pa = list(game.state.playable_actions)
        actor = game.state.current_color()
        prompt = decision_prompt(game)
        chosen = policy(game, rng)
        if capture:
            plies.append(
                Ply(
                    index=len(plies),
                    actor=actor,
                    prompt=prompt,
                    playable_actions=pa,
                    chosen=chosen,
                    game_before=game.copy(),
                    is_decision=len(pa) > 1,
                )
            )
        game.execute(chosen)

    return Trajectory(
        config=config,
        colors=list(game.state.colors),
        plies=plies,
        winner=game.winning_color(),
        num_turns=game.state.num_turns,
        hit_watchdog=hit_watchdog,
    )
