"""Small, project-local state for the opt-in CLI foundation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "enabled": False,
    "profile": "balanced",
    "mode": "manual",
    "policy": {},
    "budget": {},
}


class ConfigError(ValueError):
    pass


def config_path(project: str | Path) -> Path:
    return Path(project).resolve() / ".agentharness" / "config.yaml"


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError("config must be a YAML mapping")
    if set(data) != set(DEFAULT_CONFIG):
        raise ConfigError("config must contain exactly: " + ", ".join(DEFAULT_CONFIG))
    if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise ConfigError("unsupported schema_version")
    if type(data["enabled"]) is not bool:
        raise ConfigError("enabled must be a boolean")
    if data["profile"] not in ("minimal", "balanced", "strict"):
        raise ConfigError("profile must be minimal, balanced, or strict")
    if data["mode"] != "manual":
        raise ConfigError("M1 supports mode: manual only")
    if not isinstance(data["policy"], dict) or data["policy"]:
        raise ConfigError("M1 policy must be an empty mapping")
    if not isinstance(data["budget"], dict) or data["budget"]:
        raise ConfigError("M1 budget must be an empty mapping")
    return data


def load_config(project: str | Path) -> tuple[dict[str, Any], bool]:
    path = config_path(project)
    if not path.exists() and not path.is_symlink():
        return DEFAULT_CONFIG.copy(), False
    if path.is_symlink() or not path.is_file():
        raise ConfigError("config path must be a regular file")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config: {exc}") from exc
    return _validate(data), True


def set_enabled(project: str | Path, enabled: bool) -> tuple[dict[str, Any], bool]:
    if not Path(project).is_dir():
        raise ConfigError("project must be an existing directory")
    data, configured = load_config(project)
    if configured and data["enabled"] == enabled:
        return data, False
    path = config_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    updated = {**data, "enabled": enabled}
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".config-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            yaml.safe_dump(updated, handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return updated, True


def status(project: str | Path) -> dict[str, Any]:
    data, configured = load_config(project)
    return {
        **data,
        "configured": configured,
        "project": str(Path(project).resolve()),
        "config_path": str(config_path(project)),
        "host_adapter_installed": False,
        "automatic_checks": False,
        "llm_calls": False,
        "recent_checks": None,
        "cost_estimate": None,
    }
