"""Dataset extraction: pull failure examples from Hermes session DB.

Each example captures a real agent response that exhibited a known verbosity
pattern, paired with the guidance text that was active at the time.
"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

DB_PATH = os.path.expanduser("~/.hermes/state.db")

# ── Failure pattern definitions ─────────────────────────────────────

@dataclass
class FailurePattern:
    name: str
    description: str
    # Pattern to match in the response text (case-insensitive substring)
    matcher: str
    # What the response SHOULD have done instead
    fix_description: str


FAILURE_PATTERNS = [
    FailurePattern(
        name="filler_opening",
        description="Response starts with narrative filler instead of the finding",
        matcher="now i have",
        fix_description="Start with the finding/conclusion, not 'Now I have all the data...'",
    ),
    FailurePattern(
        name="filler_opening_v2",
        description="Response starts with 'Let me' narrative",
        matcher="let me compile",
        fix_description="Skip the setup. First sentence = result.",
    ),
    FailurePattern(
        name="filler_opening_v3",
        description="Response starts with 'Here's what I did'",
        matcher="here's what i did",
        fix_description="Say what changed, not what you did to change it.",
    ),
    FailurePattern(
        name="filler_opening_v4",
        description="Response starts with 'I'll start by'",
        matcher="i'll start by",
        fix_description="Don't narrate future actions. Execute and report.",
    ),
    FailurePattern(
        name="triple_redundancy",
        description="Same finding presented in narrative + table + bullets",
        matcher="|---|",  # markdown table = likely has redundancy
        fix_description="Pick ONE format per finding. The table IS the report.",
    ),
    FailurePattern(
        name="tool_output_restatement",
        description="Restates what a tool just returned",
        matcher="the output shows",
        fix_description="The user can see tool results. Reference, don't restate.",
    ),
    FailurePattern(
        name="overlong_code_context",
        description="Shows full file context around a small diff",
        matcher="```",  # code blocks in response
        fix_description="Show only the changed lines. User has the file.",
    ),
    FailurePattern(
        name="multi_paragraph_narrative",
        description="Long narrative before getting to the point",
        matcher="\n\n\n",  # 3+ consecutive newlines = paragraph breaks
        fix_description="Findings first. One paragraph per finding max.",
    ),
]


# ── Extraction ───────────────────────────────────────────────────────

@dataclass
class FailureExample:
    """A single instance of verbosity detected in a real agent response."""
    response_id: str
    session_id: str
    pattern: str  # FailurePattern.name
    response_preview: str  # first 500 chars
    response_length: int
    guidance_active: str  # relevant guidance text that was in effect
    timestamp: float


def extract_failure_examples(
    db_path: str = DB_PATH,
    days: int = 14,
    max_per_pattern: int = 50,
    min_response_length: int = 200,
) -> list[FailureExample]:
    """Extract failure examples from recent sessions.

    For each failure pattern, finds matching assistant responses and pairs
    them with the guidance text that was (ineffectively) active.
    """
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()

    examples: list[FailureExample] = []

    for pattern in FAILURE_PATTERNS:
        # Build query: find responses matching this pattern's matcher
        # The matcher is a substring that appears in the response text
        rows = conn.execute("""
            SELECT m.content, m.session_id, m.rowid, m.timestamp
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE s.started_at >= ?
              AND m.role = 'assistant'
              AND m.content IS NOT NULL
              AND length(m.content) >= ?
              AND lower(m.content) LIKE ?
            ORDER BY length(m.content) DESC
            LIMIT ?
        """, (cutoff, min_response_length, f"%{pattern.matcher}%", max_per_pattern)).fetchall()

        for content, session_id, msg_id, timestamp in rows:
            examples.append(FailureExample(
                response_id=f"msg_{msg_id}",
                session_id=session_id,
                pattern=pattern.name,
                response_preview=content[:500],
                response_length=len(content),
                guidance_active="",  # filled in later if needed
                timestamp=timestamp,
            ))

    conn.close()
    return examples


def build_gepa_dataset(examples: list[FailureExample]) -> list[dict]:
    """Convert examples to GEPA-compatible DataInst format.

    Each example becomes a dict with the response text and expected behavior.
    The evaluator will use an LLM judge to score whether a candidate guidance
    block would prevent this failure.
    """
    dataset = []
    for ex in examples:
        dataset.append({
            "response": ex.response_preview,
            "response_length": ex.response_length,
            "failure_pattern": ex.pattern,
            "pattern_info": next(
                (p for p in FAILURE_PATTERNS if p.name == ex.pattern),
                None,
            ),
            "session_id": ex.session_id,
            "timestamp": ex.timestamp,
        })
    return dataset


def build_dataset_with_holdout(
    examples: list[FailureExample],
    holdout_pct: float = 0.2,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Split examples into train and validation sets."""
    import random
    random.seed(seed)
    shuffled = list(examples)
    random.shuffle(shuffled)
    split_idx = int(len(shuffled) * (1 - holdout_pct))
    train = build_gepa_dataset(shuffled[:split_idx])
    val = build_gepa_dataset(shuffled[split_idx:])
    return train, val


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    examples = extract_failure_examples(max_per_pattern=20)
    print(f"Extracted {len(examples)} failure examples")
    patterns = {}
    for ex in examples:
        patterns[ex.pattern] = patterns.get(ex.pattern, 0) + 1
    for name, count in sorted(patterns.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}")
    
    train, val = build_dataset_with_holdout(examples)
    print(f"\nTrain: {len(train)}, Val: {len(val)}")
