from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_MARKETPLACE_ENV_ALIASES = {
    "ozon": ("MARKETPLACES_PROXY_OZON_URL", "MARKETPLACES_OZON_PROXY_URL", "OZON_PROXY_URL"),
    "wildberries": (
        "MARKETPLACES_PROXY_WILDBERRIES_URL",
        "MARKETPLACES_WILDBERRIES_PROXY_URL",
        "WILDBERRIES_PROXY_URL",
    ),
    "yandex_market": (
        "MARKETPLACES_PROXY_YANDEX_MARKET_URL",
        "MARKETPLACES_YANDEX_MARKET_PROXY_URL",
        "YANDEX_MARKET_PROXY_URL",
    ),
    "avito": ("MARKETPLACES_PROXY_AVITO_URL", "MARKETPLACES_AVITO_PROXY_URL", "AVITO_PROXY_URL"),
}


def _default_config_path() -> Path:
    value = os.getenv("MARKETPLACES_CONFIG")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".config" / "marketplaces-mcp" / "config.json"


def _read_config(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_fixture_dir(config: dict[str, Any]) -> Path:
    value = os.getenv("MARKETPLACES_FIXTURES_DIR") or config.get("fixture_dir")
    if value:
        return Path(str(value)).expanduser()
    return Path.cwd() / "tests" / "fixtures"


def _default_artifact_dir(config: dict[str, Any]) -> Path:
    value = os.getenv("MARKETPLACES_ARTIFACT_DIR") or config.get("artifact_dir")
    if value:
        return Path(str(value)).expanduser()
    return Path.cwd() / ".marketplaces_artifacts"


def _default_web_backend(config: dict[str, Any]) -> str:
    value = str(os.getenv("MARKETPLACES_WEB_BACKEND") or config.get("web_backend") or "hive_web").lower().strip()
    return value if value in {"hive_web", "legacy", "auto"} else "hive_web"


def _default_hive_web_max_tokens(config: dict[str, Any]) -> int:
    value = os.getenv("MARKETPLACES_HIVE_WEB_MAX_TOKENS") or config.get("hive_web_max_tokens")
    if not value:
        return 12000
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 12000


def _default_camofox_url(config: dict[str, Any]) -> str:
    return str(os.getenv("MARKETPLACES_CAMOFOX_URL") or config.get("camofox_url") or "").strip().rstrip("/")


def _default_avito_region_slug(config: dict[str, Any]) -> str:
    value = str(os.getenv("MARKETPLACES_AVITO_REGION_SLUG") or config.get("avito_region_slug") or "all")
    value = value.strip().strip("/")
    return value or "all"


def _default_avito_state_path(config: dict[str, Any]) -> Path:
    value = os.getenv("MARKETPLACES_AVITO_STATE_PATH") or config.get("avito_state_path")
    if value:
        return Path(str(value)).expanduser()
    return Path.home() / ".cache" / "marketplaces-mcp" / "avito-access-state.json"


def _float_setting(config: dict[str, Any], env_name: str, config_key: str, default: float, minimum: float = 0.0) -> float:
    value = os.getenv(env_name)
    if value is None:
        value = config.get(config_key)
    if value is None:
        return default
    try:
        return max(float(value), minimum)
    except (TypeError, ValueError):
        return default


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).lower().strip() in {"1", "true", "yes", "on"}


def _default_browser_headless(config: dict[str, Any]) -> bool:
    value = os.getenv("MARKETPLACES_BROWSER_HEADLESS")
    if value is None:
        value = config.get("browser_headless")
    return _as_bool(value, default=True)


def _default_browser_channel(config: dict[str, Any]) -> str | None:
    value = os.getenv("MARKETPLACES_BROWSER_CHANNEL") or config.get("browser_channel")
    return str(value).strip() if value else None


def _default_browser_args(config: dict[str, Any]) -> list[str]:
    value = os.getenv("MARKETPLACES_BROWSER_ARGS")
    if value is not None:
        return [part for part in value.split() if part]
    raw = config.get("browser_args") or []
    if isinstance(raw, str):
        return [part for part in raw.split() if part]
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


def _default_browser_locale(config: dict[str, Any]) -> str | None:
    value = os.getenv("MARKETPLACES_BROWSER_LOCALE") or config.get("browser_locale")
    return str(value).strip() if value else None


def _default_browser_timezone(config: dict[str, Any]) -> str | None:
    value = os.getenv("MARKETPLACES_BROWSER_TIMEZONE") or config.get("browser_timezone")
    return str(value).strip() if value else None


