"""GEPA Optimizer — evolve agent guidance text to reduce verbosity.

Uses GEPA's evolutionary search to optimize the system prompt guidance blocks
(COST_AWARENESS, TASK_COMPLETION, caveman skill) against real session failure
examples extracted from state.db.

The evaluator uses an LLM judge instead of running the full agent — 20x cheaper
than live agent evaluation while providing meaningful signal about whether
new guidance text would prevent known verbosity failures.
"""
