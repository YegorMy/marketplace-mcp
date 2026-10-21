#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
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

"$UV_BIN" sync --frozen --project "$PROJECT_DIR"

"$UV_BIN" run --project "$PROJECT_DIR" --with pyyaml python \
  "$PROJECT_DIR/scripts/configure-hermes-mcp.py" \
  "--project-dir=$PROJECT_DIR" "--uv-bin=$UV_BIN" "--server-name=$SERVER_NAME"

hermes mcp test "$SERVER_NAME"
echo "Done. In Hermes Desktop run /reload-mcp or start a new chat."
