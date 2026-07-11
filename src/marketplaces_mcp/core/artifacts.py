from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .config import get_settings


def _artifacts_root() -> Path:
    root = get_settings().artifact_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_artifact(payload: dict[str, Any], artifact_id: str | None = None) -> str:
    artifact_id = artifact_id or uuid.uuid4().hex
    artifact_dir = _artifacts_root() / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload_path = artifact_dir / "content.json"
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return artifact_id


def get_artifact_path(artifact_id: str) -> Path:
    return _artifacts_root() / artifact_id


def read_artifact(artifact_id: str, name: str = "content.json") -> dict[str, Any] | str:
    base = get_artifact_path(artifact_id)
    target = (base / name).resolve()
    if not target.exists():
        raise FileNotFoundError(f"artifact not found: {artifact_id}/{name}")

    text = target.read_text(encoding="utf-8")
    if name.endswith(".json"):
        return json.loads(text)
    return text
