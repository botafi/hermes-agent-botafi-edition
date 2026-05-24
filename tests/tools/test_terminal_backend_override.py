"""Tests for per-call terminal backend overrides."""

import json
from unittest.mock import MagicMock

import tools.code_execution_tool as code_execution_tool
import tools.file_tools as file_tools
import tools.terminal_tool as terminal_tool


class FakeEnvironment:
    def __init__(self, env_type: str):
        self.env_type = env_type
        self.commands = []
        self.cleaned = False
        self._persistent = True
        self.cwd = "/workspace"

    def execute(self, command, timeout=None, cwd=None, pty=False):
        self.commands.append((command, timeout, cwd, pty))
        return {"output": f"ran:{self.env_type}:{command}", "returncode": 0}

    def cleanup(self):
        self.cleaned = True


def setup_function():
    terminal_tool._active_environments.clear()
    terminal_tool._last_activity.clear()
    terminal_tool._creation_locks.clear()
    file_tools.clear_file_ops_cache()


def teardown_function():
    terminal_tool._active_environments.clear()
    terminal_tool._last_activity.clear()
    terminal_tool._creation_locks.clear()
    file_tools.clear_file_ops_cache()


def test_terminal_schema_exposes_backend_override():
    backend = terminal_tool.TERMINAL_SCHEMA["parameters"]["properties"]["backend"]

    assert backend["type"] == "string"
    assert backend["enum"] == ["local", "docker"]


def test_handle_terminal_passes_backend(monkeypatch):
    captured = {}

    def fake_terminal_tool(**kwargs):
        captured.update(kwargs)
        return json.dumps({"ok": True})

    monkeypatch.setattr(terminal_tool, "terminal_tool", fake_terminal_tool)

    terminal_tool._handle_terminal({"command": "pwd", "backend": "local"})

    assert captured["command"] == "pwd"
    assert captured["backend"] == "local"


def test_invalid_backend_override_is_rejected_before_environment_creation(monkeypatch):
    def fail_create(*_args, **_kwargs):
        raise AssertionError("invalid backend should not create an environment")

    monkeypatch.setattr(terminal_tool, "_create_environment", fail_create)

    result = json.loads(terminal_tool.terminal_tool("echo no", backend="ssh"))

    assert result["status"] == "error"
    assert result["exit_code"] == -1
    assert "Invalid backend" in result["error"]


def test_backend_override_controls_guard_backend_and_environment_cache(monkeypatch):
    created = []
    guard_envs = []

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setenv("TERMINAL_DOCKER_IMAGE", "fake-image")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(
        terminal_tool,
        "_check_all_guards",
        lambda command, env_type: guard_envs.append(env_type) or {"approved": True},
    )

    def fake_create_environment(env_type, image, cwd, timeout, **kwargs):
        created.append((env_type, image, cwd, kwargs.get("task_id")))
        return FakeEnvironment(env_type)

    monkeypatch.setattr(terminal_tool, "_create_environment", fake_create_environment)

    docker_result = json.loads(terminal_tool.terminal_tool("echo docker"))
    local_result = json.loads(terminal_tool.terminal_tool("echo local", backend="local"))

    assert docker_result["output"] == "ran:docker:echo docker"
    assert local_result["output"] == "ran:local:echo local"
    assert guard_envs == ["docker", "local"]
    assert [item[0] for item in created] == ["docker", "local"]
    assert ("default", "docker") in terminal_tool._active_environments
    assert ("default", "local") in terminal_tool._active_environments


def test_cleanup_vm_string_task_cleans_all_backend_environments():
    docker_env = FakeEnvironment("docker")
    local_env = FakeEnvironment("local")
    terminal_tool._active_environments[("default", "docker")] = docker_env
    terminal_tool._active_environments[("default", "local")] = local_env
    terminal_tool._last_activity[("default", "docker")] = 1.0
    terminal_tool._last_activity[("default", "local")] = 1.0

    terminal_tool.cleanup_vm("default")

    assert terminal_tool._active_environments == {}
    assert terminal_tool._last_activity == {}
    assert docker_env.cleaned is True
    assert local_env.cleaned is True


