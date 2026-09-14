"""x-opencode-session rides on every OpenCode request, on every transport."""

from __future__ import annotations

import pytest

from agent import auxiliary_client as aux
from agent.chat_completion_helpers import build_api_kwargs
from run_agent import AIAgent

_MSGS = [{"role": "user", "content": "hi"}]


def _agent(provider, model, base_url, api_mode=None):
    agent = AIAgent(
        api_key="test-key",
        base_url=base_url,
        model=model,
        provider=provider,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        session_id="sess-affinity-1",
    )
    if api_mode:
        agent.api_mode = api_mode
        agent._transport = None
        agent._anthropic_base_url = base_url
    return agent


@pytest.mark.parametrize(
    "provider, model, base_url, api_mode",
    [
        ("opencode-go", "glm-5", "https://opencode.ai/zen/go/v1", None),  # chat_completions
        ("opencode-go", "gpt-5.6-luna", "https://opencode.ai/zen/go/v1", None),  # codex_responses
        ("opencode-go", "minimax-m2.7", "https://opencode.ai/zen/go/v1", "anthropic_messages"),
        ("opencode-free", "laguna-s-2.1-free", "https://opencode.ai/zen/v1", None),
        ("custom", "glm-5", "https://opencode.ai/zen/go/v1", None),  # URL-only detection
    ],
)
def test_main_turn_sends_stable_session_header_on_every_transport(provider, model, base_url, api_mode):
    agent = _agent(provider, model, base_url, api_mode)
    first = build_api_kwargs(agent, _MSGS)["extra_headers"]["x-opencode-session"]
    second = build_api_kwargs(agent, _MSGS)["extra_headers"]["x-opencode-session"]
    assert first == second == "sess-affinity-1"

    other = _agent("openrouter", "anthropic/claude-sonnet-4.6", "https://openrouter.ai/api/v1")
    assert "x-opencode-session" not in (build_api_kwargs(other, _MSGS).get("extra_headers") or {})


def test_auxiliary_calls_share_the_main_turn_session_key():
    token = aux.set_runtime_main(
        "opencode-go", "glm-5", base_url="https://opencode.ai/zen/go/v1", session_id="sess-affinity-1"
    )
    try:
        kwargs = aux._build_call_kwargs("opencode-go", "glm-5", _MSGS, base_url="https://opencode.ai/zen/go/v1")
        assert kwargs["extra_headers"]["x-opencode-session"] == "sess-affinity-1"
        other = aux._build_call_kwargs("openrouter", "x", _MSGS, base_url="https://openrouter.ai/api/v1")
        assert "x-opencode-session" not in (other.get("extra_headers") or {})
    finally:
        aux._RUNTIME_MAIN_CONTEXT.reset(token)


def test_iteration_summary_call_carries_the_session_header():
    """The chat/anthropic summary builders hand-build kwargs; the header must still ride along."""
    from agent import chat_completion_helpers as cch

    agent = _agent("opencode-go", "glm-5", "https://opencode.ai/zen/go/v1")
    seen = {}

    def _callback(request):
        seen.update(request)
        return None

    cch._managed_summary_call(agent, "req-1", {"model": "glm-5", "messages": _MSGS}, _callback, retry_count=0)
    assert seen["extra_headers"]["x-opencode-session"] == "sess-affinity-1"

    other = _agent("openrouter", "anthropic/claude-sonnet-4.6", "https://openrouter.ai/api/v1")
    seen.clear()
    cch._managed_summary_call(other, "req-2", {"model": "x", "messages": _MSGS}, _callback, retry_count=0)
    assert "extra_headers" not in seen


def test_out_of_turn_calls_never_drop_the_header(monkeypatch):
    """The /goal judge runs after the turn facade reset the contextvars; Console Go 400s on a
    missing header, so an unresolvable scope falls back instead of dropping it."""
    from agent import opencode_affinity as oa

    monkeypatch.setattr(oa, "_LAST_SESSION_KEY", "")
    assert oa.opencode_session_headers("opencode-go", "https://opencode.ai/zen/go/v1") == {
        "x-opencode-session": oa.UNSCOPED_SESSION_KEY,
    }
    # Once a turn has resolved the conversation key, out-of-turn calls reuse it.
    assert oa.opencode_session_headers("opencode-go", None, "sess-1") == {"x-opencode-session": "sess-1"}
    assert oa.opencode_session_headers("opencode-go", None) == {"x-opencode-session": "sess-1"}
    assert oa.opencode_session_headers("openrouter", "https://openrouter.ai/api/v1") == {}
