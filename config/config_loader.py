"""Read runtime configuration from config/env.yaml.

All URLs, credentials, and timeouts must come from here; test code must not
hardcode them.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent
CONFIG_FILE = CONFIG_DIR / "env.yaml"


class ConfigError(RuntimeError):
    """Raised when env.yaml is missing or malformed."""


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the YAML configuration mapping."""
    config_path = Path(path) if path is not None else CONFIG_FILE
    if not config_path.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ConfigError(f"Configuration root must be a mapping: {config_path}")
    return data


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """Return the cached configuration mapping."""
    return load_config()


def get_value(path: str, default: Any = None, config: dict | None = None) -> Any:
    """Read a dotted path such as 'credentials.username'."""
    node: Any = config if config is not None else get_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def get_required(path: str, config: dict | None = None) -> Any:
    """Read a required dotted path, raising ConfigError when absent."""
    missing = object()
    value = get_value(path, default=missing, config=config)
    if value is missing:
        raise ConfigError(f"Missing required configuration key: {path}")
    return value