def test_file_tools_reuse_tuple_keyed_default_backend_environment(monkeypatch):
    env = FakeEnvironment("docker")
    terminal_tool._active_environments[("default", "docker")] = env
    terminal_tool._last_activity[("default", "docker")] = 1.0
    monkeypatch.setenv("TERMINAL_ENV", "docker")

    def fail_create(*_args, **_kwargs):
        raise AssertionError("file tools should reuse existing tuple-keyed environment")

    monkeypatch.setattr(terminal_tool, "_create_environment", fail_create)

    file_ops = file_tools._get_file_ops("default")

    assert file_ops.env is env
    assert ("default", "docker") in file_tools._file_ops_cache


def test_code_execution_reuses_tuple_keyed_default_backend_environment(monkeypatch):
    env = FakeEnvironment("docker")
    terminal_tool._active_environments[("default", "docker")] = env
    terminal_tool._last_activity[("default", "docker")] = 1.0
    monkeypatch.setenv("TERMINAL_ENV", "docker")

    def fail_create(*_args, **_kwargs):
        raise AssertionError("execute_code should reuse existing tuple-keyed environment")

    monkeypatch.setattr(terminal_tool, "_create_environment", fail_create)

    resolved_env, env_type = code_execution_tool._get_or_create_env("default")

    assert resolved_env is env
    assert env_type == "docker"


def test_cleanup_inactive_envs_handles_tuple_keys(monkeypatch):
    env = FakeEnvironment("docker")
    terminal_tool._active_environments[("default", "docker")] = env
    terminal_tool._last_activity[("default", "docker")] = 1.0
    terminal_tool._creation_locks[("default", "docker")] = object()

    monkeypatch.setattr(terminal_tool.time, "time", lambda: 999.0)

    terminal_tool._cleanup_inactive_envs(lifetime_seconds=10)

    assert env.cleaned is True
    assert ("default", "docker") not in terminal_tool._active_environments
    assert ("default", "docker") not in terminal_tool._last_activity
    assert ("default", "docker") not in terminal_tool._creation_locks


def test_cleanup_vm_explicit_backend_only_cleans_that_environment():
    docker_env = FakeEnvironment("docker")
    local_env = FakeEnvironment("local")
    terminal_tool._active_environments[("default", "docker")] = docker_env
    terminal_tool._active_environments[("default", "local")] = local_env
    terminal_tool._last_activity[("default", "docker")] = 1.0
    terminal_tool._last_activity[("default", "local")] = 1.0

    terminal_tool.cleanup_vm("default", backend="docker")

    assert docker_env.cleaned is True
    assert local_env.cleaned is False
    assert ("default", "docker") not in terminal_tool._active_environments
    assert ("default", "local") in terminal_tool._active_environments


def test_is_persistent_env_accepts_backend_parameter():
    env = FakeEnvironment("docker")
    env._persistent = True
    terminal_tool._active_environments[("default", "docker")] = env

    assert terminal_tool.is_persistent_env("default", backend="docker") is True
    assert terminal_tool.is_persistent_env("default", backend="local") is False


# ── docker_cwd tests ───────────────────────────────────────────────────


def test_docker_cwd_used_when_backend_is_docker_and_no_workdir(monkeypatch):
    """docker_cwd is used for Docker backend when no per-call workdir."""
    captured_cwds = {}

    def fake_create_environment(env_type, image, cwd, timeout, **kwargs):
        captured_cwds.setdefault(env_type, cwd)
        return FakeEnvironment(env_type)

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/opt/data")
    monkeypatch.setenv("TERMINAL_DOCKER_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_create_environment", fake_create_environment)
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(terminal_tool, "_check_all_guards", lambda c, e: {"approved": True})

    terminal_tool.terminal_tool("echo test")

    assert captured_cwds["docker"] == "/workspace"


def test_docker_cwd_not_used_when_workdir_is_provided(monkeypatch):
    """Per-call workdir overrides docker_cwd for Docker backend."""
    created_env = {"env": None}
    captured_cwds = {}

    def fake_create_environment(env_type, image, cwd, timeout, **kwargs):
        captured_cwds.setdefault(env_type, cwd)
        env = FakeEnvironment(env_type)
        created_env["env"] = env
        return env

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/opt/data")
    monkeypatch.setenv("TERMINAL_DOCKER_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_create_environment", fake_create_environment)
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(terminal_tool, "_check_all_guards", lambda c, e: {"approved": True})

    terminal_tool.terminal_tool("echo test", workdir="/custom/path")

    env_commands = created_env["env"].commands
    assert len(env_commands) == 1
    assert env_commands[0][2] == "/custom/path"


