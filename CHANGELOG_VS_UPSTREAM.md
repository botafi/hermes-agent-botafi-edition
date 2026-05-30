# Downstream changelog vs upstream/main

This branch is currently 14 commits ahead of `upstream/main`. The downstream
changes are grouped below by feature area rather than commit order.

## Dashboard terminal and web security

- Adds an optional `/terminal` dashboard page backed by `@wterm/react` and a
  Ghostty terminal core.
- Adds authenticated `/api/terminal/pty` and `/api/terminal/containers`
  endpoints for host-shell and Docker-container terminal sessions.
- Gates dashboard terminal access behind `HERMES_DASHBOARD_TERMINAL` rather
  than a persistent config key, because shell access is an operator choice.
- Tracks dashboard PTY sessions server-side with reconnect grace, duplicate
  attachment protection, resize forwarding, cleanup, and active-session limits.
- Hardens dashboard auth by requiring the ephemeral dashboard token on sensitive
  API and WebSocket paths, accepting it through the dedicated
  `X-Hermes-Session-Token` header and preserving Bearer-token compatibility.
- Adds Host-header validation for loopback dashboard binds to reduce DNS
  rebinding exposure.

## Kanban project and workspace improvements

- Adds configurable project discovery via `kanban.projects_directories`.
  Kanban tasks can now select a configured project by name, label, or path; the
  selected project becomes a `dir` workspace.
- Adds workspace metadata to kanban tasks:
  `workspace_kind`, `workspace_path`, and `inherit_child_workspace`.
- Adds CLI and tool support for explicit workspaces:
  `--workspace`, `--project`, `--inherit-child-workspace`, and decomposition
  flags for inheriting or resetting child workspaces.
- Allows task workspaces to be updated before a worker starts, while refusing
  live worker cwd changes.
- Persists resolved workspace paths and includes workspace data in kanban
  output, dashboard plugin responses, and kanban tool payloads.
- Improves scratch-workspace cleanup safety and emits a first-use tip explaining
  that scratch workspaces are ephemeral.

## OpenAI Responses hosted tool search

- Adds support for OpenAI Responses API hosted `tool_search` on providers and
  models that support deferred tool loading.
- Keeps required tools always present in the request and groups the rest into
  short Hermes namespaces with `defer_loading=true`.
- Uses `hermes_*` namespace names for built-in tools to avoid collisions with
  OpenAI reserved hosted-tool namespaces such as `web`.
- Maps MCP toolsets to `mcp_<server_name>` namespaces and supports short MCP
  server descriptions in config, `hermes mcp add --description`, `mcp list`,
  and `mcp test`.
- Adds `tools.hosted_search` config for global/provider/model gating,
  namespace descriptions, per-tool namespace overrides, and always-present
  overrides.
- Enables the default policy only for known OpenAI Responses surfaces
  (`openai-api` and ChatGPT Codex OAuth) and allowed model patterns; compatible
  proxies stay off unless explicitly opted in.
- Falls back to flat tool schemas if a provider rejects `tool_search`,
  `namespace`, or `defer_loading` with an explicit schema-style 4xx response.
- Preserves `tool_search_call`, `tool_search_output`, and function-call
  `namespace` records so stored Responses history can replay deferred tool
  calls correctly.

Always-present tools default to:

- `send_message`
- `terminal`
- `process`
- `execute_code`
- `session_search`

## Terminal and file backend controls

- Adds a per-call `backend` override to `terminal`, currently limited to
  `local` and `docker`.
- Splits terminal environment caches and lifecycle cleanup by `(task_id,
  backend)` so local and Docker sessions do not collide.
- Adds `terminal.docker_cwd` as a Docker-only default working directory.
  Precedence is per-call `workdir`, then `terminal.docker_cwd` for Docker, then
  `terminal.cwd`.
- Adds optional `backend` overrides to `read_file`, `write_file`, `patch`, and
  `search_files`, also limited to `local` and `docker`.
- Routes file tools through the selected backend's live cwd and home handling,
  including relative paths and `~` paths.
- Keeps `execute_code` sandboxed by design; it does not expose a backend
  override that could request host filesystem or terminal access.

## Approval-flow hardening

- Adds a dedicated `file_backend_local` approval kind for file tools that
  explicitly request `backend="local"` while the configured default backend is
  Docker.
- Prevents stale permanent dangerous-command allowlist entries from bypassing
  local-backend file approvals.
- Makes file-tool approval choices session-scoped:
  **Allow Session** approves the same file tool type, and
  **Allow All File Tools** approves all local-backend file tools for the current
  session.
- Coalesces concurrent sibling approvals of the same file-tool type in a
  session, while keeping other file tools and dangerous-command prompts
  separate.
- Updates gateway, Discord button approvals, and TUI approval prompts to expose
  file-specific approval choices.

## Gateway context dump command

- Adds `/context-dump` as a gateway command, gated by
  `gateway.context_dump.enabled`.
- Captures the last provider request payload for a gateway session when enabled.
- Saves dumps under `~/.hermes/debug/context_dumps/` and uploads them through
  the platform adapter when file upload is available.

## ElevenLabs Scribe speech-to-text

- Ports upstream PR NousResearch/hermes-agent#19777 into downstream and resolves
  it against the current `origin/main`.
- Adds `stt.provider: elevenlabs` as a built-in STT provider using direct
  multipart `POST /v1/speech-to-text` requests with the `xi-api-key` header.
- Defaults to `scribe_v2`, documents `scribe_v1`, and passes through explicit
  future or custom model IDs to the ElevenLabs API.
- Supports `stt.elevenlabs` options for `language_code`, `diarize`,
  `tag_audio_events`, and `timestamps_granularity`.
- Adds quota fallback rotation from `ELEVENLABS_API_KEY` through
  `ELEVENLABS_API_KEY_10` on quota, credit, auth, and rate-limit responses.
- Adds `hermes setup stt`, dashboard config support, docs, example config, and
  focused tests for setup, dispatch, rotation, voice-mode checks, and registry
  sync.
- Keeps this downstream's existing Mistral support and uses auto-detect order:
  `local > groq > elevenlabs > openai > mistral > xai`.

## Live-call voice customization

- Adds `voice_customization` config for realtime call sessions, separate from
  generic STT/TTS and uploaded voice messages.
- Lets Discord `/voice join` sessions run on a smaller call-mode model and
  inject an additional live-call prompt without changing normal text chats.
- Marks joined-call events explicitly with `live_call_context`, and treats
  typed messages in the linked Discord text channel as live-call turns while
  the bot remains connected to voice.
- Preserves the main session runtime for `delegate_task` when
  `delegate_complex_tasks_to_main` is enabled, unless `delegation.*` is
  explicitly configured.

## Tests, docs, and config coverage

- Adds and updates tests for terminal/file backend overrides, approval scoping,
  Responses hosted tool search, dashboard auth, dashboard terminals, kanban
  project/workspace behavior, MCP descriptions, ElevenLabs Scribe STT, and
  `/context-dump`.
- Updates `cli-config.yaml.example`, default config, MCP reference docs, and
  kanban and voice-mode user docs for the new downstream options.
