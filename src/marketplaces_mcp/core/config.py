import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_fixture_dir() -> Path:
    value = os.getenv("MARKETPLACES_FIXTURES_DIR")
    if value:
        return Path(value).expanduser()
    return Path.cwd() / "tests" / "fixtures"


def _default_artifact_dir() -> Path:
    value = os.getenv("MARKETPLACES_ARTIFACT_DIR")
    if value:
        return Path(value).expanduser()
    return Path.cwd() / ".marketplaces_artifacts"


def _default_web_backend() -> str:
    value = os.getenv("MARKETPLACES_WEB_BACKEND", "hive_web").lower().strip()
    return value if value in {"hive_web", "legacy", "auto"} else "hive_web"


def _default_hive_web_max_tokens() -> int:
    value = os.getenv("MARKETPLACES_HIVE_WEB_MAX_TOKENS")
    if not value:
        return 12000
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 12000


def _default_camofox_url() -> str:
    return os.getenv("MARKETPLACES_CAMOFOX_URL", "").strip().rstrip("/")


def _default_avito_region_slug() -> str:
    value = os.getenv("MARKETPLACES_AVITO_REGION_SLUG", "all").strip().strip("/")
    return value or "all"


def _default_avito_state_path() -> Path:
    value = os.getenv("MARKETPLACES_AVITO_STATE_PATH")
    if value:
        return Path(value).expanduser()
    return _default_artifact_dir().parent / "avito-access-state.json"


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(float(value), minimum)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    request_timeout: float = 12.0
    fixture_dir: Path = field(default_factory=_default_fixture_dir)
    artifact_dir: Path = field(default_factory=_default_artifact_dir)
    web_backend: str = field(default_factory=_default_web_backend)
    hive_web_max_tokens: int = field(default_factory=_default_hive_web_max_tokens)
    camofox_url: str = field(default_factory=_default_camofox_url)
    avito_region_slug: str = field(default_factory=_default_avito_region_slug)
    avito_state_path: Path = field(default_factory=_default_avito_state_path)
    avito_min_interval_seconds: float = field(
        default_factory=lambda: _float_env("MARKETPLACES_AVITO_MIN_INTERVAL_SECONDS", 10.0)
    )
    avito_block_cooldown_seconds: float = field(
        default_factory=lambda: _float_env("MARKETPLACES_AVITO_BLOCK_COOLDOWN_SECONDS", 21600.0, 60.0)
    )


def get_settings() -> Settings:
    return Settings()