def test_docker_cwd_not_used_for_local_backend(monkeypatch):
    """docker_cwd does not affect local backend cwd."""
    captured_cwds = {}

    def fake_create_environment(env_type, image, cwd, timeout, **kwargs):
        captured_cwds.setdefault(env_type, cwd)
        return FakeEnvironment(env_type)

    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setenv("TERMINAL_CWD", "/opt/data")
    monkeypatch.setenv("TERMINAL_DOCKER_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_create_environment", fake_create_environment)
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(terminal_tool, "_check_all_guards", lambda c, e: {"approved": True})

    terminal_tool.terminal_tool("echo test")

    assert captured_cwds.get("local") == "/opt/data"


def test_docker_cwd_not_used_when_backend_override_is_local(monkeypatch):
    """docker_cwd is not used when explicit backend="local" even if TERMINAL_ENV=docker."""
    captured_cwds = {}

    def fake_create_environment(env_type, image, cwd, timeout, **kwargs):
        captured_cwds.setdefault(env_type, cwd)
        return FakeEnvironment(env_type)

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/opt/data")
    monkeypatch.setenv("TERMINAL_DOCKER_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_create_environment", fake_create_environment)
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(terminal_tool, "_check_all_guards", lambda c, e: {"approved": True})

    terminal_tool.terminal_tool("echo test", backend="local")

    assert captured_cwds.get("local") == "/opt/data"


def test_docker_cwd_falls_back_to_cwd_when_not_set(monkeypatch):
    """When docker_cwd is absent, Docker falls back to terminal.cwd."""
    captured_cwds = {}

    def fake_create_environment(env_type, image, cwd, timeout, **kwargs):
        captured_cwds.setdefault(env_type, cwd)
        return FakeEnvironment(env_type)

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/opt/data")
    # No TERMINAL_DOCKER_CWD set
    monkeypatch.setattr(terminal_tool, "_create_environment", fake_create_environment)
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(terminal_tool, "_check_all_guards", lambda c, e: {"approved": True})

    terminal_tool.terminal_tool("echo test")

    assert captured_cwds["docker"] == "/opt/data"


def test_docker_cwd_workdir_overrides_both_docker_cwd_and_cwd(monkeypatch):
    """Per-call workdir overrides both docker_cwd and cwd for any backend."""
    created_env = {"env": None}

    def fake_create_environment(env_type, image, cwd, timeout, **kwargs):
        env = FakeEnvironment(env_type)
        created_env["env"] = env
        return env

    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setenv("TERMINAL_CWD", "/opt/data")
    monkeypatch.setenv("TERMINAL_DOCKER_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_create_environment", fake_create_environment)
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(terminal_tool, "_check_all_guards", lambda c, e: {"approved": True})

    terminal_tool.terminal_tool("echo test", workdir="/explicit/path")

    env_commands = created_env["env"].commands
    assert len(env_commands) == 1
    assert env_commands[0][2] == "/explicit/path"


# ── File tool backend override tests ───────────────────────────────────


def test_read_file_schema_exposes_backend_override():
    backend = file_tools.READ_FILE_SCHEMA["parameters"]["properties"]["backend"]
    assert backend["type"] == "string"
    assert backend["enum"] == ["local", "docker"]


def test_write_file_schema_exposes_backend_override():
    backend = file_tools.WRITE_FILE_SCHEMA["parameters"]["properties"]["backend"]
    assert backend["type"] == "string"
    assert backend["enum"] == ["local", "docker"]


def test_patch_schema_exposes_backend_override():
    backend = file_tools.PATCH_SCHEMA["parameters"]["properties"]["backend"]
    assert backend["type"] == "string"
    assert backend["enum"] == ["local", "docker"]


def test_search_files_schema_exposes_backend_override():
    backend = file_tools.SEARCH_FILES_SCHEMA["parameters"]["properties"]["backend"]
    assert backend["type"] == "string"
    assert backend["enum"] == ["local", "docker"]


