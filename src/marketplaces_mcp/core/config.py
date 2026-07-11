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


def get_settings() -> Settings:
    return Settings()
