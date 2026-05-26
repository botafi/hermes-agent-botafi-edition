Adds OpenAI hosted tool search support for Responses providers, with configurable tool namespaces and MCP server descriptions.


## Hosted tool search and namespaces

Adds support for OpenAI Responses API hosted `tool_search` on providers and models that support deferred tool loading. Hermes now keeps required tools present in the request and groups the rest into short namespaces with `defer_loading=true`.

Always-present tools default to:

- `send_message`
- `terminal`
- `process`
- `execute_code`
- `session_search`

Other built-in tools are grouped by practical area using `hermes_*` namespace names, such as `hermes_filesystem`, `hermes_web`, `hermes_browser`, `hermes_media`, `hermes_skills`, `hermes_automation`, `hermes_messaging`, `hermes_smart_home`, and `hermes_core`. The prefix avoids collisions with OpenAI hosted-tool namespaces such as `web`.

### MCP namespace support

MCP servers now map to hosted-search namespaces using `mcp_<server_name>`. For example, a configured `github` MCP server becomes the `mcp_github` namespace.

Each MCP server can now carry a short config description:

```yaml
mcp_servers:
  github:
    description: "GitHub repository, issue, and pull request tools."
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
```

`hermes mcp add` accepts `--description`, and `hermes mcp list` / `hermes mcp test` display it. Hosted tool-search namespace descriptions inherit `mcp_servers.<name>.description` unless overridden in `tools.hosted_search.namespaces`.

### Provider and model gating

Hosted tool search is configurable under `tools.hosted_search`:

- `enabled: auto | true | false`
- per-provider `enabled`
- per-provider `model_allow` and `model_deny`
- per-namespace descriptions
- per-tool `namespace` and `always_present` overrides

The default policy is conservative. Real OpenAI Responses surfaces (`openai-api` on `api.openai.com` and `openai-codex` on ChatGPT Codex OAuth) are enabled only for allowed model patterns. OpenAI-compatible proxies remain off unless explicitly opted in per provider/model.

If a provider rejects `tool_search`, `namespace`, or `defer_loading` with an explicit 4xx schema error, Hermes disables hosted tool search for the current session and retries with flat tool schemas. Non-HTTP errors and transient failures do not disable the feature.

### Replay and performance hardening

Responses history now preserves `tool_search_call`, `tool_search_output`, and function-call `namespace` records so deferred namespace tool calls can be replayed correctly with `store=false`.

Hosted-search config is loaded once per Responses request and passed into registry metadata lookup, avoiding repeated config file reads for every tool schema.


## Docker-default tool ergonomics

Adds two related capabilities for deployments that use a containerized terminal backend by default while keeping an explicit local backend available for control-plane work.

### Docker-specific default working directory

`terminal.docker_cwd` provides a Docker-only default working directory. This avoids overloading the global `terminal.cwd`, which is still used by the local backend and other non-Docker backends.

Precedence is:

1. Per-call `workdir` wins.
2. Docker backend uses `terminal.docker_cwd` when configured.
3. Otherwise the tool falls back to `terminal.cwd`.
4. Local backend ignores `terminal.docker_cwd`.

This lets a deployment choose a sandbox-friendly default cwd without breaking explicit local/backend override calls.

### File tool backend override with approval gating

File tools (`read_file`, `write_file`, `patch`, `search_files`) now accept an optional `backend` parameter limited to `"local"` or `"docker"`. When omitted, file tools continue to use the configured default terminal backend.

If the configured default backend is Docker and a file tool explicitly requests `backend="local"`, the operation is routed through the approval flow instead of silently escaping the sandbox. This applies to both read-style and mutation-style local file operations. Docker/default file operations remain sandboxed and do not require local approval.

The `execute_code` sandbox intentionally does not expose the `backend` override, so sandboxed Python cannot request local file or terminal access.

#### Approval UX and scoping hardening

Local-backend file approvals are now scoped as their own approval kind (`file_backend_local`) instead of sharing the generic dangerous-command approval bucket. This keeps file-tool approval choices from accidentally resolving unrelated pending command approvals in the same gateway session.

Gateway UIs expose file-specific approval choices:

- **Allow Session** approves future local-backend calls for the same file tool type, such as `read_file`.
- **Allow All File Tools** approves local-backend access for all file tools for the current session only.

File-tool approval checks intentionally consult session approvals only. Stale permanent `command_allowlist` entries such as `file:*` or `file:backend:local:any` do not bypass the local filesystem escape-hatch approval.

Concurrent same-type prompts are also coalesced: approving one queued local-backend `read_file` prompt for the session resolves sibling queued `read_file` prompts, while different file tools and dangerous-command prompts remain pending for separate decisions.
