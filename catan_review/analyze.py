"""Full-game analysis -> review JSON (brief §4, §6).

For every non-forced decision we evaluate the chosen action and a shortlist of
alternatives (top-K by the greedy heuristic), classify the WP_loss, and write a
plain-English annotation. The output is one self-contained document the UI
renders: board geometry, a per-step timeline (board + WP + label + annotation),
a multi-line WP eval graph, per-player report cards, and the critical moments.

Each decision is analyzed as a self-contained unit, so the work fans out across
processes (Catanatron ``Game`` objects pickle cleanly). ``n_before`` / ``n_alt`` /
``topk`` trade speed for tightness; confidence intervals keep every label honest
regardless of the setting (§3.6, §4.4).
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Dict, List, Optional

from catanatron import Game, Color, Action

from . import __version__
from .engine import Trajectory, public_victory_points
from .evaluator import evaluate_state, evaluate_action, WPEstimate, PERFECT_INFO
from .policy import _score
from .classifier import Candidate, classify, accuracy_from_losses, ICONS
from .annotate import annotate
from .gamelog import (
    board_geometry, board_snapshot, action_to_dict, action_to_human, action_from_dict,
)

DISCLAIMER = (
    "Win probabilities are Monte-Carlo estimates (rollouts to game end under a "
    "fixed reference policy), shown with 95% confidence intervals. v1 evaluates "
    "with perfect information (it can see hidden hands/deck) — a flagged "
    "approximation; labels within rollout noise are marked low-confidence."
)


def _phase(game: Game) -> str:
    if game.state.is_initial_build_phase:
        return "setup"
    lead = max(public_victory_points(game, c) for c in game.state.colors)
    return "early" if lead < 4 else ("mid" if lead < 7 else "late")


def _analyze_decision(payload: dict) -> dict:
    """Worker: fully analyze one decision. Runs in a child process."""
    game: Game = payload["game"]
    chosen: Action = payload["chosen"]
    colors: List[str] = payload["colors"]
    actor = Color(payload["actor"])
    n_before, n_alt, topk = payload["n_before"], payload["n_alt"], payload["topk"]
    i = payload["ply_index"]

    phase = _phase(game)
    wp_before = evaluate_state(game, n=n_before, base_seed=i)

    if payload["is_last"]:
        winner = payload["winner"]
        chosen_after = WPEstimate(
            wp={c: (1.0 if c == winner else 0.0) for c in colors},
            ci={c: 0.0 for c in colors}, n=0,
        )
    else:
        chosen_after = evaluate_action(game, chosen, n=n_before, base_seed=i + 7)

    # Rank legal actions by the greedy heuristic (canonical tie-break for repro).
    scored = sorted(game.state.playable_actions,
                    key=lambda a: (-_score(game, a), a.action_type.value, str(a.value)))
    chosen_rank = next((r for r, a in enumerate(scored) if a == chosen), len(scored) - 1)

    chosen_cand = Candidate(
        action=action_to_dict(chosen), actor_wp=chosen_after.of(actor),
        wp=chosen_after.wp, ci=chosen_after.ci_of(actor), heuristic_rank=chosen_rank,
    )

    alt_cands: List[Candidate] = []
    for rank, a in enumerate(scored):
        if len(alt_cands) >= topk:
            break
        if a == chosen:
            continue
        est = evaluate_action(game, a, n=n_alt, base_seed=i * 131 + rank)
        alt_cands.append(Candidate(
            action=action_to_dict(a), actor_wp=est.of(actor),
            wp=est.wp, ci=est.ci_of(actor), heuristic_rank=rank,
        ))

    cls = classify(
        mover=actor, chosen=chosen_cand, alternatives=alt_cands,
        wp_before=wp_before.of(actor), phase=phase,
        chosen_is_greedy_top=(chosen_rank == 0),
    )
    best_text = action_to_human(action_from_dict(cls.best_action)) if cls.best_action else None

    note = annotate(
        label=cls.label, mover=actor.value, action_text=action_to_human(chosen),
        best_action_text=best_text, mover_wp_after=chosen_after.of(actor),
        best_wp=cls.best_wp, eff_loss=cls.eff_loss,
        wp_before=wp_before.wp, wp_after=chosen_after.wp, low_confidence=cls.low_confidence,
    )

    cj = cls.to_json()
    cj["best_action_text"] = best_text
    entry = {
        "step": payload["step"], "ply_index": i, "turn": payload["turn"],
        "actor": actor.value, "phase": phase, "prompt": payload["prompt"],
        "action": {"dict": action_to_dict(chosen), "text": action_to_human(chosen)},
        "wp_before": {k: round(v, 4) for k, v in wp_before.wp.items()},
        "wp_after": {k: round(v, 4) for k, v in chosen_after.wp.items()},
        "ci_before": {k: round(v, 4) for k, v in wp_before.ci.items()},
        "classification": cj, "annotation": note, "board": board_snapshot(game),
    }
    return {
        "step": payload["step"], "entry": entry,
        "graph": {"step": payload["step"], "turn": payload["turn"],
                  "wp": {k: round(v, 4) for k, v in wp_before.wp.items()},
                  "ci": {k: round(v, 4) for k, v in wp_before.ci.items()}},
        "actor": actor.value, "eff_loss": cls.eff_loss, "label": cls.label, "phase": phase,
    }


def analyze_trajectory(
    traj: Trajectory,
    n_before: int = 60,
    n_alt: int = 45,
    topk: int = 4,
    workers: Optional[int] = None,
    max_decisions: Optional[int] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    plies = traj.plies
    colors = [c.value for c in traj.colors]
    winner = traj.winner.value if traj.winner else None
    if workers is None:
        workers = max(1, (os.cpu_count() or 2) - 2)

    decisions = [i for i, p in enumerate(plies) if p.is_decision]
    if max_decisions is not None:
        decisions = decisions[:max_decisions]

    payloads = [{
        "game": plies[i].game_before, "chosen": plies[i].chosen,
        "step": step, "ply_index": i, "turn": plies[i].game_before.state.num_turns,
        "prompt": plies[i].prompt, "actor": plies[i].actor.value, "colors": colors,
        "winner": winner, "is_last": (i + 1) >= len(plies),
        "n_before": n_before, "n_alt": n_alt, "topk": topk,
    } for step, i in enumerate(decisions)]

    results: List[dict] = [None] * len(payloads)
    done = 0
    if workers <= 1:
        for p in payloads:
            results[p["step"]] = _analyze_decision(p)
            done += 1
            if progress and done % 10 == 0:
                progress(done, len(payloads))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_analyze_decision, payloads, chunksize=2):
                results[res["step"]] = res
                done += 1
                if progress and done % 10 == 0:
                    progress(done, len(payloads))

    timeline = [r["entry"] for r in results]
    eval_graph = [r["graph"] for r in results]

    # Aggregates.
    losses: Dict[str, List[float]] = {c: [] for c in colors}
    label_counts: Dict[str, Dict[str, int]] = {c: {} for c in colors}
    phase_counts: Dict[str, Dict[str, Dict[str, int]]] = {c: {} for c in colors}
    for r in results:
        a = r["actor"]
        losses[a].append(r["eff_loss"])
        label_counts[a][r["label"]] = label_counts[a].get(r["label"], 0) + 1
        phase_counts[a].setdefault(r["phase"], {})
        phase_counts[a][r["phase"]][r["label"]] = phase_counts[a][r["phase"]].get(r["label"], 0) + 1

    # Terminal frame.
    final_frame = None
    if plies:
        last = plies[-1]
        g = last.game_before.copy()
        g.execute(last.chosen, validate_action=False)
        eval_graph.append({"step": len(timeline), "turn": g.state.num_turns,
                           "wp": {c: (1.0 if c == winner else 0.0) for c in colors},
                           "ci": {c: 0.0 for c in colors}})
        final_frame = {"board": board_snapshot(g), "winner": winner, "turn": g.state.num_turns}

    report_cards = {}
    for c in colors:
        ls = losses[c]
        report_cards[c] = {
            "color": c, "decisions": len(ls),
            "accuracy": accuracy_from_losses(ls),
            "avg_wp_loss": round(sum(ls) / len(ls), 4) if ls else 0.0,
            "label_counts": label_counts[c], "phase_breakdown": phase_counts[c],
            "is_winner": c == winner,
        }

    critical_moments = [
        {"step": t["step"], "actor": t["actor"], "turn": t["turn"],
         "label": t["classification"]["label"], "wp_loss": t["classification"]["eff_loss"],
         "annotation": t["annotation"]}
        for t in sorted(timeline, key=lambda t: t["classification"]["eff_loss"], reverse=True)
        if t["classification"]["eff_loss"] > 0.05
    ][:8]

    return {
        "version": "catan-review/1",
        "generated_with": f"catan_review {__version__}",
        "config": {"num_players": traj.config.num_players, "seed": traj.config.seed,
                   "vps_to_win": traj.config.vps_to_win, "discard_limit": traj.config.discard_limit},
        "players": [{"color": c, "index": idx} for idx, c in enumerate(colors)],
        "winner": winner, "num_turns": traj.num_turns,
        "geometry": board_geometry(plies[0].game_before),
        "timeline": timeline, "eval_graph": eval_graph, "final_frame": final_frame,
        "report_cards": report_cards, "critical_moments": critical_moments, "icons": ICONS,
        "meta": {"perfect_info": PERFECT_INFO,
                 "rollouts": {"n_before": n_before, "n_alt": n_alt, "topk": topk},
                 "reference_policy": "heuristic greedy (epsilon-exploratory rollouts)",
                 "disclaimer": DISCLAIMER},
    }
