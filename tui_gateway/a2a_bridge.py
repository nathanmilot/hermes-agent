"""A2A bridge: makes this TUI session an A2A peer.

Platform adapters normally only ``connect()`` inside the messaging gateway
service (``hermes gateway run``); TUI sessions have no platform manager, so
inbound A2A never reaches them. This module starts the a2a adapter in-process
on a dedicated asyncio thread and routes inbound tasks into the ACTIVE
session's turn pipeline via the same ``prompt.submit`` handler the UI uses —
the reply streams into the user's window like any other turn, and the JSON-RPC
caller gets the final assistant text.

Activation gate: the ambient ``A2A_PORT`` (set by the ``hermes()`` shell
wrapper for every session) or an a2a entry under ``plugins.enabled``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TURN_TIMEOUT_S = float(os.getenv("A2A_TURN_TIMEOUT", "600"))
_STATE_COMPLETED = "TASK_STATE_COMPLETED"
_STATE_FAILED = "TASK_STATE_FAILED"


class _Cfg:
    extra: dict = {}


def _wanted() -> bool:
    """Only bridge when the user opted in: explicit per-session port (the
    hermes() wrapper) or the a2a plugin listed in plugins.enabled."""
    if os.getenv("A2A_PORT"):
        return True
    try:
        from hermes_cli.config import load_config
        raw = load_config() or {}
        enabled = (raw.get("plugins") or {}).get("enabled") or []
        if isinstance(enabled, list) and any("a2a" in str(e) for e in enabled):
            return True
    except Exception:
        pass
    return False


def _config() -> _Cfg:
    cfg = _Cfg()
    try:
        from hermes_cli.config import load_config
        raw = load_config() or {}
        plat = ((raw.get("gateway") or {}).get("platforms") or {}).get("a2a") or {}
        cfg.extra = dict(plat.get("extra") or {})
    except Exception:
        pass
    return cfg


def _pick_session_id() -> Optional[str]:
    """Most recently active session in this TUI gateway (the one the user sees)."""
    try:
        from tui_gateway import server
        best, best_ts = None, -1.0
        for sid, s in server._sessions.items():
            ts = s.get("last_active") or 0
            if ts > best_ts:
                best, best_ts = sid, ts
        return best
    except Exception:
        return None


def _make_handler(adapter: Any):
    async def _handle_task(event: Any, chat_id: str) -> str:
        sid = _pick_session_id()
        if sid is None:
            return "No active session in this TUI window to take the task."
        text = (getattr(event, "text", "") or "")

        from tui_gateway import server

        logger.info("A2A bridge: submitting task to session %s (%d chars)", sid, len(text))
        # dispatch() rebinds method globals (_sess, transports) — calling the
        # raw prompt.submit function from here would NameError on _sess.
        req = {"jsonrpc": "2.0", "id": 0, "method": "prompt.submit",
               "params": {"session_id": sid, "text": text}}
        result = await asyncio.to_thread(server.dispatch, req)
        if isinstance(result, dict) and result.get("error"):
            msg = str(result["error"].get("message", "submit failed"))
            logger.warning("A2A bridge: prompt.submit rejected: %s", msg)
            adapter._resolve_oldest_for_context(chat_id, _STATE_FAILED, msg)
            return msg

        # Wait for the turn to finish; final assistant message is the reply.
        deadline = time.time() + _TURN_TIMEOUT_S
        reply = ""
        while time.time() < deadline:
            session = server._sessions.get(sid)
            if session is None:
                reply = "Session closed before the task finished."
                break
            if not session.get("running"):
                for m in reversed(session.get("history") or []):
                    if m.get("role") == "assistant" and m.get("content"):
                        reply = m["content"]
                        break
                break
            await asyncio.sleep(0.5)
        if not reply:
            reply = "Timed out waiting for the turn to finish."
        logger.info("A2A bridge: task done for session %s (%d chars)", sid, len(reply))
        # Fulfil the pending JSON-RPC future (mirrors adapter.send()).
        adapter._resolve_oldest_for_context(
            chat_id, _STATE_COMPLETED, reply
        )
        return reply

    async def handle_message(event: Any) -> str:
        chat_id = event.source.chat_id
        try:
            return await _handle_task(event, chat_id)
        except Exception as e:  # noqa: BLE001 — never strand a caller
            logger.warning("A2A bridge: task %s handler failed: %s",
                           getattr(event, "message_id", "?"), e, exc_info=True)
            try:
                adapter._resolve_oldest_for_context(chat_id, _STATE_FAILED, f"bridge error: {e}")
            except Exception:
                pass
            return f"bridge error: {e}"

    return handle_message


def start() -> Optional[Any]:
    """Start the a2a adapter on a dedicated loop thread.

    Returns the adapter on success, None when disabled or unavailable. The
    thread keeps the loop alive for inbound dispatch; the process exits when
    the TUI session ends either way.
    """
    if not _wanted():
        return None
    # Plugin discovery is lazy (first agent build); ensure the a2a platform
    # is registered before probing. Idempotent + exception-isolated.
    try:
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
    except Exception:
        pass
    try:
        from gateway.platform_registry import platform_registry

        if not platform_registry.is_registered("a2a"):
            logger.info("A2A bridge: a2a platform not registered, skipping")
            return None
    except Exception:
        return None

    result: dict = {}

    def _bootstrap() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            adapter = platform_registry.create_adapter("a2a", _config())
            if adapter is None:
                result["error"] = "adapter creation failed"
                return
            adapter.handle_message = _make_handler(adapter)
            # Readiness gate checks _message_handler; dispatch uses the
            # instance override above to skip the gateway's session machinery.
            adapter.set_message_handler(adapter.handle_message)
            ok = loop.run_until_complete(adapter.connect())
            if not ok:
                result["error"] = f"connect failed: {adapter._fatal_error_message}"
                return
            result["adapter"] = adapter
        except Exception as e:  # noqa: BLE001
            logger.warning("A2A bridge: bootstrap failed: %s", e, exc_info=True)
            result["error"] = repr(e)
        finally:
            loop.run_forever()

    threading.Thread(target=_bootstrap, name="a2a-bridge", daemon=True).start()

    for _ in range(100):
        if "adapter" in result or "error" in result:
            break
        time.sleep(0.1)
    adapter = result.get("adapter")
    if adapter is not None:
        logger.info("A2A bridge: session is an A2A peer on %s", adapter.port)
    else:
        logger.warning("A2A bridge: %s", result.get("error", "no result"))
    return adapter