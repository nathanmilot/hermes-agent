"""Run GEPA optimization on agent guidance text.

Evolves guidance blocks (COST_AWARENESS, TASK_COMPLETION, caveman skill)
to maximize the fraction of known verbosity failures they would prevent.

Usage:
    python3.13 -m eval.gepa_optimizer.run \
        --model deepseek/deepseek-chat \
        --reflection-model anthropic/claude-sonnet-4 \
        --max-calls 100 \
        --verbose

Requirements:
    pip install gepa litellm
    Set DEEPSEEK_API_KEY or OPENROUTER_API_KEY in environment.
"""
import argparse
import json
import os
import sys
from typing import Optional

# Add repo root to path so we can import eval.gepa_optimizer
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from eval.gepa_optimizer.dataset import (
    extract_failure_examples,
    build_dataset_with_holdout,
    FAILURE_PATTERNS,
)
from eval.gepa_optimizer.evaluator import (
    score_candidate,
    VerbosityEvaluator,
    make_litellm_judge,
)
from eval.gepa_optimizer.api_resolver import make_hermes_litellm_judge, make_hermes_reflection_lm
from eval.gepa_optimizer.config import is_gepa_enabled, require_gepa_enabled


# ── Current guidance blocks (the seed candidate) ─────────────────────

CURRENT_COST_AWARENESS = (
    "# Cost awareness\n"
    "Output tokens are expensive. Be as concise as possible in every response.\n"
    "Target ≤100 words per response. One sentence is better than three.\n"
    "When delivering results, state the outcome — not the journey. Skip narration.\n"
    "Use tools for detail (read_file, terminal) rather than describing output inline.\n"
    "Never restate what a tool just returned. The user can see tool results.\n"
    "If you find yourself writing more than 3 sentences, stop — you're over-explaining."
)

CURRENT_TASK_COMPLETION = (
    "# Finishing the job\n"
    "When the user asks you to build, run, or verify something, the deliverable is "
    "a working artifact backed by real tool output — not a description of one. "
    "Do not stop after writing a stub, a plan, or a single command. Keep working "
    "until you have actually exercised the code or produced the requested result, "
    "then report what real execution returned."
)

# ── GEPA adapter ─────────────────────────────────────────────────────

