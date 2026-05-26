"""Hosted tool-search gating for Responses-compatible providers."""

from __future__ import annotations

import fnmatch
from typing import Any
from urllib.parse import urlparse


_DEFAULT_ALLOW_MODELS = ("gpt-5.4*", "gpt-5.5*", "gpt-6*")
_DEFAULT_DENY_MODELS = ("gpt-5.4-nano*",)
_OFF_VALUES = {"0", "false", "no", "off", "disabled", "disable"}
_ON_VALUES = {"1", "true", "yes", "on", "enabled", "enable"}


def _enabled_value(value: Any, *, default: str = "auto") -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _ON_VALUES:
            return "on"
        if normalized in _OFF_VALUES:
            return "off"
        if normalized == "auto":
            return "auto"
    return default


def _hostname(base_url: str | None) -> str:
    try:
        return (urlparse(str(base_url or "")).hostname or "").lower()
    except Exception:
        return ""


def _provider_key(provider: str | None, base_url: str | None) -> str:
    provider_norm = (provider or "").strip().lower()
    if provider_norm == "openai":
        return "openai-api"
    if provider_norm:
        return provider_norm
    if _hostname(base_url) == "api.openai.com":
        return "openai-api"
    if _hostname(base_url) == "chatgpt.com" and "/backend-api/codex" in str(base_url or "").lower():
        return "openai-codex"
    return ""


def _official_openai_responses(provider: str | None, base_url: str | None) -> bool:
    key = _provider_key(provider, base_url)
    host = _hostname(base_url)
    if key == "openai-api":
        return not str(base_url or "").strip() or host == "api.openai.com"
    if key == "openai-codex":
        return not str(base_url or "").strip() or (
            host == "chatgpt.com" and "/backend-api/codex" in str(base_url or "").lower()
        )
    return host == "api.openai.com"


def _model_matches(model: str, patterns: Any) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    if not isinstance(patterns, (list, tuple, set)):
        return False
    model_norm = (model or "").strip().lower()
    return any(fnmatch.fnmatchcase(model_norm, str(pattern).strip().lower()) for pattern in patterns)


def _hosted_search_config() -> dict:
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        return ((cfg.get("tools") or {}).get("hosted_search") or {})
    except Exception:
        return {}


def provider_supports_hosted_tool_search(
    *,
    provider: str | None,
    model: str | None,
    base_url: str | None,
) -> bool:
    """Return True when hosted ``tool_search`` should be sent.

    Default policy is conservative:
    - official OpenAI Responses surfaces are auto-enabled for supported models;
    - OpenAI-compatible proxies/aggregators are off unless explicitly enabled;
    - provider and model config can force on/off or tune allow/deny patterns.
    """
    cfg = _hosted_search_config()
    global_enabled = _enabled_value(cfg.get("enabled", "auto"))
    if global_enabled == "off":
        return False

    key = _provider_key(provider, base_url)
    profile_enabled = ""
    profile_allow = ()
    profile_deny = ()
    try:
        from providers import get_provider_profile

        profile = get_provider_profile(key or (provider or ""))
        if profile is not None:
            profile_enabled = getattr(profile, "hosted_tool_search", "") or ""
            profile_allow = getattr(profile, "hosted_tool_search_model_allow", ()) or ()
            profile_deny = getattr(profile, "hosted_tool_search_model_deny", ()) or ()
    except Exception:
        pass

    provider_cfgs = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    provider_cfg = provider_cfgs.get(key) if isinstance(provider_cfgs, dict) else None
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}

    provider_enabled = _enabled_value(provider_cfg.get("enabled", profile_enabled or "auto"))
    if provider_enabled == "off":
        return False

    if provider_enabled == "on" or global_enabled == "on":
        base_enabled = True
    else:
        base_enabled = _official_openai_responses(provider, base_url)
    if not base_enabled:
        return False

    deny_patterns = provider_cfg.get("model_deny", profile_deny or _DEFAULT_DENY_MODELS)
    allow_patterns = provider_cfg.get("model_allow", profile_allow or _DEFAULT_ALLOW_MODELS)
    model_name = (model or "").strip()
    if _model_matches(model_name, deny_patterns):
        return False
    return _model_matches(model_name, allow_patterns)
