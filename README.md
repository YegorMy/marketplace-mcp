# Marketplace MCP

Read in Russian: [readme_rus.md](readme_rus.md)

Marketplace MCP is a read-only MCP server for product search, review sampling,
and price comparison across Ozon, Wildberries, Yandex Market, and Avito.

It is built for agents that need marketplace data without logging in, touching carts, or automating checkout. The server returns normalized product data, comparison groups, warnings, and source URLs. When a marketplace blocks scraping or shows anti-bot behavior, the tool reports that instead of trying to bypass it.

## Tools

- `marketplaces_search` searches one or more marketplaces.
- `ozon_search` searches Ozon only.
- `wildberries_search` searches Wildberries only.
- `yandex_market_search` searches Yandex Market only.
- `avito_search` searches Avito as an explicit used-market path.
- `marketplaces_compare` searches retail marketplaces and groups similar
  products; Avito is opt-in with `include_avito=true`.
- `marketplaces_product_details` reads a product page by URL.
- `marketplaces_product_reviews` returns a compact review sample for supported
  marketplaces.
- `marketplaces_get_artifact` reads a saved result artifact.

Returned product fields include marketplace, title, URL, image URL, price, old
price, currency, rating, review count, availability, delivery notes, seller
evidence, used-item condition and location, scraped timestamp, and warnings when
data is partial.

## Safety model

Marketplace MCP is deliberately read-only.

By default it does not:

- log in to a marketplace;
- use cookies or account sessions;
- add items to cart;
- place orders;
- reserve products;
- submit payments;
- bypass CAPTCHA or anti-bot systems.

Prices are scraped snapshots. Always open the product URL before making a purchase decision.

Marketplace MCP uses Hive Web as the default page loader (`MARKETPLACES_WEB_BACKEND=hive_web`).
`legacy` mode keeps the previous Playwright/httpx loading stack.
`auto` tries Hive Web first and falls back to legacy only if Hive Web is unavailable.

- `MARKETPLACES_WEB_BACKEND`: `hive_web` (default), `auto`, `legacy`
- `MARKETPLACES_HIVE_WEB_MAX_TOKENS`: maximum tokens for Hive Web text snapshot (default `12000`)
- `MARKETPLACES_CAMOFOX_URL`: optional Camofox base URL for anonymous ephemeral
  read-only fallback sessions.
- `MARKETPLACES_AVITO_REGION_SLUG`: Avito region path (default `all`).
- `MARKETPLACES_AVITO_STATE_PATH`: shared Avito rate-limit state file
  (default `~/.cache/marketplaces-mcp/avito-access-state.json`).
- `MARKETPLACES_AVITO_MIN_INTERVAL_SECONDS`: minimum interval between Avito live
  requests (default `10`).
- `MARKETPLACES_AVITO_BLOCK_COOLDOWN_SECONDS`: cooldown after an explicit Avito
  IP block (default `21600`, six hours).

When rendered pages are unavailable, public search-index discovery may return
canonical product links. Such results always have no verified price and include
`INDEX_DISCOVERY_ONLY` and `PRICE_UNVERIFIED`; an index snippet is never treated
as current marketplace data. Avito is excluded from default retail search and
comparison because each used listing is a unique physical item.

Runtime settings can also live in `~/.config/marketplaces-mcp/config.json` or in the path from `MARKETPLACES_CONFIG`:

```json
{
  "web_backend": "hive_web",
  "hive_web_max_tokens": 12000,
  "browser_channel": "chrome",
  "browser_headless": true,
  "browser_locale": "ru-RU",
  "browser_timezone": "Europe/Moscow",
  "browser_args": ["--disable-blink-features=AutomationControlled"],
  "browser_default_user_agent": true,
  "proxies": {
    "ozon": "http://user:password@proxy.example:19081",
    "yandex_market": null
  }
}
```

Per-marketplace proxy values are only applied to that marketplace. When a proxy is configured for a marketplace, the adapter skips Hive Web for that marketplace and uses the proxied Playwright/httpx path. Use an HTTP proxy with authentication for browser-heavy marketplaces because Chromium/Playwright does not support authenticated SOCKS5 proxies. Environment variables override file values: `MARKETPLACES_PROXY_OZON_URL`, `MARKETPLACES_OZON_PROXY_URL`, `OZON_PROXY_URL`, `MARKETPLACES_PROXY_YANDEX_MARKET_URL`, `MARKETPLACES_YANDEX_MARKET_PROXY_URL`, `YANDEX_MARKET_PROXY_URL`.

Ozon is rendered with JavaScript enabled. When an Ozon proxy is configured, the Ozon adapter keeps Playwright headful even if `browser_headless` is true, because Ozon is stricter in headless mode. Disabling JavaScript is not a useful fallback: Ozon returns an anti-bot challenge asking the browser to enable JavaScript, and the adapter reports it as `CAPTCHA_OR_BLOCKED`.

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Hermes or another MCP client

## Install

```bash
git clone https://github.com/YegorMy/marketplace-mcp.git
cd marketplace-mcp
uv sync
```

Run tests:

```bash
uv run pytest -q
```

Run the MCP smoke test:

```bash
uv run python scripts/test-mcp-client.py
```

Run a live search smoke test:

```bash
uv run python scripts/smoke-search.py --query "бумага a4" --limit 2
```

Run one explicit Avito canary without touching retail marketplaces:

```bash
uv run python scripts/live_canary.py --avito-only --avito-query "кроватка Stokke"
```

Live search depends on current marketplace behavior. Ozon and Yandex Market may rate-limit, block, or change page markup. In that case the smoke test should return warnings such as `CAPTCHA_OR_BLOCKED` instead of crashing.

## Hermes setup

The installer writes a `marketplaces` MCP server entry into `~/.hermes/config.yaml` and tests the connection:

```bash
bash scripts/install-hermes-mcp.sh
```

You can override the MCP server name:

```bash
SERVER_NAME=marketplaces bash scripts/install-hermes-mcp.sh
```

Manual Hermes config:

```yaml
mcp_servers:
  marketplaces:
    command: /absolute/path/to/uv
    args: ["run", "--project", "/absolute/path/to/marketplace-mcp", "marketplaces-mcp"]
    connect_timeout: 60
    enabled: true
```

After changing MCP config, reload MCP in the client or start a new session.

## Other MCP clients

Any MCP client that supports stdio can run the same command:

```bash
uv run --project /absolute/path/to/marketplace-mcp marketplaces-mcp
```

Claude Code:

```bash
claude mcp add -s user marketplaces -- uv run --project /absolute/path/to/marketplace-mcp marketplaces-mcp
```

Codex CLI:

```bash
codex mcp add marketplaces -- uv run --project /absolute/path/to/marketplace-mcp marketplaces-mcp
```

OpenCode uses the same stdio command in its MCP config:

```json
{
  "mcp": {
    "marketplaces": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/marketplace-mcp", "marketplaces-mcp"]
    }
  }
}
```

## Development

```bash
uv sync
uv run pytest -q
uv run python scripts/test-mcp-client.py
uv run python scripts/smoke-search.py --query "бумага a4" --limit 2
```

The adapters live under `src/marketplaces_mcp/adapters/`. Tests use fixtures where possible so the core behavior does not depend on live marketplace pages.

## License

MIT
