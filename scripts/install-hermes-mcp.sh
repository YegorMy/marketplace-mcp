#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SERVER_NAME="${SERVER_NAME:-marketplaces}"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"

if [[ -z "$UV_BIN" ]]; then
  echo "uv is required. Install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [[ "$UV_BIN" != /* ]]; then
  UV_BIN="$(command -v "$UV_BIN")"
fi

if ! command -v hermes >/dev/null 2>&1; then
  echo "hermes CLI is required to auto-configure MCP. Project is still usable manually." >&2
  echo "Manual command: $UV_BIN run --project $PROJECT_DIR marketplaces-mcp" >&2
  exit 1
fi

"$UV_BIN" sync

"$UV_BIN" run --with pyyaml python - <<PY
from pathlib import Path
import yaml

cfg_path = Path.home() / '.hermes' / 'config.yaml'
if not cfg_path.exists():
    raise SystemExit(f'Hermes config not found: {cfg_path}')
cfg = yaml.safe_load(cfg_path.read_text()) or {}
servers = cfg.setdefault('mcp_servers', {})
servers['$SERVER_NAME'] = {
    'command': '$UV_BIN',
    'args': ['run', '--project', '$PROJECT_DIR', 'marketplaces-mcp'],
    'connect_timeout': 60,
    'enabled': True,
}
cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
print(f'configured MCP server {"$SERVER_NAME"!r} -> {"$PROJECT_DIR"}')
PY

hermes mcp test "$SERVER_NAME"
echo "Done. In Hermes Desktop run /reload-mcp or start a new chat."
