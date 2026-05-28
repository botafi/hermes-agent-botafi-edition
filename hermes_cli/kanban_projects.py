"""Project-directory discovery for Kanban task workspaces."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _configured_project_dirs(config: dict[str, Any]) -> list[str]:
    """Return raw project-directory roots from config.

    Canonical key: ``kanban.projects_directories``.

    The camelCase aliases are accepted because the dashboard request that
    introduced this feature used ``projectsDirectories`` terminology.
    """
    kanban_cfg = config.get("kanban") if isinstance(config, dict) else {}
    if not isinstance(kanban_cfg, dict):
        kanban_cfg = {}
    raw = (
        kanban_cfg.get("projects_directories")
        or kanban_cfg.get("projectsDirectories")
        or config.get("projectsDirectories")
        or []
    )
    if isinstance(raw, (str, os.PathLike)):
        return [str(raw)]
    if not isinstance(raw, list):
        return []
    return [str(p) for p in raw if str(p).strip()]


def _expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def list_project_roots(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return configured project roots with existence metadata."""
    roots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _configured_project_dirs(config):
        try:
            path = _expand_path(raw)
        except Exception:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        roots.append({
            "path": key,
            "exists": path.exists(),
            "is_dir": path.is_dir(),
        })
    return roots


def list_projects(config: dict[str, Any]) -> list[dict[str, str]]:
    """Discover direct child directories under configured project roots."""
    projects: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for root in list_project_roots(config):
        if not root["exists"] or not root["is_dir"]:
            continue
        root_path = Path(root["path"])
        try:
            entries = sorted(
                (p for p in root_path.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            continue
        for entry in entries:
            try:
                resolved = str(entry.resolve())
            except OSError:
                continue
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            projects.append({
                "name": entry.name,
                "path": resolved,
                "root": str(root_path),
            })

    name_counts: dict[str, int] = {}
    for project in projects:
        name_counts[project["name"]] = name_counts.get(project["name"], 0) + 1
    for project in projects:
        project["label"] = (
            project["name"]
            if name_counts.get(project["name"], 0) == 1
            else f"{project['name']} ({project['root']})"
        )
    return projects


def resolve_project(config: dict[str, Any], value: str) -> dict[str, str]:
    """Resolve a configured project by unique name, label, or exact path."""
    needle = (value or "").strip()
    if not needle:
        raise ValueError("project is required")
    expanded = str(_expand_path(needle))
    matches = [
        p for p in list_projects(config)
        if needle in {p["name"], p["label"], p["path"]} or expanded == p["path"]
    ]
    if not matches:
        raise ValueError(
            f"unknown project {value!r}; add its parent to kanban.projects_directories"
        )
    if len(matches) > 1:
        labels = ", ".join(p["label"] for p in matches)
        raise ValueError(f"project {value!r} is ambiguous; use one of: {labels}")
    return matches[0]
