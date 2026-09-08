"""Plain-English annotations (brief §6.1).

Templated explanations seeded by WP and Catan-literate pattern detection (notably
"feeding the leader", §3.5). We frame the mover's result as "now at X% (top move
~Y%)" rather than a before→after arrow: across a ply the same player may keep
acting (placements), so a raw before→after swing conflates the move with the
turn and reads misleadingly. The before→after arrow is reserved for the *leader*,
where it is a genuine signal.
"""
from __future__ import annotations

from typing import Dict, Optional


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def _leader(wp: Dict[str, float], exclude: Optional[str] = None) -> Optional[str]:
    items = [(c, v) for c, v in wp.items() if c != exclude]
    return max(items, key=lambda kv: kv[1])[0] if items else None


def annotate(
    *,
    label: str,
    mover: str,
    action_text: str,
    best_action_text: Optional[str],
    mover_wp_after: float,
    best_wp: float,
    eff_loss: float,
    wp_before: Dict[str, float],
    wp_after: Dict[str, float],
    low_confidence: bool,
) -> str:
    at = f"{mover.title()} now at {_pct(mover_wp_after)}"
    top = f"top move ~{_pct(best_wp)}"
    better = (f" Better: {best_action_text}." if best_action_text else "")

    if label == "Book":
        msg = f"Book opening: {action_text.lower()}; a strong high-production line. {at}."
    elif label == "Brilliant":
        msg = (f"Brilliant. {action_text} looks weak by instinct, but it is the single best move. {at}.")
    elif label == "Great":
        msg = f"Great: the only move that holds it; every alternative was clearly worse. {at}."
    elif label == "Best":
        msg = f"Best move. {at}."
    elif label == "Excellent":
        msg = f"Excellent: essentially the engine's choice. {at}."
    elif label == "Good":
        msg = f"Good. {at} (gave up {_pct(eff_loss)} vs the {top})."
    elif label == "Inaccuracy":
        msg = f"Inaccuracy: {_pct(eff_loss)} below the {top}.{better} {at}."
    elif label == "Mistake":
        msg = f"Mistake: cost about {_pct(eff_loss)} win chance ({top}).{better} {at}."
    elif label == "Miss":
        msg = f"Miss: a near-winning move was right there{(': ' + best_action_text) if best_action_text else ''}. {at}."
    elif label == "Blunder":
        msg = f"Blunder: threw away about {_pct(eff_loss)} win chance ({top}).{better} {at}."
    else:
        msg = f"{label}. {at}."

    # --- "feeding the leader" detection (§3.5): the leader's genuine gain ---
    leader = _leader(wp_before, exclude=mover)
    if leader and label in ("Inaccuracy", "Mistake", "Blunder", "Miss"):
        gain = wp_after.get(leader, 0.0) - wp_before.get(leader, 0.0)
        if gain >= 0.04:
            msg += (f" This fed the leader: {leader.title()} "
                    f"{_pct(wp_before.get(leader, 0.0))} → {_pct(wp_after.get(leader, 0.0))}.")

    if low_confidence:
        msg += " (low confidence: within rollout noise.)"
    return msg
