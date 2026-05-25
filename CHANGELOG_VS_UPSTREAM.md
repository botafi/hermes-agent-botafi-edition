Adds a per-call terminal backend override so sessions can default to sandboxed Docker while explicitly allowing local control-plane commands when needed.


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