def test_file_tool_read_backend_passed_to_get_file_ops(monkeypatch):
    captured_backend = {}

    def fake_get_file_ops(task_id="default", backend=None):
        captured_backend["backend"] = backend
        ops = MagicMock()
        result_obj = MagicMock()
        result_obj.content = "test content"
        result_obj.to_dict.return_value = {"content": "test content"}
        ops.read_file.return_value = result_obj
        return ops

    monkeypatch.setattr(file_tools, "_get_file_ops", fake_get_file_ops)

    file_tools._handle_read_file({"path": "/test.txt", "backend": "docker"})

    assert captured_backend["backend"] == "docker"


def test_file_tool_write_backend_passed_to_get_file_ops(monkeypatch):
    captured_backend = {}

    def fake_get_file_ops(task_id="default", backend=None):
        captured_backend["backend"] = backend
        ops = MagicMock()
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {}
        ops.write_file.return_value = result_obj
        return ops

    monkeypatch.setattr(file_tools, "_get_file_ops", fake_get_file_ops)

    file_tools._handle_write_file({"path": "/test.txt", "content": "hello", "backend": "local"})

    assert captured_backend["backend"] == "local"


def test_file_tool_search_backend_passed_to_get_file_ops(monkeypatch):
    captured_backend = {}

    def fake_get_file_ops(task_id="default", backend=None):
        captured_backend["backend"] = backend
        ops = MagicMock()
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"matches": []}
        ops.search.return_value = result_obj
        return ops

    monkeypatch.setattr(file_tools, "_get_file_ops", fake_get_file_ops)

    file_tools._handle_search_files({"pattern": "test", "backend": "docker"})

    assert captured_backend["backend"] == "docker"


def test_file_tool_patch_backend_passed_to_get_file_ops(monkeypatch):
    captured_backend = {}

    def fake_get_file_ops(task_id="default", backend=None):
        captured_backend["backend"] = backend
        ops = MagicMock()
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {}
        ops.patch_replace.return_value = result_obj
        return ops

    monkeypatch.setattr(file_tools, "_get_file_ops", fake_get_file_ops)

    file_tools._handle_patch({
        "mode": "replace", "path": "/test.txt",
        "old_string": "a", "new_string": "b",
        "backend": "local",
    })

    assert captured_backend["backend"] == "local"


def test_file_tool_default_backend_is_none(monkeypatch):
    captured_backend = {}

    def fake_get_file_ops(task_id="default", backend=None):
        captured_backend["backend"] = backend
        ops = MagicMock()
        result_obj = MagicMock()
        result_obj.content = "test"
        result_obj.to_dict.return_value = {"content": "test"}
        ops.read_file.return_value = result_obj
        return ops

    monkeypatch.setattr(file_tools, "_get_file_ops", fake_get_file_ops)

    file_tools._handle_read_file({"path": "/test.txt"})

    assert captured_backend["backend"] is None


def test_file_tool_invalid_backend_is_rejected(monkeypatch):
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda **kw: None)

    result = json.loads(file_tools._handle_read_file({
        "path": "/test.txt", "backend": "invalid",
    }))

    assert "error" in result or "error" in str(result).lower()


def test_file_tool_local_docker_caches_coexist_for_same_task(monkeypatch):
    env_docker = FakeEnvironment("docker")
    env_local = FakeEnvironment("local")
    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)

    terminal_tool._active_environments[("default", "docker")] = env_docker
    terminal_tool._active_environments[("default", "local")] = env_local
    terminal_tool._last_activity[("default", "docker")] = 1.0
    terminal_tool._last_activity[("default", "local")] = 1.0

    def fail_create(*_args, **_kwargs):
        raise AssertionError("should not create new environment")

    monkeypatch.setattr(terminal_tool, "_create_environment", fail_create)

    docker_ops = file_tools._get_file_ops("default", backend="docker")
    local_ops = file_tools._get_file_ops("default", backend="local")

    assert docker_ops.env is env_docker
    assert local_ops.env is env_local
    assert docker_ops.env is not local_ops.env


# ── Approval gating tests ─────────────────────────────────────────────


