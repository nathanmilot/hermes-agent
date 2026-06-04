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

JUDGE_SYSTEM_PROMPT = """You are a strict evaluator testing whether agent guidance text
would prevent verbosity failures. You are shown:

1. A candidate GUIDANCE block (instructions the agent will follow)
2. A FAILURE EXAMPLE (an actual agent response that was too verbose)

Your job: decide if the agent, given this guidance, would STILL produce
this same verbose response, or would produce something more concise.

Consider:
- Does the guidance explicitly prohibit the specific failure pattern?
- Is the prohibition strong enough that a reasonable agent would obey it?
- Would the guidance make the agent change its response structure?

Respond with ONLY a JSON object:
{
  "would_prevent": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explaining your decision"
}"""

JUDGE_USER_TEMPLATE = """## Candidate Guidance
{guidance}

## Failure Example
Pattern: {failure_pattern}
Response length: {response_length} chars

The agent produced this response:
---
{response}
---

Would the candidate guidance above prevent this verbose response?"""


# ── Scoring ──────────────────────────────────────────────────────────

def score_candidate(
    guidance_blocks: dict[str, str],
    examples: list[dict],
    judge_fn,  # Callable[[list[dict]], str]
    verbose: bool = False,
) -> float:
    """Score a candidate guidance block against failure examples.

    Returns the fraction of examples the LLM judge says would be prevented.
    Higher = better (the guidance text is more effective).

    Args:
        guidance_blocks: Dict of guidance name -> guidance text
        examples: List of failure examples from dataset.build_gepa_dataset()
        judge_fn: Function that takes a prompt string and returns LLM response
        verbose: Print per-example results
    """
    # Combine all guidance blocks into a single text for the judge
    combined_guidance = "\n\n".join(
        f"# {name}\n{text}" for name, text in guidance_blocks.items()
    )

    prevented = 0
    total = 0

    for i, example in enumerate(examples):
        pattern = example.get("failure_pattern", "unknown")
        response = example["response"]
        response_len = example.get("response_length", len(response))

        prompt = JUDGE_USER_TEMPLATE.format(
            guidance=combined_guidance,
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
