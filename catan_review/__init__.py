"""Catan Review: a chess.com-style move-quality analysis engine for Catan.

Layering (kept decoupled so the evaluator can be upgraded without touching the UI):

    engine      thin wrapper over Catanatron (rules / simulation core)
    policy      reference + rollout policies (the "opponent model")
    evaluator   win-probability via Monte-Carlo rollouts, with confidence intervals
    classifier  per-decision WP-loss -> chess.com taxonomy labels
    annotate    plain-English explanations
    analyze     full-game analysis -> review JSON (the UI's data source)
    gamelog     versioned JSON game format (replay / import / self-play log)
    api         FastAPI service over all of the above
"""

__version__ = "0.1.0"