def _default_browser_default_user_agent(config: dict[str, Any]) -> bool:
    value = os.getenv("MARKETPLACES_BROWSER_DEFAULT_USER_AGENT")
    if value is None:
        value = config.get("browser_default_user_agent")
    return _as_bool(value, default=False)


def _default_proxies(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("proxies") or {}
    proxies = {str(key): str(value).strip() for key, value in raw.items() if value} if isinstance(raw, dict) else {}
    for marketplace, env_names in _MARKETPLACE_ENV_ALIASES.items():
        for env_name in env_names:
            value = os.getenv(env_name)
            if value and value.strip():
                proxies[marketplace] = value.strip()
                break
    return proxies


@dataclass(frozen=True)
class Settings:
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    request_timeout: float = 12.0
    config_path: Path = field(default_factory=_default_config_path)
    fixture_dir: Path = field(default_factory=lambda: _default_fixture_dir(_read_config(_default_config_path())))
    artifact_dir: Path = field(default_factory=lambda: _default_artifact_dir(_read_config(_default_config_path())))
    web_backend: str = field(default_factory=lambda: _default_web_backend(_read_config(_default_config_path())))
    hive_web_max_tokens: int = field(default_factory=lambda: _default_hive_web_max_tokens(_read_config(_default_config_path())))
    camofox_url: str = field(default_factory=lambda: _default_camofox_url(_read_config(_default_config_path())))
    avito_region_slug: str = field(default_factory=lambda: _default_avito_region_slug(_read_config(_default_config_path())))
    avito_state_path: Path = field(default_factory=lambda: _default_avito_state_path(_read_config(_default_config_path())))
    avito_min_interval_seconds: float = field(
        default_factory=lambda: _float_setting(
            _read_config(_default_config_path()),
            "MARKETPLACES_AVITO_MIN_INTERVAL_SECONDS",
            "avito_min_interval_seconds",
            10.0,
        )
    )
    avito_block_cooldown_seconds: float = field(
        default_factory=lambda: _float_setting(
            _read_config(_default_config_path()),
            "MARKETPLACES_AVITO_BLOCK_COOLDOWN_SECONDS",
            "avito_block_cooldown_seconds",
            21600.0,
            60.0,
        )
    )
    proxies: dict[str, str] = field(default_factory=lambda: _default_proxies(_read_config(_default_config_path())))
    browser_headless: bool = field(default_factory=lambda: _default_browser_headless(_read_config(_default_config_path())))
    browser_channel: str | None = field(default_factory=lambda: _default_browser_channel(_read_config(_default_config_path())))
    browser_args: list[str] = field(default_factory=lambda: _default_browser_args(_read_config(_default_config_path())))
    browser_locale: str | None = field(default_factory=lambda: _default_browser_locale(_read_config(_default_config_path())))
    browser_timezone: str | None = field(default_factory=lambda: _default_browser_timezone(_read_config(_default_config_path())))
    browser_default_user_agent: bool = field(
        default_factory=lambda: _default_browser_default_user_agent(_read_config(_default_config_path()))
    )

    def proxy_url_for(self, marketplace: str) -> str | None:
        value = self.proxies.get(marketplace)
        return value.strip() if value else None


def get_settings() -> Settings:
    config_path = _default_config_path()
    config = _read_config(config_path)
    return Settings(
        config_path=config_path,
        fixture_dir=_default_fixture_dir(config),
        artifact_dir=_default_artifact_dir(config),
        web_backend=_default_web_backend(config),
        hive_web_max_tokens=_default_hive_web_max_tokens(config),
        camofox_url=_default_camofox_url(config),
        avito_region_slug=_default_avito_region_slug(config),
        avito_state_path=_default_avito_state_path(config),
        avito_min_interval_seconds=_float_setting(
            config,
            "MARKETPLACES_AVITO_MIN_INTERVAL_SECONDS",
            "avito_min_interval_seconds",
            10.0,
        ),
        avito_block_cooldown_seconds=_float_setting(
            config,
            "MARKETPLACES_AVITO_BLOCK_COOLDOWN_SECONDS",
            "avito_block_cooldown_seconds",
            21600.0,
            60.0,
        ),
        proxies=_default_proxies(config),
        browser_headless=_default_browser_headless(config),
        browser_channel=_default_browser_channel(config),
        browser_args=_default_browser_args(config),
        browser_locale=_default_browser_locale(config),
        browser_timezone=_default_browser_timezone(config),
        browser_default_user_agent=_default_browser_default_user_agent(config),
    )
