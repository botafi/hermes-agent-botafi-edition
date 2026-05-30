from types import SimpleNamespace

from tools.delegate_tool import _resolve_delegation_credentials


def test_live_call_delegate_defaults_to_main_runtime_when_enabled():
    parent = SimpleNamespace(
        _live_call_delegate_to_main=True,
        _live_call_main_runtime={
            "model": "main-model",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "main-key",
            "api_mode": "chat_completions",
            "command": None,
            "args": [],
        },
    )

    creds = _resolve_delegation_credentials({}, parent)

    assert creds["model"] == "main-model"
    assert creds["provider"] == "openrouter"
    assert creds["api_key"] == "main-key"


def test_delegation_model_override_wins_over_live_call_main_runtime():
    parent = SimpleNamespace(
        _live_call_delegate_to_main=True,
        _live_call_main_runtime={
            "model": "main-model",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "main-key",
            "api_mode": "chat_completions",
        },
    )

    creds = _resolve_delegation_credentials({"model": "delegation-model"}, parent)

    assert creds["model"] == "delegation-model"
    assert creds["provider"] is None
