# GEPA Session Verbosity Analysis

Analysis of 410 Hermes sessions (14 days, 6,602 assistant messages, 2.6M output chars) using GEPA-style reflection to identify token waste patterns.

## Summary

| Metric | 2-Week Value | Monthly Estimate |
|---|---|---|
| Sessions | 410 | ~880 |
| Assistant messages | 6,602 | ~14,150 |
| Output characters | 2,624,875 | ~5.6M |
| Estimated output tokens | 656,218 | ~1.3M |

**Conservative savings: 328K tokens/month (25% reduction)**
**Optimistic savings: 525K tokens/month (40% reduction)**

## Waste Categories (ranked by impact)

### 🔴 HIGH: Code Review Verbosity — 24.8% of output

- 198 messages, 651,800 chars, avg **3,291 chars/msg**
- **All 5 longest responses** (17K–38K chars) start with "Now I have..."
- Pattern: restates entire file contents as markdown code blocks, verbose narrative wrapper around each finding
- **Fix**: Cite findings by file:line. Never restate file contents.

### 🔴 HIGH: Report/Summary Verbosity — 17.0% of output

- 301 messages, 446,828 chars, avg **1,484 chars/msg**
- Pattern: triple-redundancy — same finding in narrative + JSON/markdown table + bullet summary
- **Fix**: Pick ONE format per finding. Never present the same information three ways.

### 🟡 MEDIUM: Boilerplate Transitions — ~100K chars/month

- Common openings repeated 3–50x per phrase: "Now I have...", "Let me compile...", "Here's what I did..."
- 15–30 chars per response with zero information value
- **Fix**: Caveman skill + COST_AWARENESS already address this but are ignored. Strengthen with explicit prohibition.

### 🟡 MEDIUM: Code Output Context Over-display — 22.7% of output

- 1,408 messages, 595,678 chars, avg 423 chars/msg
- Agent shows full file context around diffs instead of just the changed lines
- **Fix**: "Show only the diff hunk — never restate unchanged surrounding code"

### 🟢 LOW: Debug Responses — 15.6% of output

- Already fairly terse (avg 259 chars/msg). Minor savings from trimming tool output restatement.

## Pattern Catalog

### Filler openings (ignoring existing COST_AWARENESS guidance)

| Phrase | Seen in |
|---|---|
| "Now I have [all the information/understanding/data]..." | 5/5 longest responses |
| "Let me compile/proceed with..." | report, code_review |
| "Here's what I did/changed..." | task_done |
| "I'll start by..." | planning |

### Already-ignored guidance

- **COST_AWARENESS**: "state the outcome — not the journey" → ignored in 5/5 longest responses
- **COST_AWARENESS**: "Never restate what a tool just returned" → frequently ignored
- **caveman skill**: "no bullet-point summaries that restate what was just shown" → partially effective

## Recommended Prompt Changes

### 1. Strengthen COST_AWARENESS_GUIDANCE

Add to `agent/prompt_builder.py`:

```
# Specific Anti-Verbosity Rules
- In code reviews: cite findings by file:line. Never restate file contents.
- In reports: pick ONE format (narrative, table, or bullets) per finding — never all three.
- Never start a response with "Now I have", "Let me compile", or "Here's what I did".
- If a response is >500 chars, re-read it and cut every sentence that restates a tool output.
- The user can see tool results. Don't narrate them.
- Deep review responses: findings only. Skip the "here is my comprehensive review" wrapper.
```

### 2. Add verbosity rule to TASK_COMPLETION_GUIDANCE

```
# Verbosity on task completion
When a task is done, say what changed — not what you did to get there.
"Fixed X by changing Y" not "I investigated X, then I checked Y..."
The commit message IS the summary. Don't add a second one.
```

### 3. Strengthen caveman skill

```
# No review-essay responses
When doing code review or security audit, do NOT write a multi-thousand-word essay.
Structure findings as a concise checklist with one-line per finding.
```

## GEPA Full Optimization: Worth It?

- **Yes** — especially for the skill index format and guidance blocks jointly
- Setup: 4–6 hours for evaluation harness (benchmark tasks + automated scoring)
- Run cost: ~$500–1,500 in API calls
- Expected savings: 20–40% reduction in per-session output tokens
- ROI: ~2–3 weeks to break even

## Files

- `scripts/gepa_session_analysis.py` — data extraction + statistical analysis
- `scripts/gepa_verbosity_reflection.py` — GEPA-style reflection report generator
- `/tmp/gepa_session_analysis.json` — raw extracted data
- `/tmp/gepa_verbosity_report.json` — full structured report
