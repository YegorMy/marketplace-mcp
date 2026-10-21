"""Update one Hermes MCP entry; shared by the Bash and PowerShell installers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import yaml


def config_path() -> Path:
    override = os.environ.get("HERMES_HOME", "").strip()
    if override:
        return Path(override).expanduser() / "config.yaml"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "hermes" / "config.yaml"
    return Path.home() / ".hermes" / "config.yaml"


def configure(path: Path, project_dir: str, uv_bin: str, server_name: str) -> bool:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Hermes config not found: {path}. Run Hermes setup first.")
    config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("Hermes config must be a YAML mapping.")
    servers = config.get("mcp_servers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise ValueError("Hermes mcp_servers must be a YAML mapping.")
    entry = {
        "command": uv_bin,
        "args": ["run", "--project", project_dir, "marketplaces-mcp"],
        "connect_timeout": 60,
        "enabled": True,
    }
    if servers.get(server_name) == entry:
        return False
    config["mcp_servers"] = {**servers, server_name: entry}
    rendered = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    shutil.copy2(path, path.with_name(path.name + ".bak"))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".marketplaces-mcp-", delete=False) as output:
            temporary = Path(output.name)
            output.write(rendered)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--uv-bin", required=True)
    parser.add_argument("--server-name", default="marketplaces")
    args = parser.parse_args()
    path = config_path()
    try:
        changed = configure(path, args.project_dir, args.uv_bin, args.server_name)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps({"configured": args.server_name, "config_path": str(path), "changed": changed}))


if __name__ == "__main__":
    main()
