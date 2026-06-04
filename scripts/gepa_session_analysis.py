"""GEPA-inspired session verbosity analysis.

Extracts assistant messages from recent Hermes sessions and uses LLM reflection
(a la GEPA's reflective mutation) to identify token waste patterns in agent responses.

Produces a report: patterns found, estimated savings, recommended prompt changes.
"""
import sqlite3
import json
import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Any

DB_PATH = os.path.expanduser("~/.hermes/state.db")
DAYS = 14
SAMPLE_PER_CATEGORY = 5  # responses to send to LLM per category
MAX_RESPONSE_LENGTH = 4000  # chars to send to LLM (truncate longer)

# ── Data extraction ──────────────────────────────────────────────────

def extract_sessions(db_path: str, days: int = DAYS):
    """Return recent sessions with assistant messages."""
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    
    # Get sessions
    sessions = conn.execute("""
        SELECT id, started_at, model, message_count, input_tokens, output_tokens,
               tool_call_count, title
        FROM sessions WHERE started_at >= ?
        ORDER BY started_at DESC
    """, (cutoff,)).fetchall()
    
    # Get all assistant messages for these sessions
    session_ids = [s[0] for s in sessions]
    messages = []
    for sid in session_ids:
        msgs = conn.execute("""
            SELECT content, token_count, timestamp
            FROM messages 
            WHERE session_id = ? AND role = 'assistant'
            AND content IS NOT NULL AND length(content) > 20
            ORDER BY timestamp
        """, (sid,)).fetchall()
        messages.extend([(sid, *m) for m in msgs])
    
    conn.close()
    return sessions, messages


def categorize_response(content: str) -> str:
    """Quick heuristic categorization."""
    content_lower = content[:500].lower()
    if any(kw in content_lower for kw in ['```', 'code', 'function', 'patch', 'diff', 'commit']):
        if 'review' in content_lower or 'finding' in content_lower or 'risk' in content_lower:
            return 'code_review'
        return 'code_output'
    if any(kw in content_lower for kw in ['report', 'summary', 'analysis', 'finding']):
        return 'report'
    if any(kw in content_lower for kw in ['error', 'bug', 'fix', 'issue', 'debug']):
        return 'debug'
    if any(kw in content_lower for kw in ['done', 'fixed', 'complete', 'success']):
        return 'task_done'
    if any(kw in content_lower for kw in ['here', 'let me', 'i will', 'i\'ll', 'plan']):
        return 'planning'
    return 'general'