def build_adapter(examples, judge_fn, verbose=False):
    """Build a GEPA-compatible adapter for guidance optimization."""
    import gepa
    from gepa.core.adapter import GEPAAdapter, EvaluationBatch
    
    class GuidanceAdapter:
        """GEPA adapter that evaluates guidance text against failure examples."""
        
        def __init__(self, examples, judge_fn, verbose=False):
            self.examples = examples
            self.judge_fn = judge_fn
            self.verbose = verbose
        
        def evaluate(self, batch, candidate, capture_traces=False):
            """Score candidate guidance against a batch of failure examples."""
            guidance = {
                "cost_awareness": candidate.get("cost_awareness", ""),
                "task_completion": candidate.get("task_completion", ""),
            }
            
            scores = []
            outputs = []
            trajectories = [] if capture_traces else None
            
            for example in batch:
                try:
                    s = score_candidate(
                        guidance_blocks=guidance,
                        examples=[example],
                        judge_fn=self.judge_fn,
                        verbose=self.verbose,
                    )
                    scores.append(s)
                    outputs.append({"prevented": s > 0.5})
                    
                    if capture_traces:
                        # Trajectory = raw judge context for the reflection LM
                        trajectories.append({
                            "guidance": guidance,
                            "failure_pattern": example.get("failure_pattern", ""),
                            "response_length": example.get("response_length", 0),
                            "response_preview": example.get("response", "")[:500],
                            "score": s,
                            "prevented": s > 0.5,
                        })
                except Exception as e:
                    scores.append(0.0)
                    outputs.append({"error": str(e)})
                    if capture_traces:
                        trajectories.append({"error": str(e)})
            
            return EvaluationBatch(
                outputs=outputs,
                scores=scores,
                trajectories=trajectories,
            )
        
        def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
            """Build reflection data for the proposer LM."""
            dataset = {}
            for comp in components_to_update:
                records = []
                for i, (output, score) in enumerate(zip(eval_batch.outputs, eval_batch.scores)):
                    if score < 0.5 and i < len(self.examples):
                        ex = self.examples[i]
                        records.append({
                            "Inputs": {"guidance_component": comp},
                            "Generated Outputs": candidate.get(comp, ""),
                            "Feedback": (
                                f"Guidance failed to prevent: {ex.get('failure_pattern')}. "
                                f"The agent response was {ex.get('response_length', 0)} chars. "
                                f"Response preview: {ex['response'][:300]}"
                            ),
                        })
                dataset[comp] = records[:10]  # cap for token budget
            return dataset
    
    return GuidanceAdapter(examples, judge_fn, verbose)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GEPA optimization of Hermes agent guidance text"
    )
    parser.add_argument(
        "--model", default="deepseek/deepseek-chat",
        help="LiteLLM model string for the judge/evaluator (default: deepseek/deepseek-chat)"
    )
    parser.add_argument(
        "--reflection-model", default=None,
        help="LiteLLM model string for the reflection/proposer LM. "
             "Defaults to the active Hermes provider model (deepseek-v4-pro)."
    )
    parser.add_argument(
        "--max-calls", type=int, default=100,
        help="Maximum metric calls (default: 100)"
    )
    parser.add_argument(
        "--max-examples", type=int, default=200,
        help="Maximum failure examples to extract (default: 200)"
    )
    parser.add_argument(
        "--days", type=int, default=14,
        help="Days of session history to analyze (default: 14)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print per-example judge results"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Extract dataset and score seed candidate, but don't run optimization"
    )
    parser.add_argument(
        "--output", default="/tmp/gepa_optimized_guidance.json",
        help="Output path for optimized guidance (default: /tmp/gepa_optimized_guidance.json)"
    )
    parser.add_argument(
        "--api-key", default=None,
        help="API key for the judge model (or set env var DEEPSEEK_API_KEY / OPENROUTER_API_KEY)"
    )
    args = parser.parse_args()

    # ── Step 1: Extract failure examples ─────────────────────────────
    print("=" * 60)
    print("Step 1: Extracting failure examples from sessions...")
    print("=" * 60)
    
    examples = extract_failure_examples(
        max_per_pattern=args.max_examples // len(FAILURE_PATTERNS),
        days=args.days,
    )
    print(f"  Extracted {len(examples)} examples across {len(FAILURE_PATTERNS)} patterns")
    
    if not examples:
        print("  No examples found. Try increasing --days or check state.db.")
        return 1
    
    train, val = build_dataset_with_holdout(examples, holdout_pct=0.2)
    print(f"  Train: {len(train)}, Val: {len(val)}")

    # ── Step 2: Build judge ──────────────────────────────────────────
    print(f"\nStep 2: Building LLM judge...")
    
    # Try Hermes provider first, fall back to explicit args
    if args.api_key or args.model != "deepseek/deepseek-chat":
        # User explicitly configured — use their settings
        judge_fn = make_litellm_judge(model=args.model, api_key=args.api_key)
        print(f"  Using explicit model: {args.model}")
    else:
        # Auto-detect from Hermes config
        judge_fn = make_hermes_litellm_judge(verbose=True)
        if judge_fn is None:
            print("  Could not resolve API credentials. Use --api-key or set env vars.")
            return 1

    # ── Step 3: Score seed candidate ─────────────────────────────────
    print(f"\nStep 3: Scoring current (seed) guidance...")
    
    seed_guidance = {
        "cost_awareness": CURRENT_COST_AWARENESS,
        "task_completion": CURRENT_TASK_COMPLETION,
    }
    
    seed_score = score_candidate(
        guidance_blocks=seed_guidance,
        examples=val[:20],  # use a subset for speed
        judge_fn=judge_fn,
        verbose=args.verbose,
    )
    print(f"  Seed score: {seed_score:.3f} ({int(seed_score * 20)}/20 prevented)")

    if args.dry_run:
        print("\n  Dry run complete. Not running optimization.")
        print(f"  Dataset: {len(train)} train, {len(val)} val examples")
        print(f"  Seed score: {seed_score:.3f}")
        return 0

    # ── Step 4: Run GEPA optimization ────────────────────────────────
    print(f"\nStep 4: Running GEPA optimization...")
    
    # Resolve reflection LM
    if args.reflection_model:
        # User explicitly specified — use as litellm string
        reflection_lm = args.reflection_model
        print(f"  Reflection model: {args.reflection_model} (explicit)")
    else:
        # Auto-detect from Hermes config (deepseek-v4-pro via OpenCode Go)
        reflection_lm = make_hermes_reflection_lm(verbose=True)
        if reflection_lm is None:
            print("  ERROR: Could not resolve reflection LM. Use --reflection-model.")
            return 1
        print(f"  Reflection model: auto-detected from Hermes provider")
    
    print(f"  Max metric calls: {args.max_calls}")
    
    try:
        import gepa
    except ImportError:
        print("  ERROR: gepa not installed. Run: pip install gepa")
        return 1

    adapter = build_adapter(val[:50], judge_fn, verbose=args.verbose)

    result = gepa.optimize(
        seed_candidate={
            "cost_awareness": CURRENT_COST_AWARENESS,
            "task_completion": CURRENT_TASK_COMPLETION,
        },
        trainset=train[:args.max_examples],
        valset=val[:min(50, len(val))],
        adapter=adapter,
        reflection_lm=reflection_lm,
        max_metric_calls=args.max_calls,
        display_progress_bar=False,  # disable in non-TTY/background
    )

    # ── Step 5: Report ───────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("Step 5: Results")
    print(f"{'=' * 60}")
    
    best = result.best_candidate
    
    # Score the optimized guidance on the full val set
    final_score = score_candidate(
        guidance_blocks=best,
        examples=val,
        judge_fn=judge_fn,
        verbose=False,
    )
    
    print(f"\n  Seed score:     {seed_score:.3f}")
    print(f"  Optimized score: {final_score:.3f}")
    print(f"  Improvement:     +{(final_score - seed_score) * 100:.1f} percentage points")
    
    print(f"\n  Optimized COST_AWARENESS_GUIDANCE:")
    print(f"  {'-' * 40}")
    for line in best.get("cost_awareness", "").split("\n"):
        print(f"  {line}")
    
    print(f"\n  Optimized TASK_COMPLETION_GUIDANCE:")
    print(f"  {'-' * 40}")
    for line in best.get("task_completion", "").split("\n"):
        print(f"  {line}")
    
    # Save results
    output = {
        "seed_score": seed_score,
        "optimized_score": final_score,
        "improvement_pct": (final_score - seed_score) * 100,
        "seed_guidance": seed_guidance,
        "optimized_guidance": best,
        "num_examples": len(examples),
        "num_metric_calls": args.max_calls,
        "model": args.model,
        "reflection_model": args.reflection_model or "hermes-provider",
    }
    
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Full results saved to {args.output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
