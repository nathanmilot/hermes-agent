# Token Optimization Roadmap — feat/skill-token-optimization

## Phase 1: Bug fixes (CRITICAL + HIGH from review)

Order from report, estimated ~2h total:

1. **C1** — `TERMINAL_CWD` in `parse_project_skill_config` (1 line)
2. **C2** — Category assignment for top-level skills (1 line)
3. **C3** — Don't clear cache on stow (3 lines)
4. **H3** — Config.yaml merge: setdefault+extend (1 line)
5. **H1** — Remove trailing-single-item heuristic (delete 3 lines)
6. **H2** — Reword stow message
7. **H4** — Pass skill_name to filter function

## Phase 2: Hardening (MEDIUM)

8. **M1** — Validate index_format values
9. **M4** — Extract filter function to module level
10. **M5** — Add debug logging for filter results
11. **M6** — Avoid redundant context file reads
12. **L4** — Add unit tests for filter logic, config parser, compact format, stow

## Phase 3: Broader optimizations

### 3a. Compact format for other prompt sections

- **SKILLS_GUIDANCE block**: Current 500+ chars → 2-line directive. "Compressed skill index. Load with skill_view(name) when a skill matches your task. Stow when done."
- **Memory injection header**: Remove prose, keep just the section delimiter
- **Persona**: Currently ~400 chars of personality fluff. Could be a single line
- **Tool-use enforcement**: 300+ chars → "Use tools to act; don't describe intentions."

### 3b. Memory compression

- Current memory entries are full text injected into every turn
- Could use same compact-index pattern: name-only list in prompt, load full entry on demand via memory tool
- This alone saves ~1,000 tokens/turn for sessions with large memory stores

### 3c. Binary skill index (cold-start speed)

- Current cold start: walk filesystem, YAML-parse every SKILL.md frontmatter
- Replace snapshot JSON with msgpack binary blob containing pre-parsed metadata
- Expected: 10x faster cold start, 30% smaller on disk
- Trade-off: requires msgpack dep (already in ecosystem)

### 3d. Skill description trimming

- Many skill descriptions are verbose paragraphs (e.g. proxxied-cli is ~140 chars for description alone)
- Compact format already helps, but descriptions could be capped at 80 chars
- Could add `description_trim` or `description_max_chars` config

### 3e. Lazy skill index

- Only expand full descriptions on first `skill_view` load
- Prompt shows just names + categories. Full index loaded only when needed.
- Trade-off: agent can't scan descriptions to decide relevance

## Effort/impact matrix

| Change | Effort | Token savings | Risk |
|---|---|---|---|
| C1-C3 fixes | 15 min | Prevent regression | None |
| H1-H4 fixes | 30 min | Prevent silent errors | None |
| Compact guidance blocks | 20 min | ~500 chars/session | Low |
| Memory compression | 2h | ~1000 tokens/turn | Medium |
| Binary skill index | 4h | 10x cold start | Medium |
| Description trimming | 15 min | ~20% of skills block | Low |
| Lazy skill index | 3h | ~60% of skills block | High |

## Recommended order

1. Fix bugs (Phase 1)
2. Add tests (Phase 2)
3. Compact guidance blocks (quick win, Phase 3a)
4. Description trimming (quick win, Phase 3d)
5. Memory compression (high impact, Phase 3b)
6. Binary skill index (infrastructure, Phase 3c)
7. Lazy skill index (risky, Phase 3e — only if benchmarks show need)
