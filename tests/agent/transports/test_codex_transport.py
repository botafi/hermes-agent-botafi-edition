"""Tests for the ResponsesApiTransport (Codex)."""

import json
import pytest
from types import SimpleNamespace

from agent.transports import get_transport
from agent.transports.types import NormalizedResponse, ToolCall


@pytest.fixture
def transport():
    import agent.transports.codex  # noqa: F401
    return get_transport("codex_responses")


class TestCodexTransportBasic:

    def test_api_mode(self, transport):
        assert transport.api_mode == "codex_responses"

    def test_registered_on_import(self, transport):
        assert transport is not None

    def test_convert_tools(self, transport):
        tools = [{
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "Run a command",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
            }
        }]
        result = transport.convert_tools(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "terminal"

    def test_hosted_tool_search_groups_mcp_toolset_as_namespace(self, transport):
        from tools.registry import registry

        schemas = [
            {
                "name": "mcp_unit_lookup",
                "description": "Lookup a unit test value.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "mcp_unit_update",
                "description": "Update a unit test value.",
                "parameters": {"type": "object", "properties": {}},
            },
        ]
        for schema in schemas:
            registry.register(
                name=schema["name"],
                toolset="mcp-unit",
                schema=schema,
                handler=lambda *_a, **_k: "{}",
            )
        try:
            tools = [
                {"type": "function", "function": schema}
                for schema in schemas
            ] + [
                {
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "description": "Run a command",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
            result = transport.build_kwargs(
                model="gpt-5.4",
                messages=[{"role": "user", "content": "Hi"}],
                tools=tools,
                is_codex_backend=True,
                enable_hosted_tool_search=True,
            )["tools"]

            assert result[0] == {"type": "tool_search"}
            assert any(t["type"] == "function" and t["name"] == "terminal" for t in result)
            namespace = next(t for t in result if t["type"] == "namespace")
            assert namespace["name"] == "mcp_unit"
            assert "MCP server" in namespace["description"]
            assert {t["name"] for t in namespace["tools"]} == {
                "mcp_unit_lookup",
                "mcp_unit_update",
            }
            assert all(t["defer_loading"] is True for t in namespace["tools"])
        finally:
            registry.deregister("mcp_unit_lookup")
            registry.deregister("mcp_unit_update")

    def test_hosted_tool_search_uses_mcp_server_description(self, monkeypatch):
        import hermes_cli.config
        from tools.registry import registry

        monkeypatch.setattr(
            hermes_cli.config,
            "load_config",
            lambda: {
                "mcp_servers": {
                    "unit-server": {
                        "description": "Unit MCP lookup and update tools.",
                    },
                },
                "tools": {"hosted_search": {}},
            },
        )
        registry.register(
            name="mcp_unit_server_lookup",
            toolset="mcp-unit-server",
            schema={
                "name": "mcp_unit_server_lookup",
                "description": "Lookup.",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda *_a, **_k: "{}",
        )
        try:
            metadata = registry.get_hosted_search_metadata("mcp_unit_server_lookup")
            assert metadata["namespace"] == "mcp_unit_server"
            assert metadata["namespace_description"] == "Unit MCP lookup and update tools."
        finally:
            registry.deregister("mcp_unit_server_lookup")

    def test_hosted_tool_search_prefixes_builtin_namespaces(self, transport):
        from tools.registry import registry

        registry.register(
            name="unit_web_search",
            toolset="web",
            schema={
                "name": "unit_web_search",
                "description": "Search the web.",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda *_a, **_k: "{}",
        )
        try:
            result = transport.build_kwargs(
                model="gpt-5.5",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "unit_web_search",
                            "description": "Search the web.",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                is_codex_backend=True,
                enable_hosted_tool_search=True,
            )["tools"]
            namespace = next(t for t in result if t["type"] == "namespace")
            assert namespace["name"] == "hermes_web"
            assert namespace["description"] == "Search the web and extract webpage content."
        finally:
            registry.deregister("unit_web_search")

    def test_hosted_tool_search_loads_config_once_per_request(self, transport, monkeypatch):
        import hermes_cli.config
        from tools.registry import registry

        calls = {"count": 0}

        def fake_load_config():
            calls["count"] += 1
            return {"tools": {"hosted_search": {}}}

        monkeypatch.setattr(hermes_cli.config, "load_config", fake_load_config)

        schemas = [
            {
                "name": "mcp_config_once_lookup",
                "description": "Lookup.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "mcp_config_once_update",
                "description": "Update.",
                "parameters": {"type": "object", "properties": {}},
            },
        ]
        for schema in schemas:
            registry.register(
                name=schema["name"],
                toolset="mcp-config-once",
                schema=schema,
                handler=lambda *_a, **_k: "{}",
            )
        try:
            transport.build_kwargs(
                model="gpt-5.4",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[{"type": "function", "function": schema} for schema in schemas],
                is_codex_backend=True,
                enable_hosted_tool_search=True,
            )
            assert calls["count"] == 1
        finally:
            registry.deregister("mcp_config_once_lookup")
            registry.deregister("mcp_config_once_update")

    def test_chat_message_conversion_replays_tool_search_before_function_call(self):
        from agent.codex_responses_adapter import _chat_messages_to_responses_input

        messages = [
            {
                "role": "assistant",
                "content": "",
                "codex_tool_search_items": [
                    {
                        "type": "tool_search_call",
                        "execution": "server",
                        "call_id": None,
                        "status": "completed",
                        "arguments": {"paths": ["unit"]},
                    },
                    {
                        "type": "tool_search_output",
                        "execution": "server",
                        "call_id": None,
                        "status": "completed",
                        "tools": [],
                    },
                ],
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "call_id": "call_abc123",
                        "type": "function",
                        "namespace": "unit",
                        "function": {"name": "mcp_unit_lookup", "arguments": "{}"},
                    }
                ],
            }
        ]
        items = _chat_messages_to_responses_input(messages)
        assert [item["type"] for item in items] == [
            "tool_search_call",
            "tool_search_output",
            "function_call",
        ]
        assert items[-1]["namespace"] == "unit"

    def test_hosted_tool_search_provider_gate_defaults_to_off_for_lookalikes(self):
        from agent.hosted_tool_search import provider_supports_hosted_tool_search

        assert provider_supports_hosted_tool_search(
            provider="openai-api",
            model="gpt-5.4",
            base_url="https://api.openai.com/v1",
        ) is True
        assert provider_supports_hosted_tool_search(
            provider="openai-codex",
            model="gpt-5.4-mini",
            base_url="https://chatgpt.com/backend-api/codex",
        ) is True
        assert provider_supports_hosted_tool_search(
            provider="openai-api",
            model="gpt-5.4-nano",
            base_url="https://api.openai.com/v1",
        ) is False
        assert provider_supports_hosted_tool_search(
            provider="openai-api",
            model="gpt-5.4",
            base_url="https://api.gmi-serving.com/v1",
        ) is False
        assert provider_supports_hosted_tool_search(
            provider="gmi",
            model="openai/gpt-5.4",
            base_url="https://api.gmi-serving.com/v1",
        ) is False


class TestCodexBuildKwargs:

    def test_basic_kwargs(self, transport):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=messages,
            tools=[],
        )
        assert kw["model"] == "gpt-5.4"
        assert kw["instructions"] == "You are helpful."
        assert "input" in kw
        assert kw["store"] is False

    def test_preflight_accepts_tool_search_namespace_and_replay_items(self, transport):
        kw = {
            "model": "gpt-5.4",
            "instructions": "You are helpful.",
            "input": [
                {"role": "user", "content": "Hello"},
                {
                    "type": "tool_search_call",
                    "execution": "server",
                    "call_id": None,
                    "status": "completed",
                    "arguments": {"paths": ["unit"]},
                },
                {
                    "type": "tool_search_output",
                    "execution": "server",
                    "call_id": None,
                    "status": "completed",
                    "tools": [
                        {
                            "type": "namespace",
                            "name": "unit",
                            "description": "Unit MCP tools.",
                            "tools": [
                                {
                                    "type": "function",
                                    "name": "mcp_unit_lookup",
                                    "description": "Lookup.",
                                    "defer_loading": True,
                                    "parameters": {"type": "object", "properties": {}},
                                }
                            ],
                        }
                    ],
                },
            ],
            "tools": [
                {"type": "tool_search"},
                {
                    "type": "namespace",
                    "name": "unit",
                    "description": "Unit MCP tools.",
                    "tools": [
                        {
                            "type": "function",
                            "name": "mcp_unit_lookup",
                            "description": "Lookup.",
                            "defer_loading": True,
                            "parameters": {"type": "object", "properties": {}},
                        }
                    ],
                },
            ],
            "store": False,
        }
        normalized = transport.preflight_kwargs(kw)
        assert normalized["tools"][0] == {"type": "tool_search"}
        assert normalized["tools"][1]["type"] == "namespace"
        assert normalized["input"][1]["type"] == "tool_search_call"
        assert normalized["input"][2]["tools"][0]["type"] == "namespace"

    def test_system_extracted_from_messages(self, transport):
        messages = [
            {"role": "system", "content": "Custom system prompt"},
            {"role": "user", "content": "Hi"},
        ]
        kw = transport.build_kwargs(model="gpt-5.4", messages=messages, tools=[])
        assert kw["instructions"] == "Custom system prompt"

    def test_no_system_uses_default(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(model="gpt-5.4", messages=messages, tools=[])
        assert kw["instructions"]  # should be non-empty default

    def test_reasoning_config(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4", messages=messages, tools=[],
            reasoning_config={"effort": "high"},
        )
        assert kw.get("reasoning", {}).get("effort") == "high"

    def test_reasoning_disabled(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4", messages=messages, tools=[],
            reasoning_config={"enabled": False},
        )
        assert "reasoning" not in kw or kw.get("include") == []

    def test_session_id_sets_cache_key(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4", messages=messages, tools=[],
            session_id="test-session-123",
        )
        assert kw.get("prompt_cache_key") == "test-session-123"

    def test_github_responses_no_cache_key(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4", messages=messages, tools=[],
            session_id="test-session",
            is_github_responses=True,
        )
        assert "prompt_cache_key" not in kw

    def test_xai_responses_sends_cache_key_via_extra_body(self, transport):
        """xAI's Responses API documents ``prompt_cache_key`` as the
        body-level cache-routing key (the ``x-grok-conv-id`` header is
        Chat-Completions-only). Passing it via ``extra_body`` is robust
        against openai SDK builds whose ``Responses.stream()`` kwarg
        signature ever drops the field — the body field still serializes
        and reaches xAI either way. The ``x-grok-conv-id`` header is kept
        as a belt-and-braces fallback so cache routing survives even
        when the body field would be stripped by an intermediate proxy.
        Ref: https://docs.x.ai/developers/advanced-api-usage/prompt-caching/maximizing-cache-hits
        """
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-4.3", messages=messages, tools=[],
            session_id="conv-xai-1",
            is_xai_responses=True,
        )
        assert "prompt_cache_key" not in kw
        assert kw.get("extra_body", {}).get("prompt_cache_key") == "conv-xai-1"
        assert kw.get("extra_headers", {}).get("x-grok-conv-id") == "conv-xai-1"

    def test_xai_responses_extra_body_preserves_caller_fields(self, transport):
        """When the caller already supplies ``extra_body`` (e.g. via
        request_overrides), the xAI cache-key injection must merge into
        the existing dict instead of overwriting it. Caller-supplied
        ``prompt_cache_key`` wins (setdefault semantics) so user overrides
        aren't silently clobbered by the transport."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-4.3", messages=messages, tools=[],
            session_id="conv-xai-1",
            is_xai_responses=True,
            request_overrides={"extra_body": {"prompt_cache_key": "caller-override", "other_field": 42}},
        )
        eb = kw.get("extra_body", {})
        assert eb.get("prompt_cache_key") == "caller-override"
        assert eb.get("other_field") == 42

    def test_max_tokens(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4", messages=messages, tools=[],
            max_tokens=4096,
        )
        assert kw.get("max_output_tokens") == 4096

    def test_codex_backend_no_max_output_tokens(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4", messages=messages, tools=[],
            max_tokens=4096,
            is_codex_backend=True,
        )
        assert "max_output_tokens" not in kw

    def test_xai_headers(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-3", messages=messages, tools=[],
            session_id="conv-123",
            is_xai_responses=True,
        )
        assert kw.get("extra_headers", {}).get("x-grok-conv-id") == "conv-123"

    def test_xai_headers_preserve_request_override_headers(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-3", messages=messages, tools=[],
            session_id="conv-123",
            is_xai_responses=True,
            request_overrides={"extra_headers": {"X-Test": "1", "X-Trace": "abc"}},
        )
        assert kw.get("extra_headers") == {
            "X-Test": "1",
            "X-Trace": "abc",
            "x-grok-conv-id": "conv-123",
        }

    def test_minimal_effort_clamped(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="gpt-5.4", messages=messages, tools=[],
            reasoning_config={"effort": "minimal"},
        )
        # "minimal" should be clamped to "low"
        assert kw.get("reasoning", {}).get("effort") == "low"

    def test_xai_reasoning_effort_passed(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-4.3", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"effort": "high"},
        )
        # xAI Responses receives reasoning.effort on the allowlisted models.
        assert kw.get("reasoning") == {"effort": "high"}
        # As of May 2026 (post-revert of PR #26644) we DO request
        # reasoning.encrypted_content back from xAI so we can replay it
        # across turns for cross-turn coherence — xAI explicitly relies
        # on this for their partnership integration.  See
        # tests/run_agent/test_codex_xai_oauth_recovery.py for the
        # full history.
        assert "reasoning.encrypted_content" in kw.get("include", [])

    def test_xai_reasoning_disabled_no_reasoning_key(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-4.3", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"enabled": False},
        )
        # When reasoning is disabled, do not send the reasoning key at all
        assert "reasoning" not in kw

    def test_xai_minimal_effort_clamped(self, transport):
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-4.3", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"effort": "minimal"},
        )
        # "minimal" should be clamped to "low" for xAI as well
        assert kw.get("reasoning", {}).get("effort") == "low"

    # --- Grok reasoning-effort capability allowlist ---
    # api.x.ai 400s with "Model X does not support parameter reasoningEffort"
    # on grok-4 / grok-4-fast / grok-3 / grok-code-fast / grok-4.20-0309-*.
    # Those models reason natively but don't expose the dial. The transport
    # must omit the `reasoning` key for them.  As of May 2026 we DO request
    # ``reasoning.encrypted_content`` back from xAI on every model —
    # see test_xai_reasoning_effort_passed for the rationale.

    def test_xai_grok_4_omits_reasoning_effort(self, transport):
        """grok-4 / grok-4-0709 reject reasoning.effort with HTTP 400."""
        messages = [{"role": "user", "content": "Hi"}]
        for model in ("grok-4", "grok-4-0709"):
            kw = transport.build_kwargs(
                model=model, messages=messages, tools=[],
                is_xai_responses=True,
                reasoning_config={"effort": "high"},
            )
            assert "reasoning" not in kw, (
                f"{model} must not receive a reasoning key (xAI rejects it)"
            )
            # Even without the effort dial we still ask xAI to echo back
            # encrypted reasoning content so it can be replayed next turn.
            assert "reasoning.encrypted_content" in kw.get("include", [])

    def test_xai_grok_4_fast_omits_reasoning_effort(self, transport):
        """grok-4-fast and grok-4-1-fast variants reject reasoning.effort."""
        messages = [{"role": "user", "content": "Hi"}]
        for model in (
            "grok-4-fast-reasoning",
            "grok-4-fast-non-reasoning",
            "grok-4-1-fast-reasoning",
            "grok-4-1-fast-non-reasoning",
        ):
            kw = transport.build_kwargs(
                model=model, messages=messages, tools=[],
                is_xai_responses=True,
                reasoning_config={"effort": "low"},
            )
            assert "reasoning" not in kw, (
                f"{model} must not receive a reasoning key (xAI rejects it)"
            )

    def test_xai_grok_3_non_mini_omits_reasoning_effort(self, transport):
        """Plain grok-3 rejects reasoning.effort — only grok-3-mini accepts it."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-3", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"effort": "medium"},
        )
        assert "reasoning" not in kw

    def test_xai_grok_3_mini_keeps_reasoning_effort(self, transport):
        """grok-3-mini and -fast variants do accept the effort dial."""
        messages = [{"role": "user", "content": "Hi"}]
        for model in ("grok-3-mini", "grok-3-mini-fast"):
            kw = transport.build_kwargs(
                model=model, messages=messages, tools=[],
                is_xai_responses=True,
                reasoning_config={"effort": "high"},
            )
            assert kw.get("reasoning") == {"effort": "high"}

    def test_xai_grok_4_20_0309_variants_omit_reasoning_effort(self, transport):
        """grok-4.20-0309-(non-)reasoning reject the effort dial.

        Counterintuitively, only grok-4.20-multi-agent-0309 accepts it.
        """
        messages = [{"role": "user", "content": "Hi"}]
        for model in ("grok-4.20-0309-reasoning", "grok-4.20-0309-non-reasoning"):
            kw = transport.build_kwargs(
                model=model, messages=messages, tools=[],
                is_xai_responses=True,
                reasoning_config={"effort": "high"},
            )
            assert "reasoning" not in kw, f"{model} must not receive reasoning"

    def test_xai_grok_4_20_multi_agent_keeps_reasoning_effort(self, transport):
        """grok-4.20-multi-agent-0309 is the one grok-4.20 variant that accepts effort."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-4.20-multi-agent-0309", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"effort": "low"},
        )
        assert kw.get("reasoning") == {"effort": "low"}

    def test_xai_grok_code_fast_omits_reasoning_effort(self, transport):
        """grok-code-fast-1 rejects reasoning.effort."""
        messages = [{"role": "user", "content": "Hi"}]
        kw = transport.build_kwargs(
            model="grok-code-fast-1", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"effort": "high"},
        )
        assert "reasoning" not in kw

    def test_xai_aggregator_prefix_stripped(self, transport):
        """`x-ai/grok-3-mini` (OpenRouter-style slug) still resolves correctly."""
        messages = [{"role": "user", "content": "Hi"}]
        # Effort-capable
        kw = transport.build_kwargs(
            model="x-ai/grok-3-mini", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"effort": "high"},
        )
        assert kw.get("reasoning") == {"effort": "high"}
        # Effort-incapable
        kw = transport.build_kwargs(
            model="x-ai/grok-4-0709", messages=messages, tools=[],
            is_xai_responses=True,
            reasoning_config={"effort": "high"},
        )
        assert "reasoning" not in kw


class TestCodexValidateResponse:

    def test_none_response(self, transport):
        assert transport.validate_response(None) is False

    def test_empty_output(self, transport):
        r = SimpleNamespace(output=[], output_text=None)
        assert transport.validate_response(r) is False

    def test_valid_output(self, transport):
        r = SimpleNamespace(output=[{"type": "message", "content": []}])
        assert transport.validate_response(r) is True

    def test_output_text_fallback_not_valid(self, transport):
        """validate_response is strict — output_text doesn't make it valid.
        The caller handles output_text fallback with diagnostic logging."""
        r = SimpleNamespace(output=None, output_text="Some text")
        assert transport.validate_response(r) is False


class TestCodexMapFinishReason:

    def test_completed(self, transport):
        assert transport.map_finish_reason("completed") == "stop"

    def test_incomplete(self, transport):
        assert transport.map_finish_reason("incomplete") == "length"

    def test_failed(self, transport):
        assert transport.map_finish_reason("failed") == "stop"

    def test_unknown(self, transport):
        assert transport.map_finish_reason("unknown_status") == "stop"


class TestCodexNormalizeResponse:

    def test_text_response(self, transport):
        """Normalize a simple text Codex response."""
        r = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[SimpleNamespace(type="output_text", text="Hello world")],
                    status="completed",
                ),
            ],
            status="completed",
            incomplete_details=None,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                                  input_tokens_details=None, output_tokens_details=None),
        )
        nr = transport.normalize_response(r)
        assert isinstance(nr, NormalizedResponse)
        assert nr.content == "Hello world"
        assert nr.finish_reason == "stop"

    def test_message_items_preserved_in_provider_data(self, transport):
        """Codex assistant message item ids/phases must survive transport normalization."""
        r = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    id="msg_abc",
                    phase="final_answer",
                    content=[SimpleNamespace(type="output_text", text="Hello world")],
                    status="completed",
                ),
            ],
            status="completed",
            incomplete_details=None,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                                  input_tokens_details=None, output_tokens_details=None),
        )
        nr = transport.normalize_response(r)
        assert nr.codex_message_items == [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Hello world"}],
                "id": "msg_abc",
                "phase": "final_answer",
            }
        ]

    def test_tool_call_response(self, transport):
        """Normalize a Codex response with tool calls."""
        r = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_abc123",
                    name="terminal",
                    arguments=json.dumps({"command": "ls"}),
                    id="fc_abc123",
                    status="completed",
                ),
            ],
            status="completed",
            incomplete_details=None,
            usage=SimpleNamespace(input_tokens=10, output_tokens=20,
                                  input_tokens_details=None, output_tokens_details=None),
        )
        nr = transport.normalize_response(r)
        assert nr.finish_reason == "tool_calls"
        assert len(nr.tool_calls) == 1
        tc = nr.tool_calls[0]
        assert tc.name == "terminal"
        assert '"command"' in tc.arguments

    def test_tool_search_items_and_namespace_are_preserved(self, transport):
        """Hosted tool-search replay items must survive across store=False turns."""
        loaded_namespace = {
            "type": "namespace",
            "name": "unit",
            "description": "Unit MCP tools.",
            "tools": [
                {
                    "type": "function",
                    "name": "mcp_unit_lookup",
                    "description": "Lookup a unit test value.",
                    "defer_loading": True,
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        }
        r = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="tool_search_call",
                    execution="server",
                    call_id=None,
                    status="completed",
                    arguments={"paths": ["unit"]},
                ),
                SimpleNamespace(
                    type="tool_search_output",
                    execution="server",
                    call_id=None,
                    status="completed",
                    tools=[loaded_namespace],
                ),
                SimpleNamespace(
                    type="function_call",
                    call_id="call_abc123",
                    name="mcp_unit_lookup",
                    namespace="unit",
                    arguments="{}",
                    id="fc_abc123",
                    status="completed",
                ),
            ],
            status="completed",
            incomplete_details=None,
            usage=SimpleNamespace(input_tokens=10, output_tokens=20,
                                  input_tokens_details=None, output_tokens_details=None),
        )
        nr = transport.normalize_response(r)
        assert nr.finish_reason == "tool_calls"
        assert nr.codex_tool_search_items == [
            {
                "type": "tool_search_call",
                "execution": "server",
                "call_id": None,
                "status": "completed",
                "arguments": {"paths": ["unit"]},
            },
            {
                "type": "tool_search_output",
                "execution": "server",
                "call_id": None,
                "status": "completed",
                "tools": [loaded_namespace],
            },
        ]
        assert nr.tool_calls[0].namespace == "unit"



class TestCodexTransportTimeout:
    """Forward per-request timeout from build_kwargs to the SDK kwargs."""

    def test_positive_timeout_preserved(self, transport):
        kw = transport.build_kwargs(
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            timeout=600.0,
        )
        assert kw.get("timeout") == 600.0

    def test_zero_timeout_dropped(self, transport):
        kw = transport.build_kwargs(
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            timeout=0,
        )
        assert "timeout" not in kw

    def test_none_timeout_omitted(self, transport):
        kw = transport.build_kwargs(
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            timeout=None,
        )
        assert "timeout" not in kw

    def test_inf_timeout_dropped(self, transport):
        kw = transport.build_kwargs(
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            timeout=float("inf"),
        )
        assert "timeout" not in kw

    def test_bool_timeout_dropped(self, transport):
        """``True`` is technically int but must not survive — caller bug guard."""
        kw = transport.build_kwargs(
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            timeout=True,
        )
        assert "timeout" not in kw

    def test_request_overrides_can_supply_timeout(self, transport):
        """request_overrides["timeout"] is honored when no explicit kwarg passed."""
        kw = transport.build_kwargs(
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            request_overrides={"timeout": 450.0},
        )
        assert kw.get("timeout") == 450.0
