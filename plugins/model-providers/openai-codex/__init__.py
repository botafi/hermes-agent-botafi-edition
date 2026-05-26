"""OpenAI Codex (Responses API) provider profile."""

from providers import register_provider
from providers.base import ProviderProfile

openai_codex = ProviderProfile(
    name="openai-codex",
    aliases=("codex", "openai_codex"),
    api_mode="codex_responses",
    env_vars=(),  # OAuth external — no API key
    base_url="https://chatgpt.com/backend-api/codex",
    auth_type="oauth_external",
    hosted_tool_search="auto",
    hosted_tool_search_model_allow=("gpt-5.4*", "gpt-5.5*", "gpt-6*"),
    hosted_tool_search_model_deny=("gpt-5.4-nano*",),
)

register_provider(openai_codex)
