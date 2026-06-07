# Skill Compression & Token Optimization — Code Review Panel Verdict (Round 2)

**Date:** 2026-05-24
**Branch:** `feat/skill-token-optimization` vs `main`
**Reviewers:** Adversarial (DeepSeek V4 Flash), Neutral (DeepSeek V4 Flash)
**Score:** 5/10 (down from 6/10 in Round 1 — new findings discovered after rebase)

---

## CRITICAL — Must fix before deploy

### C1: `parse_project_skill_config()` ignores `TERMINAL_CWD` — skill directives silently lost in gateway mode

**Files:** `agent/system_prompt.py:180`, `agent/prompt_builder.py:1418`
**Root cause:** `system_prompt.py` calls `parse_project_skill_config()` with no arguments → defaults to `Path.cwd()`. But the rest of the codebase uses `os.getenv("TERMINAL_CWD")` for context file discovery in gateway mode. When running under the messaging gateway, `cwd` is the hermes-agent install directory, not the user's project directory.
**Impact:** User's `.hermes.md`/`AGENTS.md` skill directives in their project directory are silently ignored. The parser reads the hermes-agent repo's own AGENTS.md (1,132+ lines of dev docs) instead. Only `config.yaml` fallback applies.
**Fix:** `parse_project_skill_config(cwd=os.getenv("TERMINAL_CWD") or None)` in `system_prompt.py`.

### C2: Top-level skills get wrong category — breaks `categories_include: [general]`

**File:** `agent/prompt_builder.py:924`
**Code:** `category = "/".join(parts[:-2]) if len(parts) > 2 else parts[0]`
**Root cause:** For a top-level skill at `skills_dir/my-skill/SKILL.md`, `parts = ("my-skill", "SKILL.md")` → `len(parts) == 2` → `category = parts[0]` = `"my-skill"` (same as the skill name) instead of `"general"`.
**Impact:** `categories_include: [general]` returns zero top-level skills. `categories_exclude: [some-skill]` accidentally excludes a skill named `some-skill` even if it's in a different category. This was harmless before but the new filter logic makes it correctness-critical.
**Fix:** `category = "general" if len(parts) == 2 else "/".join(parts[:-2])`

### C3: Cache destroyed on every `stow` — token optimization anti-pattern

**Files:** `tools/skill_manager_tool.py:786-787`, `agent/prompt_builder.py`
**Root cause:** Every successful `skill_manage` action (including `stow`) calls `clear_skills_system_prompt_cache(clear_snapshot=True)`. This deletes the disk snapshot AND clears the in-process LRU cache even though `stow` modified no skill files.
**Impact:** One session with 5 stows = 5 unnecessary full cold filesystem rescans (read every SKILL.md, parse frontmatter, rebuild index). Directly defeats the stated goal of token optimization. The cache exists to AVOID rescans.
**Fix:** Guard cache clear to only mutation actions: `if action in ("create", "edit", "patch", "delete", "write_file", "remove_file"): clear_skills_system_prompt_cache(...)`.

---

## HIGH — Should fix before deploy

### H1: Trailing-single-item heuristic injects comment text as bogus skill names

**File:** `agent/prompt_builder.py:1462-1465`
**Code:** After matching `skills.include: [a, b]`, everything after `]` is captured as a "trailing item" unless it starts with `[` or `-`.
**Impact:** `skills.include: [proxxied-cli, caveman] # project tools` → `extra = ["# project tools"]` added as a filter entry. Commas in trailing text preserved: `skills.include: [a, b], c` → `extra = [", c"]` (leading comma included). Silently corrupts filter lists.
**Fix:** Strip comments (split on `#`), strip leading/trailing commas and whitespace, and require the result to look like a skill name (alphanumeric+dash). Or remove this fragile feature entirely — the YAML list format already handles multi-item.

### H2: Stow message promises compression that doesn't exist

**File:** `tools/skill_manager_tool.py:773-776`
**Message:** "Its full content will be compressed on the next context compression cycle."
**Root cause:** `stow` only calls `bump_use(name)` — a telemetry counter increment. There is no context compressor wired to this counter. The message is a lie to the agent.
**Impact:** The model may call stow expecting to reclaim tokens. It may skip stow later thinking compression already occurred. Telemetry data is useful for curator analytics but the agent-facing contract is false.
**Fix:** Either (a) wire the context compressor to the stow signal, or (b) reword: "Skill 'X' stowed. Its usage has been recorded. Load again with skill_view(name='X') if needed."

### H3: Config.yaml values don't merge with context file — silently replaced

**File:** `agent/prompt_builder.py:1527-1531`
**Code:** `if key not in result: result[key] = [str(v) for v in val]`
**Root cause:** The `if key not in result` guard means config.yaml values are only used when the context file didn't set that key at all. If context sets `include: [python]` and config.yaml has `include: [devops, github]`, the config values are dropped.
**Note:** The previous review (Round 1) marked this fixed as H2, but only the `if not result:` outer gate was removed. The per-key guard still prevents merging. The stated intent is "config as base, context overlays."
**Fix:** `result.setdefault(key, []).extend([str(v) for v in val])` with deduplication.

