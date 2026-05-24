Adds a per-call terminal backend override so sessions can default to sandboxed Docker while explicitly allowing local control-plane commands when needed.

- Backported upstream #26767: stop injecting `session_id` and `x-client-request-id` through `extra_headers` for the chatgpt.com Codex Responses backend, while preserving body-level `prompt_cache_key` cache affinity.
- Backported upstream #24126: preserve configured timeouts for Codex Responses requests and estimate non-stream stale-call size from the full Responses payload (`input`, `instructions`, and `tools`) instead of only Chat Completions `messages`.

## Milestone 1 — `terminal.docker_cwd` + File Tool Backend Override

### `terminal.docker_cwd` (2026-05-24)

Adds a Docker-only working directory default that does not affect the local/control-plane backend.
Configured via `config.yaml` (`terminal.docker_cwd`) or `TERMINAL_DOCKER_CWD` env var.

```yaml
terminal:
  backend: docker
  cwd: /opt/data           # local/control-plane default
  docker_cwd: /workspace   # Docker sandbox default
```

Precedence:
1. Per-call `workdir` overrides both.
2. If `backend=docker` and `docker_cwd` is set, use `docker_cwd` as default.
3. Otherwise fall back to `terminal.cwd`.
4. `backend=local` ignores `docker_cwd`.

### File tool `backend` override

File tools (`read_file`, `write_file`, `patch`, `search_files`) now accept an optional
`backend` parameter (`"local"` or `"docker"`) to override the terminal backend for that
operation. Default (`None`) uses the configured `terminal.backend`.

When the configured/default backend is `docker` and a file tool explicitly requests
`backend="local"`, the operation is approval-gated to prevent silent sandbox escape.
Docker/default file operations remain sandboxed and do not require local approval.

The `execute_code` tool does NOT expose the `backend` override — it was intentionally
blocked in the sandbox stub to prevent sandboxed Python from escaping to local.