def test_local_file_read_triggers_approval_when_default_is_docker(monkeypatch):
    approval_calls = []

    def fake_approval(**kwargs):
        approval_calls.append(kwargs)
        return {"approved": True}

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)

    env = FakeEnvironment("local")
    terminal_tool._active_environments[("default", "local")] = env
    terminal_tool._last_activity[("default", "local")] = 1.0

    monkeypatch.setattr(file_tools, "_check_local_file_operation_approval", fake_approval)

    file_tools._handle_read_file({"path": "/test.txt", "backend": "local"})

    assert len(approval_calls) >= 1
    assert approval_calls[0].get("backend") == "local"


def test_local_file_write_triggers_approval_when_default_is_docker(monkeypatch):
    approval_calls = []

    def fake_approval(**kwargs):
        approval_calls.append(kwargs)
        return {"approved": True}

    def fake_get_file_ops(task_id="default", backend=None):
        ops = MagicMock()
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {}
        ops.write_file.return_value = result_obj
        return ops

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)

    env = FakeEnvironment("local")
    terminal_tool._active_environments[("default", "local")] = env
    terminal_tool._last_activity[("default", "local")] = 1.0

    monkeypatch.setattr(file_tools, "_get_file_ops", fake_get_file_ops)
    monkeypatch.setattr(file_tools, "_check_local_file_operation_approval", fake_approval)

    file_tools._handle_write_file({"path": "/test.txt", "content": "hello", "backend": "local"})

    assert len(approval_calls) >= 1
    assert approval_calls[0].get("backend") == "local"


def test_local_file_patch_triggers_approval_when_default_is_docker(monkeypatch):
    approval_calls = []

    def fake_approval(**kwargs):
        approval_calls.append(kwargs)
        return {"approved": True}

    def fake_get_file_ops(task_id="default", backend=None):
        ops = MagicMock()
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {}
        ops.patch_replace.return_value = result_obj
        return ops

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)

    env = FakeEnvironment("local")
    terminal_tool._active_environments[("default", "local")] = env
    terminal_tool._last_activity[("default", "local")] = 1.0

    monkeypatch.setattr(file_tools, "_get_file_ops", fake_get_file_ops)
    monkeypatch.setattr(file_tools, "_check_local_file_operation_approval", fake_approval)

    file_tools._handle_patch({
        "mode": "replace", "path": "/test.txt",
        "old_string": "a", "new_string": "b",
        "backend": "local",
    })

    assert len(approval_calls) >= 1
    assert approval_calls[0].get("backend") == "local"


def test_docker_file_ops_do_not_require_local_approval(monkeypatch):
    approval_calls = []

    def fake_approval(**kwargs):
        approval_calls.append(kwargs)
        return {"approved": True}

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)

    env = FakeEnvironment("docker")
    terminal_tool._active_environments[("default", "docker")] = env
    terminal_tool._last_activity[("default", "docker")] = 1.0

    monkeypatch.setattr(file_tools, "_check_local_file_operation_approval", fake_approval)

    file_tools._handle_read_file({"path": "/test.txt"})

    assert len(approval_calls) == 0


def test_local_file_approval_denial_returns_error(monkeypatch):
    def fake_approval(**kwargs):
        return {"approved": False, "error": "Local file operation denied by approval policy"}

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)

    env = FakeEnvironment("local")
    terminal_tool._active_environments[("default", "local")] = env
    terminal_tool._last_activity[("default", "local")] = 1.0

    monkeypatch.setattr(file_tools, "_check_local_file_operation_approval", fake_approval)

    result = json.loads(file_tools._handle_read_file({
        "path": "/test.txt", "backend": "local",
    }))

    assert "error" in result
    assert "denied" in str(result["error"]).lower() or "denied" in str(result).lower()


def test_local_file_read_no_approval_when_default_is_local(monkeypatch):
    approval_calls = []

    def fake_approval(**kwargs):
        approval_calls.append(kwargs)
        return {"approved": True}

    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)

    env = FakeEnvironment("local")
    terminal_tool._active_environments[("default", "local")] = env
    terminal_tool._last_activity[("default", "local")] = 1.0

    monkeypatch.setattr(file_tools, "_check_local_file_operation_approval", fake_approval)

    file_tools._handle_read_file({"path": "/test.txt"})

    assert len(approval_calls) == 0