### H4: Filter checks `frontmatter_name` but not `skill_name` (directory name)

**File:** `agent/prompt_builder.py:1128,1158,1205`
**Root cause:** All three code paths pass only `frontmatter_name` to `_skill_passes_project_filters`. But the `disabled` check uses BOTH names. Users filtering by directory name (`skills.include: [my-skill]`) won't match skills whose frontmatter `name:` differs from the directory.
**Impact:** `skills.exclude: [some-skill]` silently fails if the skill's frontmatter `name:` is `"Some Skill"` — the directory name exclusion doesn't apply because only `frontmatter_name` is checked by the filter.
**Fix:** Pass both names to `_skill_passes_project_filters` and check either matches, or add `skill_name` as a second parameter.

---

## MEDIUM — Fix before next iteration

| # | Issue | File | Fix |
|---|-------|------|-----|
| M1 | `index_format` not validated — any string silently falls through to full format | `prompt_builder.py:1483,1532` | Validate against `{"full", "compact"}`, log warning on mismatch |
| M2 | Inconsistent trailing-item handling: `categories.include/exclude` lack it while `include/exclude` have it | `prompt_builder.py:1468-1480` | Remove the fragile feature from both; YAML lists handle multi-item |
| M3 | `_find_hermes_md` missing lowercase `hermes.md` (no dot) in search tuple | `prompt_builder.py:89` | Add `"hermes.md"` |
| M4 | `_skill_passes_project_filters` is an untestable closure — should be a module-level pure function | `prompt_builder.py:1074` | Extract to module level with explicit params |
| M5 | No debug logging for filter results — users can't diagnose "why isn't skill X showing?" | `prompt_builder.py:1128,1158,1205` | Add `logger.debug("Filter: %d skills included, %d excluded", ...)` |
| M6 | Context file read twice per session (parser + context builder both read it) | `prompt_builder.py` | Accept pre-loaded text as optional param to avoid redundant I/O |

---

## LOW — Nice to have

| # | Issue | File |
|---|-------|------|
| L1 | Bare `except Exception: pass` swallows `KeyboardInterrupt`/`SystemExit` in 3 places | `prompt_builder.py:1518,1535`, `skill_manager_tool.py:788` |
| L2 | Snapshot manifest uses mtime+size not content hash — race on sub-millisecond edits | `prompt_builder.py:889` |
| L3 | Snapshot file never pruned — persists indefinitely at `~/.hermes/.skills_prompt_snapshot.json` | `prompt_builder.py` |
| L4 | Zero tests for new code paths (filter logic, compact format, config parser, stow) | — |
| L5 | YAML list read-ahead loop doesn't update `in_fence` state (pathological) | `prompt_builder.py:1496-1515` |

---

## What's GOOD — Strengths

1. **Backward compatibility is rock solid** — all new params default to None/"full", existing callers see zero change
2. **91.5% skills block reduction** observed in production (11,078 → 946 chars for proxxied project)
3. **OR-positive filter semantics** correctly implemented — two positive filters compose as union
4. **Two-layer cache preserved** with expanded cache key — no performance regression
5. **Code-fence awareness in parser** — correctly skips YAML examples in documentation
6. **Stow action properly validates** — rejects empty names and non-existent skills, returns proper errors
7. **Import hardening** — `get_session_env` wrapped in try/except with lambda fallback
8. **`seen_skill_names.lower()`** fixes real dedup bug between local/external skill dirs

---

## Rollout Readiness Assessment

| Gate | Status | Notes |
|------|--------|-------|
| Migration | ✅ | No schema changes, no data migration |
| Endpoints | ✅ | No new API endpoints |
| Backward compat | ✅ | All new params default to None |
| Caching | ⚠️ | C3: cache destroyed on stow (anti-pattern) |
| Gateway mode | ❌ | C1: TERMINAL_CWD not used, skill directives silently lost |
| Tests | ❌ | Zero tests for new code paths |
| Stow wire-up | ⚠️ | H2: message promises compression not yet implemented |
| Config merge | ⚠️ | H3: config.yaml per-key replace not append |

---

## Fix Priority Order

1. **C1** — `TERMINAL_CWD` in `parse_project_skill_config` (1 line, prevents silent data loss in gateway mode)
2. **C2** — Category assignment for top-level skills (1 line, correctness-critical for filter logic)
3. **C3** — Don't clear cache on stow (3 lines, prevents token-optimization anti-pattern)
4. **H3** — Config.yaml merge: `setdefault` + `extend` instead of replace (1 line)
5. **H1** — Remove trailing-single-item heuristic (delete 3 lines, eliminates injection vector)
6. **H2** — Reword stow message (truthful about what actually happens)
7. **H4** — Pass `skill_name` to filter function alongside `frontmatter_name`
8. **M1** — Validate `index_format` values
9. **M4** — Extract `_skill_passes_project_filters` to module-level function
10. **M5** — Add debug logging for filter results
11. **L4** — Add unit tests for all new code paths
