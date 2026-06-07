# GEPA Guidance Optimizer

Evolves Hermes agent guidance text (COST_AWARENESS, TASK_COMPLETION, caveman skill) 
using GEPA's evolutionary search to maximize the fraction of known verbosity 
failures they would prevent.

## How it works

1. **Extract failure examples** from real session data in `~/.hermes/state.db`
2. **Score candidates** with an LLM judge: "Would this guidance text have prevented this verbose response?"
3. **GEPA evolves** better guidance text via reflection + mutation
4. **Apply results** back to `agent/prompt_builder.py`

The LLM judge is 20x cheaper than running the full agent (single cheap LLM call 
vs 10-50 tool calls per example).

## Quick start

```bash
# Install deps
pip install gepa litellm

# Set API key for the judge model
export DEEPSEEK_API_KEY=sk-...

# Dry run: extract dataset and score current guidance
python3.13 -m eval.gepa_optimizer.run --dry-run --verbose

# Full optimization (100 iterations)
python3.13 -m eval.gepa_optimizer.run \
    --model deepseek/deepseek-chat \
    --reflection-model anthropic/claude-sonnet-4 \
    --max-calls 100 \
    --verbose
```

## Model configuration

- `--model`: The judge/evaluator model. Uses litellm model strings.
  - `deepseek/deepseek-chat` (DeepSeek V3 — cheap, fast)
  - `openrouter/deepseek/deepseek-chat` (via OpenRouter)
  - `openai/gpt-4.1-mini` (OpenAI)
- `--reflection-model`: The proposer/reflection model. Should be strong at text analysis.
  - `anthropic/claude-sonnet-4` (recommended)
  - `openai/gpt-4o`
  - `openrouter/anthropic/claude-sonnet-4`

## Output

Optimized guidance text saved to `/tmp/gepa_optimized_guidance.json`.
Apply to `agent/prompt_builder.py` manually after review.

## Disabling

Set `gepa.enabled: false` in `~/.hermes/config.yaml` to prevent automatic
GEPA optimization during `hermes update` or skill operations.

```yaml
# ~/.hermes/config.yaml
gepa:
  enabled: false
```
