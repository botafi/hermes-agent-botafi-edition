"""Tests for per-call terminal backend overrides."""

import json

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
