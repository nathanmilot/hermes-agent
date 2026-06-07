"""GEPA evaluator: LLM judge scores guidance text against failure examples.

Instead of running the full Hermes agent (expensive, 10-50 tool calls per example),
we use a cheap LLM judge to simulate: "If the agent had THIS guidance text,
would it still produce the same verbose response?"
"""
import json
import os
import re
from typing import Any, Callable, Optional

# ── Judge prompt template ────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = """You are a strict evaluator comparing two versions of agent guidance text.

You are shown:
1. ORIGINAL guidance — the instructions the agent actually had when it produced the failure
2. CANDIDATE guidance — a proposed replacement
3. FAILURE EXAMPLE — the verbose response the agent produced under the ORIGINAL guidance

CRITICAL CONTEXT: The failure happened WITH the original guidance active.
The original guidance FAILED to prevent this specific verbose response.
The candidate only gets credit if it adds something the original lacked.

Your job: does the CANDIDATE guidance add new, specific prohibitions or
stronger language that would change the agent's behavior, compared to the original?

Consider:
- Does the candidate add NEW rules the original didn't have?
- Is the candidate's language STRONGER (e.g., "NEVER do X" vs "try to avoid X")?
- Would the specific failure pattern (filler opening, redundancy, etc.) be
  explicitly addressed by the candidate's ADDITIONS?

If the candidate is identical or only trivially reworded: would_prevent = false.
If the candidate adds meaningful new constraints targeting this pattern: would_prevent = true.

Respond with ONLY a JSON object:
{
  "would_prevent": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "one sentence citing what the candidate adds that the original lacked"
}"""

JUDGE_USER_TEMPLATE = """## Original Guidance (active when failure occurred)
{original_guidance}

## Candidate Guidance (proposed replacement)
{candidate_guidance}

## Failure Example
Pattern: {failure_pattern}
Response length: {response_length} chars

The agent produced this response under the ORIGINAL guidance:
---
{response}
---

Does the CANDIDATE guidance add specific new constraints that would prevent this?
Answer ONLY with JSON."""


# ── Scoring ──────────────────────────────────────────────────────────

def score_candidate(
    guidance_blocks: dict[str, str],
    examples: list[dict],
    judge_fn,  # Callable[[list[dict]], str]
    original_guidance: dict[str, str] | None = None,
    verbose: bool = False,
) -> float:
    """Score a candidate guidance block against failure examples.

    Returns the fraction of examples the LLM judge says would be prevented.
    Higher = better (the guidance text is more effective).

    Args:
        guidance_blocks: Dict of guidance name -> candidate guidance text
        examples: List of failure examples from dataset.build_gepa_dataset()
        judge_fn: Function that takes a prompt string and returns LLM response
        original_guidance: The seed/original guidance for comparison.
                          If None, candidate is compared against itself (always score 0).
        verbose: Print per-example results
    """
    # Combine guidance blocks into single text for the judge
    candidate_text = "\n\n".join(
        f"# {name}\n{text}" for name, text in guidance_blocks.items()
    )
    
    if original_guidance is None:
        original_guidance = guidance_blocks
    
    original_text = "\n\n".join(
        f"# {name}\n{text}" for name, text in original_guidance.items()
    )

    prevented = 0
    total = 0

    for i, example in enumerate(examples):
        pattern = example.get("failure_pattern", "unknown")
        response = example["response"]
        response_len = example.get("response_length", len(response))

        prompt = JUDGE_USER_TEMPLATE.format(
            original_guidance=original_text,
            candidate_guidance=candidate_text,
            failure_pattern=pattern,
            response_length=response_len,
            response=response[:2000],  # cap for token budget
        )

        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            result = judge_fn(messages)
            parsed = _parse_judge_response(result)
            
            if parsed.get("would_prevent"):
                prevented += 1
            
            if verbose:
                status = "✓" if parsed.get("would_prevent") else "✗"
                print(f"  [{status}] example {i+1}/{len(examples)}: {pattern} "
                      f"(conf={parsed.get('confidence', 0):.2f})")
        except Exception as e:
            if verbose:
                print(f"  [!] example {i+1}: judge error: {e}")
            # Count as not prevented on error
            pass

        total += 1

    score = prevented / max(total, 1)
    return score


def _parse_judge_response(text: str) -> dict:
    """Extract JSON from judge response (may have markdown fences or extra text)."""
    # Try to find JSON in code fences
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    
    # Try raw JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to find a bare JSON object
    json_match = re.search(r'\{[^{}]*"would_prevent"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    
    # Fallback: look for true/false near "would_prevent"
    would_prevent = '"would_prevent": true' in text.lower() or \
                    'would_prevent": true' in text.lower() or \
                    '"would_prevent":true' in text.lower()
    
    return {"would_prevent": would_prevent, "confidence": 0.5, "reasoning": "parsed from fallback"}


# ── GEPA Adapter (for optimize_anything) ─────────────────────────────

class VerbosityEvaluator:
    """Callable evaluator for GEPA's optimize_anything API.

    Wraps score_candidate() to match GEPA's expected signature:
    evaluate(candidate: str) -> float
    """
    def __init__(
        self,
        examples: list[dict],
        judge_fn: Callable,
        guidance_names: list[str],
        verbose: bool = False,
    ):
        self.examples = examples
        self.judge_fn = judge_fn
        self.guidance_names = guidance_names
        self.verbose = verbose

    def __call__(self, candidate_text: str) -> float:
        """Evaluate a single guidance block candidate.

        candidate_text is the full text of one guidance block.
        We wrap it in the expected dict format.
        """
        # candidate_text is a single string — map it to all guidance names
        # (GEPA optimize_anything works with strings, not dicts)
        guidance = {name: candidate_text for name in self.guidance_names}
        
        try:
            import gepa.optimize_anything as oa
            oa.log(f"Evaluating candidate ({len(candidate_text)} chars)")
        except ImportError:
            pass
        
        score = score_candidate(
            guidance_blocks=guidance,
            examples=self.examples,
            judge_fn=self.judge_fn,
            verbose=self.verbose,
        )
        
        try:
            import gepa.optimize_anything as oa
            oa.log(f"Score: {score:.3f} ({int(score * len(self.examples))}/{len(self.examples)} prevented)")
        except ImportError:
            pass
        
        return score


# ── Helpers ──────────────────────────────────────────────────────────

def make_litellm_judge(model: str, api_key: Optional[str] = None) -> Callable:
    """Create a judge function that uses litellm for LLM calls.

    Args:
        model: litellm model string, e.g. 'deepseek/deepseek-chat' or
               'openrouter/deepseek/deepseek-chat'
        api_key: Optional API key. If not provided, uses env vars
                 (DEEPSEEK_API_KEY, OPENROUTER_API_KEY, etc.)
    """
    import litellm

    if api_key:
        if "deepseek" in model.lower():
            os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
        elif "openrouter" in model.lower():
            os.environ.setdefault("OPENROUTER_API_KEY", api_key)

    def judge(messages: list[dict]) -> str:
        response = litellm.completion(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=200,
        )
        return response.choices[0].message.content or ""

    return judge
