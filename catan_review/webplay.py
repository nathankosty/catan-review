"""Live play session: human vs reference bots, with instant move feedback.

Runs *in the browser* under Pyodide (pure stdlib + catanatron + quickeval; no
numpy). The React UI drives it through small JSON-in/JSON-out methods.

The chess.com learning loop (the whole point of the app):
  1. You act -> the value function evaluates your choice against every legal
     alternative -> you get a label (Best / Book / Mistake / Blunder...) and a
     plain-English explanation immediately.
  2. You may take the move back and try again. Take-back restores the exact
     RNG state, so replaying the same move gives the same dice, so you can't
     fish for better rolls, only for better decisions.
  3. Every decision (yours and the bots') is classified as it happens, in the
     same schema as the offline analyzer, so when the game ends, the complete
     chess.com-style review of the game you just played is already assembled.

Honesty (§10): live evaluation is the trained value function, not Monte-Carlo
rollouts. Its measured pairwise error (sigma_pair, stored in the model file) is
used as the label CI, and the review is flagged "quick eval" accordingly.
"""
from __future__ import annotations

import json
import random
from typing import Dict, List, Optional

from catanatron import Game, Color, Action, ActionType
import catanatron.state_functions as sf

from . import __version__
from .engine import GameConfig, new_game, ACTION_WATCHDOG, RESOURCES
from .policy import REFERENCE, _score
from .quickeval import ValueModel, extract_features
from .classifier import Candidate, classify, accuracy_from_losses, ICONS
from .annotate import annotate
from .gamelog import board_geometry, board_snapshot, action_to_dict, action_to_human

AT = ActionType
DEV_TYPES = ["KNIGHT", "YEAR_OF_PLENTY", "MONOPOLY", "ROAD_BUILDING", "VICTORY_POINT"]

DISCLAIMER = (
    "Live evaluation uses a fast value model trained on self-play (measured "
    "pairwise error shown as the label confidence), with perfect information. "
    "It is a coach's instinct, not a deep search. Labels within its error "
    "margin are marked low-confidence."
)


def _phase_of(game: Game) -> str:
    if game.state.is_initial_build_phase:
        return "setup"
    lead = max(sf.get_visible_victory_points(game.state, c) for c in game.state.colors)
    return "early" if lead < 4 else ("mid" if lead < 7 else "late")


def _sorted_actions(game: Game) -> List[Action]:
    """Canonical action order (stable ids across identical states)."""
    return sorted(game.state.playable_actions, key=lambda a: (a.action_type.value, str(a.value)))


def _action_ui(a: Action, idx: int, game: Optional[Game] = None) -> dict:
    """JS-friendly serialization of one legal action, with board-click targets."""
    d: dict = {"id": idx, "type": a.action_type.name, "text": action_to_human(a, game)}
    v = a.value
    t = a.action_type
    if t in (AT.BUILD_SETTLEMENT, AT.BUILD_CITY):
        d["node"] = v
    elif t == AT.BUILD_ROAD:
        d["edge"] = sorted(list(v))
    elif t == AT.MOVE_ROBBER:
        coord, victim, _ = v
        d["coord"] = list(coord)
        d["victim"] = victim.value if isinstance(victim, Color) else victim
    elif t == AT.MARITIME_TRADE:
        gives = [x for x in v[:-1] if x]
        d["gives"] = gives
        d["receives"] = v[-1]
    elif t == AT.PLAY_MONOPOLY:
        d["resource"] = v if isinstance(v, str) else (v[0] if v else None)
    elif t == AT.PLAY_YEAR_OF_PLENTY:
        d["resources"] = [x for x in (v if isinstance(v, (list, tuple)) else [v]) if x]
    return d


def _action_target(a: Action) -> Optional[dict]:
    """Board location of an action, if it has one (drives the 📍 suggestion marker)."""
    t, v = a.action_type, a.value
    if t in (AT.BUILD_SETTLEMENT, AT.BUILD_CITY):
        return {"node": v}
    if t == AT.BUILD_ROAD:
        return {"edge": sorted(list(v))}
    if t == AT.MOVE_ROBBER:
        return {"coord": list(v[0])}
    return None


