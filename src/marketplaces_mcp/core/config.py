from dataclasses import dataclass, field
from pathlib import Path
import os


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


def get_settings() -> Settings:
    return Settings()
