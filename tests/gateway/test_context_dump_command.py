"""Tests for the gateway /context-dump command."""

from __future__ import annotations

import json
import stat
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.conversation_loop import (
    _context_dump_json_safe,
    _record_context_dump_snapshot,
)
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, SendResult
from gateway.session import SessionSource
from hermes_cli.config import DEFAULT_CONFIG


SESSION_KEY = "agent:main:discord:dm:c1"


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.DISCORD,
        chat_id="c1",
        chat_type="dm",
        user_id="u1",
    )


def _make_event() -> MessageEvent:
    return MessageEvent(text="/context-dump", source=_make_source(), message_id="m1")


def _make_runner(*, snapshot: dict | None = None):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner._running_agents = {}
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._session_key_for_source = MagicMock(return_value=SESSION_KEY)
    runner._thread_metadata_for_source = MagicMock(return_value=None)
    runner._read_user_config = MagicMock(
        return_value={"gateway": {"context_dump": {"enabled": True}}}
    )

    adapter = SimpleNamespace(
        send_document=AsyncMock(return_value=SendResult(success=True, message_id="doc1"))
    )
    runner.adapters = {Platform.DISCORD: adapter}

    if snapshot is not None:
        agent = SimpleNamespace(_last_context_dump_snapshot=snapshot)
        runner._agent_cache[SESSION_KEY] = (agent, "sig")

    return runner, adapter


def test_context_dump_default_config_disabled():
    assert DEFAULT_CONFIG["gateway"]["context_dump"]["enabled"] is False


def test_context_dump_sanitizer_removes_auth_fields_but_keeps_payload():
    sanitized = _context_dump_json_safe(
        {
            "model": "gpt-test",
            "max_tokens": 123,
            "api_key": "sk-secret",
            "access_token": "secret",
            "extra_headers": {
                "Authorization": "Bearer secret",
                "x-api-key": "secret",
                "OpenAI-Beta": "responses",
            },
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert sanitized["model"] == "gpt-test"
    assert sanitized["max_tokens"] == 123
    assert sanitized["messages"][0]["content"] == "hello"
    assert "api_key" not in sanitized
    assert "access_token" not in sanitized
    assert "Authorization" not in sanitized["extra_headers"]
    assert "x-api-key" not in sanitized["extra_headers"]
    assert sanitized["extra_headers"]["OpenAI-Beta"] == "responses"


def test_record_context_dump_snapshot_stores_metadata_and_sanitized_payload():
    agent = SimpleNamespace(
        session_id="sess-1",
        platform="gateway",
        provider="openai-codex",
        model="gpt-5.1-codex",
        api_mode="codex_responses",
        base_url="https://chatgpt.com/backend-api/codex",
        _context_dump_enabled=True,
    )

    _record_context_dump_snapshot(
        agent,
        api_kwargs={
            "model": "gpt-5.1-codex",
            "input": [{"role": "user", "content": "hi"}],
            "extra_headers": {"authorization": "Bearer secret"},
        },
        api_call_count=2,
        approx_tokens=42,
        total_chars=168,
    )

    snapshot = agent._last_context_dump_snapshot
    assert snapshot["schema_version"] == 1
    assert snapshot["session_id"] == "sess-1"
    assert snapshot["provider"] == "openai-codex"
    assert snapshot["api_mode"] == "codex_responses"
    assert snapshot["api_call_count"] == 2
    assert snapshot["approx_input_tokens"] == 42
    assert snapshot["request_char_count"] == 168
    assert snapshot["payload"]["input"][0]["content"] == "hi"
    assert "authorization" not in snapshot["payload"]["extra_headers"]


def test_record_context_dump_snapshot_is_noop_when_disabled():
    agent = SimpleNamespace(_context_dump_enabled=False)

    _record_context_dump_snapshot(
        agent,
        api_kwargs={"messages": [{"role": "user", "content": "hi"}]},
        api_call_count=1,
        approx_tokens=1,
        total_chars=2,
    )

    assert not hasattr(agent, "_last_context_dump_snapshot")


@pytest.mark.asyncio
async def test_context_dump_command_disabled_by_config():
    runner, _adapter = _make_runner(snapshot={"session_id": "sess-1", "payload": {}})
    runner._read_user_config.return_value = {
        "gateway": {"context_dump": {"enabled": False}}
    }

    result = await runner._handle_context_dump_command(_make_event())

    assert "/context-dump is disabled" in result


@pytest.mark.asyncio
async def test_context_dump_command_requires_existing_snapshot():
    runner, adapter = _make_runner(snapshot=None)

    result = await runner._handle_context_dump_command(_make_event())

    assert "No LLM request context has been captured" in result
    adapter.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_dump_command_writes_json_and_uploads(monkeypatch, tmp_path):
    from gateway import run as gateway_run

    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    snapshot = {
        "schema_version": 1,
        "created_at": "2026-05-25T00:00:00Z",
        "session_id": "sess-1",
        "platform": "discord",
        "provider": "openai-codex",
        "model": "gpt-5.1-codex",
        "api_mode": "codex_responses",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_call_count": 1,
        "approx_input_tokens": 10,
        "request_char_count": 40,
        "payload": {"input": [{"role": "user", "content": "hello"}]},
    }
    runner, adapter = _make_runner(snapshot=snapshot)

    result = await runner._handle_context_dump_command(_make_event())

    assert "Context dump uploaded" in result
    adapter.send_document.assert_awaited_once()
    kwargs = adapter.send_document.await_args.kwargs
    from pathlib import Path
    dump_path = Path(kwargs["file_path"])
    assert kwargs["file_name"].startswith("context-dump-sess-1-")
    assert kwargs["caption"] == "LLM request context dump"

    on_disk = json.loads(dump_path.read_text(encoding="utf-8"))
    assert on_disk == snapshot
    assert stat.S_IMODE(dump_path.stat().st_mode) == 0o600
