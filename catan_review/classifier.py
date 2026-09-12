"""Move classification: the chess.com taxonomy mapped to Catan (brief §4).

For each *decision* (forced moves are excluded, §4.1) we compute

    WP_loss = WP(best legal action) - WP(chosen action)      (for the mover)

and bucket it (§4.2). On top of the plain buckets sit the Catan-specific special
labels: Book, Great, Brilliant, Miss (§4.3).

Noise discipline (§4.4) is first-class: every WP figure carries a confidence
interval, so before we call something a "Blunder" we check the WP_loss is
distinguishable from the next bucket down *at our sample size*. If it isn't, we
soften the label and flag it ``low_confidence`` rather than overclaiming.

Thresholds start from chess.com's Expected-Points bands and are meant to be
recalibrated against our own self-play WP_loss distribution (§5); the calibration
status is recorded in DECISIONS.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from catanatron import Color, Action

# WP_loss upper bounds for each plain bucket (mover's perspective).
THRESHOLDS: List[Tuple[str, float]] = [
    ("Best", 0.005),
    ("Excellent", 0.02),
    ("Good", 0.05),
    ("Inaccuracy", 0.10),
    ("Mistake", 0.20),
    ("Blunder", float("inf")),
]

# A move is "Great" when it's (near) best AND every alternative is much worse.
GREAT_GAP = 0.10
# "Brilliant" additionally requires the move to look bad to a greedy heuristic.
BRILLIANT_GAP = 0.12
# "Miss" = a large loss where an obvious, near-winning alternative existed.
MISS_BEST_WP = 0.80

ICONS = {
    "Brilliant": "✦", "Great": "★", "Best": "✓", "Excellent": "▲",
    "Good": "•", "Book": "≡", "Inaccuracy": "?!", "Mistake": "?",
    "Miss": "⦰", "Blunder": "??", "Forced": "·",
}

@dataclass
class Candidate:
    action: dict           # serialized action
    actor_wp: float        # mover's WP after this action
    wp: Dict[str, float]   # full per-player WP after this action
    ci: float              # mover's WP 95% half-width
    heuristic_rank: int    # rank by the greedy policy (0 = greedy's top pick)


@dataclass
class Classification:
    label: str
    icon: str
    wp_loss: float           # raw best-minus-chosen (for display)
    eff_loss: float          # noise-floor-debiased loss (drives label + accuracy)
    wp_before: float
    wp_after: float          # mover's WP after the chosen action
    best_wp: float
    ci_loss: float           # 95% half-width on the loss
    best_action: Optional[dict]
    low_confidence: bool
    note: str = ""           # short rationale for the label choice
    forced: bool = False

    def to_json(self) -> dict:
        return {
            "label": self.label,
            "icon": self.icon,
            "wp_loss": round(self.wp_loss, 4),
            "eff_loss": round(self.eff_loss, 4),
            "wp_before": round(self.wp_before, 4),
            "wp_after": round(self.wp_after, 4),
            "best_wp": round(self.best_wp, 4),
            "ci_loss": round(self.ci_loss, 4),
            "best_action": self.best_action,
            "low_confidence": self.low_confidence,
            "forced": self.forced,
            "note": self.note,
        }


def _bucket(wp_loss: float) -> str:
    for label, hi in THRESHOLDS:
        if wp_loss <= hi:
            return label
    return "Blunder"


def classify(
    *,
    mover: Color,
    chosen: Candidate,
    alternatives: List[Candidate],
    wp_before: float,
    phase: str,
    chosen_is_greedy_top: bool,
) -> Classification:
    """Classify one decision. ``chosen`` and ``alternatives`` are evaluated
    candidates (mover's WP, with CIs). ``alternatives`` excludes the chosen one."""
    pool = [chosen] + alternatives
    best = max(pool, key=lambda c: c.actor_wp)
    best_wp = best.actor_wp
    wp_loss = max(0.0, best_wp - chosen.actor_wp)

    # Uncertainty on the *loss*: combine the two estimates' half-widths (§4.4).
    # ci_* are 95% half-widths (1.96σ); recover the 1σ standard error of the diff.
    ci_loss = (chosen.ci ** 2 + best.ci ** 2) ** 0.5
    se_loss = ci_loss / 1.96

    # Noise-floor debiasing (§4.4, §10): ``best_wp`` is a max over noisy estimates
    # and is biased upward, so the raw loss systematically overstates how bad a
    # move was. Subtract one standard error: we bucket on the loss we can
    # distinguish from noise (a "more likely than not real" loss), and flag the
    # rest as low-confidence rather than overclaiming.
    eff_loss = max(0.0, wp_loss - se_loss)
    label = _bucket(eff_loss)
    note = ""
    # "Best" is reserved for the engine's actual top choice; a move that is
    # merely indistinguishable from the top within noise is "Excellent",
    # otherwise quiet positions would hand out "Best" for everything (§4.4).
    if label == "Best" and best is not chosen:
        label = "Excellent"

    # Flag as low-confidence when most of the apparent loss is rollout noise.
    low_confidence = wp_loss > THRESHOLDS[2][1] and eff_loss < 0.5 * wp_loss

    # --- Special labels layered on top of the plain bucket (§4.3) ---
    second_best = max((c.actor_wp for c in alternatives), default=chosen.actor_wp)
    gap_to_second = chosen.actor_wp - second_best  # >0 when chosen uniquely strong

    is_near_best = eff_loss <= THRESHOLDS[1][1]  # Best/Excellent territory

    if is_near_best:
        if phase == "setup":
            label = "Book"
            note = note or "matches strong opening theory (high-production placement)"
        elif gap_to_second >= GREAT_GAP and len(alternatives) >= 1 and not low_confidence:
            label = "Great"
            note = f"only strong option, {gap_to_second:.2f} WP better than every alternative"
            # Brilliant: Great AND the greedy heuristic ranked it poorly (a
            # counterintuitive / sacrificial move the engine vindicates).
            if (not chosen_is_greedy_top and chosen.heuristic_rank >= 2
                    and gap_to_second >= BRILLIANT_GAP):
                label = "Brilliant"
                note = (f"counterintuitive: greedy play ranks this #{chosen.heuristic_rank + 1}, "
                        f"yet it is best by {gap_to_second:.2f} WP")
        elif eff_loss <= THRESHOLDS[0][1] and best is chosen:
            label = "Best"
        # else stays Excellent

    # --- Miss: failed to take an obvious, near-winning opportunity (§4.3) ---
    # Gated on confidence: never call a Miss we can't distinguish from noise.
    if (not low_confidence and eff_loss > THRESHOLDS[2][1]
            and best_wp >= MISS_BEST_WP and best.heuristic_rank <= 1):
        label = "Miss"
        note = f"a near-winning move ({best_wp:.0%} WP) was available and obvious"

    return Classification(
        label=label,
        icon=ICONS.get(label, "•"),
        wp_loss=wp_loss,
        eff_loss=eff_loss,
        wp_before=wp_before,
        wp_after=chosen.actor_wp,
        best_wp=best_wp,
        ci_loss=ci_loss,
        best_action=None if best is chosen else best.action,
        low_confidence=low_confidence,
        note=note,
    )


# ---- summary stats (§4.5) ---------------------------------------------------

def accuracy_from_losses(losses: List[float], scale: float = 0.05) -> float:
    """Map a player's average WP_loss to an Accuracy %% (analogue of chess.com's
    accuracy-from-ACPL). 0 loss -> 100%%; decays exponentially. ``scale`` is the
    calibration knob (documented, not borrowed blindly)."""
    if not losses:
        return 100.0
    avg = sum(losses) / len(losses)
    import math
    return round(100.0 * math.exp(-avg / scale), 1)
