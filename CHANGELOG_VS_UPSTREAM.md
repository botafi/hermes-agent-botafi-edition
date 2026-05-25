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

#### Approval UX and scoping hardening

Local-backend file approvals are now scoped as their own approval kind (`file_backend_local`) instead of sharing the generic dangerous-command approval bucket. This keeps file-tool approval choices from accidentally resolving unrelated pending command approvals in the same gateway session.

Gateway UIs expose file-specific approval choices:

- **Allow Session** approves future local-backend calls for the same file tool type, such as `read_file`.
- **Allow All File Tools** approves local-backend access for all file tools for the current session only.

File-tool approval checks intentionally consult session approvals only. Stale permanent `command_allowlist` entries such as `file:*` or `file:backend:local:any` do not bypass the local filesystem escape-hatch approval.

Concurrent same-type prompts are also coalesced: approving one queued local-backend `read_file` prompt for the session resolves sibling queued `read_file` prompts, while different file tools and dangerous-command prompts remain pending for separate decisions.
