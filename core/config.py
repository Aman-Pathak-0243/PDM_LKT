"""Configuration loading and validation.

Loads ``.env`` once, exposes a typed, immutable :class:`Config` object, and
resolves all filesystem paths relative to the repository root. Secrets are held
but **never** rendered by ``repr``/``str`` (the Grafana and DB passwords are
masked) so they cannot leak into logs or tracebacks.

Nothing here connects to anything; it only reads configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict

from dotenv import dotenv_values

# Repository root = parent of the ``core`` package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _load_env() -> Dict[str, str]:
    """Merge ``.env`` file values with the live process environment.

    Process environment wins, so a deployment can override any value without
    editing ``.env`` (useful for Docker / systemd). Empty strings are treated
    as "unset" so blank placeholder keys (e.g. unfilled module URLs) do not
    masquerade as real values.
    """
    merged: Dict[str, str] = {}
    if ENV_PATH.exists():
        for key, value in dotenv_values(ENV_PATH).items():
            if value is not None and value != "":
                merged[key] = value
    for key, value in os.environ.items():
        if value is not None and value != "":
            merged[key] = value
    return merged


class _Secret(str):
    """A string subclass that masks itself in ``repr`` to avoid leaking secrets."""

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "'***'"


@dataclass(frozen=True)
class GrafanaConfig:
    base_url: str
    username: str
    password: _Secret
    username_selector: str
    password_selector: str
    submit_selector: str
    download_button_text: str
    headless: bool
    nav_timeout_ms: int

    @property
    def login_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/login"

    @property
    def api_base(self) -> str:
        return self.base_url.rstrip("/")


@dataclass(frozen=True)
class DatabaseConfig:
    """MySQL connection details. Held but dormant until permission is granted."""

    host: str
    port: int
    user: str
    password: _Secret
    name: str
    connection_limit: int

    def sqlalchemy_url(self) -> str:
        # Only constructed by the dormant MySQL backend once enabled.
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}?charset=utf8mb4"
        )


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    title: str


@dataclass(frozen=True)
class Config:
    grafana: GrafanaConfig
    database: DatabaseConfig
    app: AppConfig
    storage_backend: str          # "csv" (active) | "mysql" (dormant, gated)
    data_dir: Path
    log_dir: Path
    fetch_default_window: str
    raw: Dict[str, str] = field(default_factory=dict, repr=False)

    # ---- module dashboard URL helpers --------------------------------------
    def module_dashboard_urls(self, module: str) -> Dict[str, str]:
        """Return ``{DASHBOARD_NAME: url}`` for a module from ``MODULE__*`` keys.

        Only non-empty values are returned, so unfilled placeholders are
        omitted (callers can detect "not configured yet").
        """
        prefix = f"{module.upper()}__"
        out: Dict[str, str] = {}
        for key, value in self.raw.items():
            if key.startswith(prefix) and value:
                out[key[len(prefix):]] = value
        return out

    @property
    def mysql_enabled(self) -> bool:
        return self.storage_backend.lower() == "mysql"


def _require(env: Dict[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise ConfigError(
            f"Required environment variable '{key}' is missing or empty in {ENV_PATH}"
        )
    return value


def _as_bool(value: str, default: bool = True) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"} if value else default


def _resolve_dir(env: Dict[str, str], key: str, default: str) -> Path:
    raw = env.get(key, default) or default
    p = Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Load, validate, and cache the configuration (singleton)."""
    env = _load_env()

    grafana = GrafanaConfig(
        base_url=_require(env, "GRAFANA_BASE_URL"),
        username=_require(env, "GRAFANA_USERNAME"),
        password=_Secret(_require(env, "GRAFANA_PASSWORD")),
        username_selector=env.get("GRAFANA_USERNAME_SELECTOR", 'input[name="user"]'),
        password_selector=env.get("GRAFANA_PASSWORD_SELECTOR", 'input[name="password"]'),
        submit_selector=env.get("GRAFANA_SUBMIT_SELECTOR", 'button[type="submit"]'),
        download_button_text=env.get("GRAFANA_DOWNLOAD_BUTTON_TEXT", "Download CSV"),
        headless=_as_bool(env.get("PLAYWRIGHT_HEADLESS", "true")),
        nav_timeout_ms=int(env.get("GRAFANA_NAV_TIMEOUT_MS", "30000")),
    )

    database = DatabaseConfig(
        host=env.get("DB_HOST", ""),
        port=int(env.get("DB_PORT", "3306")),
        user=env.get("DB_USER", ""),
        password=_Secret(env.get("DB_PASSWORD", "")),
        name=env.get("DB_NAME", "PDM"),
        connection_limit=int(env.get("DB_CONNECTION_LIMIT", "10")),
    )

    app = AppConfig(
        host=env.get("APP_HOST", "0.0.0.0"),
        port=int(env.get("APP_PORT", "8800")),
        title=env.get("APP_TITLE", "ASRS Predictive Maintenance"),
    )

    storage_backend = env.get("STORAGE_BACKEND", "csv").strip().lower()
    if storage_backend not in {"csv", "mysql"}:
        raise ConfigError(
            f"STORAGE_BACKEND must be 'csv' or 'mysql', got '{storage_backend}'"
        )

    return Config(
        grafana=grafana,
        database=database,
        app=app,
        storage_backend=storage_backend,
        data_dir=_resolve_dir(env, "DATA_DIR", "database"),
        log_dir=_resolve_dir(env, "LOG_DIR", "logs"),
        fetch_default_window=env.get("FETCH_DEFAULT_WINDOW", "now-2d"),
        raw=env,
    )