class PlaySession:
    def __init__(self, model_json: str, seed: int = 1, human_color: str = "RED",
                 num_players: int = 4, topk: int = 4):
        self.model = ValueModel(json.loads(model_json))
        self.config = GameConfig(num_players=num_players, seed=seed)
        self.game = new_game(self.config)
        self.rng = random.Random(seed * 7 + 3)
        self.human = Color(human_color)
        if self.human not in self.game.state.colors:
            self.human = self.game.state.colors[0]
        self.topk = topk

        self.geometry = board_geometry(self.game)
        self.timeline: List[dict] = []     # review-schema entries, all players
        self.eval_graph: List[dict] = []
        self.feed: List[dict] = []         # recent events for the UI ticker
        self.takebacks = 0
        self.pending: Optional[dict] = None   # feedback for the human's last move
        # Take-back stack: state *before* each human decision.
        self._snapshots: List[dict] = []

    # ------------------------------------------------------------------ #
    # Evaluation & classification of one decision (shared: human and bots)
    # ------------------------------------------------------------------ #

    def _wp_now(self, game: Game) -> Dict[str, float]:
        return self.model.predict_wp(game)

    def _classify_decision(self, game_before: Game, chosen: Action) -> dict:
        actor = game_before.state.current_color()
        phase = _phase_of(game_before)
        wp_before = self._wp_now(game_before)

        acts = _sorted_actions(game_before)
        # Heuristic ranking (drives Brilliant detection + candidate shortlist).
        heur = sorted(acts, key=lambda a: (-_score(game_before, a), a.action_type.value, str(a.value)))
        hrank = {id(a): r for r, a in enumerate(heur)}
        # Model CI per candidate, sized so the classifier's combined loss-CI
        # equals the measured pairwise error (see quickeval docstring).
        ci = 1.96 * self.model.sigma_pair / (2 ** 0.5)

        # Evaluate every legal action with the value model (cheap), keep the
        # chosen + the best few alternatives for classification/report.
        evaluated = []
        for a in acts:
            wp = self.model.predict_after(game_before, a)
            evaluated.append((a, wp))
        chosen_wp = next(wp for a, wp in evaluated if a == chosen)
        chosen_cand = Candidate(
            action=action_to_dict(chosen), actor_wp=chosen_wp.get(actor.value, 0.0),
            wp=chosen_wp, ci=ci, heuristic_rank=hrank.get(id(chosen), len(acts) - 1),
        )
        alts = sorted(
            (x for x in evaluated if x[0] != chosen),
            key=lambda x: -x[1].get(actor.value, 0.0),
        )[: self.topk]
        alt_cands = [
            Candidate(action=action_to_dict(a), actor_wp=wp.get(actor.value, 0.0),
                      wp=wp, ci=ci, heuristic_rank=hrank.get(id(a), len(acts) - 1))
            for a, wp in alts
        ]

        cls = classify(
            mover=actor, chosen=chosen_cand, alternatives=alt_cands,
            wp_before=wp_before.get(actor.value, 0.0), phase=phase,
            chosen_is_greedy_top=(hrank.get(id(chosen)) == 0),
        )
        best_text, best_target = None, None
        if cls.best_action is not None:
            best_a = next((a for a, _ in evaluated if action_to_dict(a) == cls.best_action), None)
            if best_a is not None:
                best_text = action_to_human(best_a, game_before)
                best_target = _action_target(best_a)
        note = annotate(
            label=cls.label, mover=actor.value, action_text=action_to_human(chosen, game_before),
            best_action_text=best_text, mover_wp_after=chosen_cand.actor_wp,
            best_wp=cls.best_wp, eff_loss=cls.eff_loss,
            wp_before=wp_before, wp_after=chosen_wp, low_confidence=cls.low_confidence,
        )
        cj = cls.to_json()
        cj["best_action_text"] = best_text
        cj["best_action_target"] = best_target
        step = len(self.timeline)
        entry = {
            "step": step, "ply_index": step, "turn": game_before.state.num_turns,
            "actor": actor.value, "phase": phase,
            "prompt": str(getattr(game_before.state, "current_prompt", "PLAY_TURN")).split(".")[-1],
            "action": {"dict": action_to_dict(chosen), "text": action_to_human(chosen, game_before)},
            "wp_before": {k: round(v, 4) for k, v in wp_before.items()},
            "wp_after": {k: round(v, 4) for k, v in chosen_wp.items()},
            "ci_before": {k: round(ci, 4) for k in wp_before},
            "classification": cj, "annotation": note,
            "board": board_snapshot(game_before),
        }
        return entry

    def _record(self, entry: dict) -> None:
        self.timeline.append(entry)
        self.eval_graph.append({
            "step": entry["step"], "turn": entry["turn"],
            "wp": entry["wp_before"], "ci": entry["ci_before"],
        })

    def _feed_add(self, actor: str, text: str, kind: str = "action", label: str = None) -> None:
        self.feed.append({"actor": actor, "text": text, "kind": kind, "label": label})
        del self.feed[:-40]

    # ------------------------------------------------------------------ #
    # Game flow
    # ------------------------------------------------------------------ #

    def advance(self) -> str:
        """Run bots (classifying their decisions) and auto-execute the human's
        forced non-ROLL actions, until the human must act or the game ends."""
        g = self.game
        guard = 0
        while g.winning_color() is None and guard < ACTION_WATCHDOG:
            guard += 1
            acts = g.state.playable_actions
            cur = g.state.current_color()
            if cur == self.human:
                if len(acts) > 1:
                    break  # human decision
                a = acts[0]
                if a.action_type == AT.ROLL:
                    break  # let the human press Roll themselves
                self._feed_add(cur.value, action_to_human(a, g), "forced")
                g.execute(a)
                continue
            # Bot move: classify decisions (>1 option) for the final review.
            if len(acts) > 1:
                chosen = REFERENCE(g, self.rng)
                entry = self._classify_decision(g.copy(), chosen)
                self._record(entry)
                self._feed_add(cur.value, action_to_human(chosen, g), "action",
                               entry["classification"]["label"])
                g.execute(chosen)
            else:
                a = acts[0]
                self._feed_add(cur.value, action_to_human(a, g), "forced")
                g.execute(a)
        return self.state_json()

    def submit(self, action_id: int) -> str:
        """Execute the human's chosen action; return feedback + new state."""
        acts = _sorted_actions(self.game)
        if not (0 <= action_id < len(acts)):
            return json.dumps({"error": f"bad action id {action_id}"})
        chosen = acts[action_id]
        is_decision = len(acts) > 1

        feedback = None
        if is_decision:
            # Snapshot for take-back: full game + RNG so a retried line replays
            # identically (no dice-fishing).
            self._snapshots.append({
                "game": self.game.copy(),
                "timeline_len": len(self.timeline),
                "feed_len": len(self.feed),
                "rng_state": self.rng.getstate(),
                "global_rng_state": random.getstate(),
            })
            del self._snapshots[:-20]
            entry = self._classify_decision(self.game.copy(), chosen)
            self._record(entry)
            c = entry["classification"]
            feedback = {
                "label": c["label"], "icon": ICONS.get(c["label"], "•"),
                "annotation": entry["annotation"],
                "eff_loss": c["eff_loss"],
                "wp_before": c["wp_before"], "wp_after": c["wp_after"],
                "delta": round(c["wp_after"] - c["wp_before"], 4),
                "best_wp": c["best_wp"], "best_action_text": c["best_action_text"],
                "best_action_target": c.get("best_action_target"),
                "low_confidence": c["low_confidence"],
                "action_text": entry["action"]["text"],
                "can_take_back": True,
            }
            self._feed_add(self.human.value, entry["action"]["text"], "human", c["label"])
        else:
            self._feed_add(self.human.value, action_to_human(chosen, self.game), "forced")

        self.game.execute(chosen)
        self.pending = feedback
        return json.dumps({"feedback": feedback, "state": json.loads(self.state_json())})

    def take_back(self) -> str:
        """Undo to just before the human's last classified decision."""
        if not self._snapshots:
            return json.dumps({"error": "nothing to take back"})
        snap = self._snapshots.pop()
        self.game = snap["game"]
        del self.timeline[snap["timeline_len"]:]
        del self.eval_graph[snap["timeline_len"]:]
        del self.feed[snap["feed_len"]:]
        self.rng.setstate(snap["rng_state"])
        random.setstate(snap["global_rng_state"])
        self.takebacks += 1
        self.pending = None
        self._feed_add(self.human.value, "took the move back", "takeback")
        return self.state_json()

    def hint(self) -> str:
        """The engine's suggested move for the current position (optional UI)."""
        acts = _sorted_actions(self.game)
        if len(acts) <= 1:
            return json.dumps({"hint": None})
        best_id, best_wp = 0, -1.0
        for i, a in enumerate(acts):
            wp = self.model.predict_after(self.game, a).get(self.human.value, 0.0)
            if wp > best_wp:
                best_id, best_wp = i, wp
        return json.dumps({"hint": {"id": best_id,
                                    "text": action_to_human(acts[best_id], self.game),
                                    "target": _action_target(acts[best_id]),
                                    "wp": round(best_wp, 3)}})

    # ------------------------------------------------------------------ #
    # State for the UI
    # ------------------------------------------------------------------ #

    def _human_hand(self) -> dict:
        s = self.game.state
        key = sf.player_key(s, self.human)
        return {
            "resources": {r: s.player_state[f"{key}_{r}_IN_HAND"] for r in RESOURCES},
            "dev_cards": {d: s.player_state[f"{key}_{d}_IN_HAND"] for d in DEV_TYPES},
            "played_knights": sf.get_played_dev_cards(s, self.human, "KNIGHT"),
            "actual_vp": sf.get_actual_victory_points(s, self.human),
        }

    def state_json(self) -> str:
        g = self.game
        over = g.winning_color()
        acts = _sorted_actions(g) if over is None else []
        cur = g.state.current_color() if over is None else None
        is_human_turn = over is None and cur == self.human
        return json.dumps({
            "over": over is not None,
            "winner": over.value if over else None,
            "turn": g.state.num_turns,
            "phase": _phase_of(g),
            "current": cur.value if cur else None,
            "is_human_turn": is_human_turn,
            "human": self.human.value,
            "colors": [c.value for c in g.state.colors],
            "board": board_snapshot(g),
            "hand": self._human_hand(),
            "wp": {k: round(v, 4) for k, v in self._wp_now(g).items()},
            "legal_actions": [_action_ui(a, i, g) for i, a in enumerate(acts)] if is_human_turn else [],
            "must_roll": is_human_turn and len(acts) == 1 and acts[0].action_type == AT.ROLL,
            "feed": self.feed[-12:],
            "eval_graph": self.eval_graph,
            "can_take_back": bool(self._snapshots),
            "takebacks": self.takebacks,
            "step": len(self.timeline),
        })

    # ------------------------------------------------------------------ #
    # Final review (same schema as the offline analyzer -> same UI)
    # ------------------------------------------------------------------ #

    def final_review(self) -> str:
        g = self.game
        winner = g.winning_color()
        colors = [c.value for c in g.state.colors]
        w = winner.value if winner else None

        losses: Dict[str, List[float]] = {c: [] for c in colors}
        label_counts: Dict[str, Dict[str, int]] = {c: {} for c in colors}
        phase_counts: Dict[str, dict] = {c: {} for c in colors}
        for t in self.timeline:
            a = t["actor"]
            e = t["classification"]["eff_loss"]
            l = t["classification"]["label"]
            losses[a].append(e)
            label_counts[a][l] = label_counts[a].get(l, 0) + 1
            phase_counts[a].setdefault(t["phase"], {})
            phase_counts[a][t["phase"]][l] = phase_counts[a][t["phase"]].get(l, 0) + 1

        report_cards = {}
        for c in colors:
            ls = losses[c]
            report_cards[c] = {
                "color": c, "decisions": len(ls),
                "accuracy": accuracy_from_losses(ls),
                "avg_wp_loss": round(sum(ls) / len(ls), 4) if ls else 0.0,
                "label_counts": label_counts[c], "phase_breakdown": phase_counts[c],
                "is_winner": c == w,
                "is_human": c == self.human.value,
                "takebacks": self.takebacks if c == self.human.value else 0,
            }

        eval_graph = list(self.eval_graph)
        eval_graph.append({
            "step": len(self.timeline), "turn": g.state.num_turns,
            "wp": {c: (1.0 if c == w else 0.0) for c in colors},
            "ci": {c: 0.0 for c in colors},
        })
        critical = [
            {"step": t["step"], "actor": t["actor"], "turn": t["turn"],
             "label": t["classification"]["label"],
             "wp_loss": t["classification"]["eff_loss"], "annotation": t["annotation"]}
            for t in sorted(self.timeline, key=lambda t: t["classification"]["eff_loss"], reverse=True)
            if t["classification"]["eff_loss"] > 0.05
        ][:8]

        return json.dumps({
            "version": "catan-review/1",
            "generated_with": f"catan_review {__version__} (live value-model)",
            "config": {"num_players": self.config.num_players, "seed": self.config.seed,
                       "vps_to_win": self.config.vps_to_win,
                       "discard_limit": self.config.discard_limit,
                       "human": self.human.value},
            "players": [{"color": c, "index": i} for i, c in enumerate(colors)],
            "winner": w, "num_turns": g.state.num_turns,
            "geometry": self.geometry,
            "timeline": self.timeline, "eval_graph": eval_graph,
            "final_frame": {"board": board_snapshot(g), "winner": w, "turn": g.state.num_turns},
            "report_cards": report_cards, "critical_moments": critical, "icons": ICONS,
            "meta": {"perfect_info": True, "evaluator": "value-model",
                     "sigma_pair": self.model.sigma_pair,
                     "takebacks": self.takebacks, "disclaimer": DISCLAIMER},
        })


# ------------------------------------------------------------------------- #
# Module-level API for the JS side (one active session).
# ------------------------------------------------------------------------- #

_SESSION: Optional[PlaySession] = None


def start_session(model_json: str, seed: int, human_color: str, num_players: int) -> str:
    global _SESSION
    _SESSION = PlaySession(model_json, seed=seed, human_color=human_color,
                           num_players=num_players)
    return _SESSION.advance()


def get_geometry() -> str:
    return json.dumps(_SESSION.geometry)


def get_state() -> str:
    return _SESSION.state_json()


def submit_action(action_id: int) -> str:
    return _SESSION.submit(action_id)


def advance() -> str:
    return _SESSION.advance()


def take_back() -> str:
    return _SESSION.take_back()


def hint() -> str:
    return _SESSION.hint()


def final_review() -> str:
    return _SESSION.final_review()
