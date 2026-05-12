Adds a per-call terminal backend override so sessions can default to sandboxed Docker while explicitly allowing local control-plane commands when needed.

- Backported upstream #26767: stop injecting `session_id` and `x-client-request-id` through `extra_headers` for the chatgpt.com Codex Responses backend, while preserving body-level `prompt_cache_key` cache affinity.
- Backported upstream #24126: preserve configured timeouts for Codex Responses requests and estimate non-stream stale-call size from the full Responses payload (`input`, `instructions`, and `tools`) instead of only Chat Completions `messages`.