def estimate_tokens(text: str | int) -> int:
    """Rough token estimate (4 chars per token for English text)."""
    if isinstance(text, int):
        text = str(text)
    return max(1, len(text) // 4)


# ── LLM Reflection (GEPA-style) ──────────────────────────────────────

REFLECTION_PROMPT = """You are analyzing Hermes agent responses to identify token waste patterns.
For each response below, identify:

1. FLUFF: Filler phrases that add no information
   Examples: "Now I have a full picture", "Let me compile the findings", 
   "Here's what I did:", "I've completed the analysis"

2. REPETITION: Information restated from tool output or previous turns
   Examples: restating file contents the user can see, repeating earlier findings

3. OVER-STRUCTURE: Excessive formatting that burns tokens
   Examples: triple-nested bullet lists, redundant section headers, 
   markdown tables restating the same data differently

4. BOILERPLATE: Fixed phrases repeated across sessions
   Examples: "Now let me proceed with...", "Let me check...", 
   "I'll start by..."

For each pattern, estimate the % of the response that could be cut while preserving 
all useful information. Give a concrete example from the response.

Respond as JSON:
{
  "analysis": [
    {
      "response_id": <n>,
      "category": "<category>",
      "total_chars": <n>,
      "patterns": [
        {
          "type": "fluff|repetition|over_structure|boilerplate",
          "example": "<exact quote from response>",
          "estimated_savings_chars": <n>,
          "fix_suggestion": "<how to avoid this in prompts>"
        }
      ],
      "total_savings_pct": <n>,
      "concise_version": "<rewrite removing the waste>"
    }
  ],
  "cross_cutting_findings": [
    {
      "pattern_name": "<name>",
      "frequency": "<how often seen>",
      "estimated_global_savings_pct": <n>,
      "prompt_fix": "<specific text to add/modify in system prompt>"
    }
  ],
  "top_actionable_recommendation": "<#1 single change that would save the most tokens>"
}"""


def build_reflection_messages(samples: list[dict]) -> list[dict]:
    """Build the messages array for the LLM reflection call."""
    user_content = "Analyze these Hermes agent responses for token waste:\n\n"
    for i, s in enumerate(samples):
        truncated = s["content"][:MAX_RESPONSE_LENGTH]
        if len(s["content"]) > MAX_RESPONSE_LENGTH:
            truncated += f"\n... [{len(s['content']) - MAX_RESPONSE_LENGTH} more chars]"
        user_content += f"--- Response {i+1} (category: {s['category']}, {s['chars']} chars) ---\n"
        user_content += truncated + "\n\n"
    
    return [
        {"role": "system", "content": REFLECTION_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ── Sampling ─────────────────────────────────────────────────────────

def sample_for_analysis(messages: list, sessions: list, n_per_category: int = SAMPLE_PER_CATEGORY):
    """Pick diverse samples across categories and session types."""
    categorized = defaultdict(list)
    for sid, content, tokens, ts in messages:
        cat = categorize_response(content)
        chars = len(content)
        categorized[cat].append({
            "session_id": sid,
            "content": content,
            "chars": chars,
            "est_tokens": tokens or estimate_tokens(content),
            "category": cat,
            "timestamp": ts,
        })
    
    samples = []
    for cat, items in categorized.items():
        # Pick: longest, shortest, median, and 2 random
        items.sort(key=lambda x: x["chars"])
        picks = []
        picks.append(items[-1])  # longest
        picks.append(items[0])   # shortest
        if len(items) > 2:
            picks.append(items[len(items)//2])  # median
        # Add random picks to fill
        import random
        random.seed(42)
        remaining = [i for i in items if i not in picks]
        if remaining:
            picks.extend(random.sample(remaining, min(n_per_category - len(picks), len(remaining))))
        samples.extend(picks[:n_per_category])
    
    return samples


# ── Statistical analysis (no LLM needed) ──────────────────────────────

def compute_stats(messages: list, sessions: list):
    """Compute token/verbosity statistics."""
    total_assistant_chars = sum(len(m[1]) for m in messages)
    total_assistant_msgs = len(messages)
    total_sessions = len(sessions)
    total_output_tokens = sum(s[5] or 0 for s in sessions)
    
    # Response length distribution
    lengths = sorted([len(m[1]) for m in messages])
    
    # Category breakdown
    cat_counts = defaultdict(lambda: {"count": 0, "chars": 0, "tokens": 0})
    for sid, content, tokens, ts in messages:
        cat = categorize_response(content)
        cat_counts[cat]["count"] += 1
        cat_counts[cat]["chars"] += len(content)
        cat_counts[cat]["tokens"] += tokens or estimate_tokens(content)
    
    # Boilerplate detection: find common opening/closing phrases
    openings = defaultdict(int)
    for _, content, _, _ in messages:
        first_line = content.strip().split("\n")[0][:100]
        openings[first_line] += 1
    
    common_openings = [(phrase, count) for phrase, count in openings.items() 
                       if count >= 3 and len(phrase) > 10]
    common_openings.sort(key=lambda x: -x[1])
    
    return {
        "total_assistant_msgs": total_assistant_msgs,
        "total_assistant_chars": total_assistant_chars,
        "total_sessions": total_sessions,
        "avg_chars_per_response": total_assistant_chars // max(total_assistant_msgs, 1),
        "median_chars_per_response": lengths[len(lengths)//2] if lengths else 0,
        "p95_chars": lengths[int(len(lengths)*0.95)] if lengths else 0,
        "max_chars": lengths[-1] if lengths else 0,
        "category_breakdown": dict(cat_counts),
        "common_openings": common_openings[:20],
        "estimated_output_tokens": estimate_tokens(total_assistant_chars),
        "estimated_monthly_tokens": estimate_tokens(total_assistant_chars) * 2,  # 2-week → monthly
    }


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("GEPA Session Verbosity Analysis")
    print("=" * 60)
    print()
    
    # 1. Extract data
    print("[1/4] Extracting sessions...")
    sessions, messages = extract_sessions(DB_PATH, DAYS)
    print(f"  {len(sessions)} sessions, {len(messages)} assistant messages")
    
    # 2. Statistical analysis
    print("\n[2/4] Computing statistics...")
    stats = compute_stats(messages, sessions)
    
    print(f"\n  ├─ Total assistant chars:    {stats['total_assistant_chars']:>10,}")
    print(f"  ├─ Total assistant messages: {stats['total_assistant_msgs']:>10,}")
    print(f"  ├─ Avg chars/response:       {stats['avg_chars_per_response']:>10,}")
    print(f"  ├─ Median chars/response:    {stats['median_chars_per_response']:>10,}")
    print(f"  ├─ P95 chars:                {stats['p95_chars']:>10,}")
    print(f"  ├─ Max chars:                {stats['max_chars']:>10,}")
    print(f"  ├─ Est. tokens (2 weeks):    {stats['estimated_output_tokens']:>10,}")
    print(f"  └─ Est. tokens (monthly):    {stats['estimated_monthly_tokens']:>10,}")
    
    print(f"\n  Category breakdown:")
    for cat, data in sorted(stats["category_breakdown"].items(), key=lambda x: -x[1]["chars"]):
        pct = data["chars"] / max(stats["total_assistant_chars"], 1) * 100
        avg = data["chars"] // max(data["count"], 1)
        print(f"    {cat:<15} {data['count']:>5} msgs  {data['chars']:>10,} chars ({pct:>5.1f}%)  avg {avg:,} chars/msg")
    
    print(f"\n  Common opening phrases (repeated ≥3 times):")
    for phrase, count in stats["common_openings"][:10]:
        print(f"    [{count}x] {phrase[:80]}...")
    
    # 3. Sample for LLM analysis
    print("\n[3/4] Sampling responses for LLM reflection...")
    samples = sample_for_analysis(messages, sessions)
    print(f"  {len(samples)} samples across {len(set(s['category'] for s in samples))} categories")
    
    # 4. Save for LLM analysis
    output = {
        "stats": stats,
        "samples": [
            {
                "category": s["category"],
                "chars": s["chars"],
                "est_tokens": s["est_tokens"],
                "content_preview": s["content"][:500],
                "session_id": s["session_id"],
            }
            for s in samples
        ],
        "reflection_messages": build_reflection_messages(samples),
    }
    
    out_path = "/tmp/gepa_session_analysis.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\n[4/4] Results saved to {out_path}")
    print(f"  reflection_messages ready for LLM call ({len(output['reflection_messages'][1]['content']):,} chars)")
    
    # Print the reflection prompt for the user to see what we're sending
    print(f"\n{'='*60}")
    print("Ready for LLM reflection. The analysis extracts:")

if __name__ == "__main__":
    main()
