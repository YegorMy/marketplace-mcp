# Marketplace MCP

[Русская версия](readme_rus.md)

Marketplace MCP is a read-only MCP server for product search and price comparison across Ozon and Yandex Market.

It is built for agents that need marketplace data without logging in, touching carts, or automating checkout. The server returns normalized product data, comparison groups, warnings, and source URLs. When a marketplace blocks scraping or shows anti-bot behavior, the tool reports that instead of trying to bypass it.

## Tools

- `marketplaces_search` searches one or more marketplaces.
- `ozon_search` searches Ozon only.
- `yandex_market_search` searches Yandex Market only.
- `marketplaces_compare` searches both marketplaces and groups similar products.
- `marketplaces_product_details` reads a product page by URL.
- `marketplaces_get_artifact` reads a saved result artifact.

Returned product fields include marketplace, title, URL, image URL, price, old price, currency, rating, review count, availability, delivery notes, scraped timestamp, and warnings when data is partial.

## Safety model

Marketplace MCP is deliberately read-only.

It does not:

- log in to Ozon or Yandex Market;
- use cookies or account sessions;
- add items to cart;
- place orders;
- reserve products;
- submit payments;
- bypass CAPTCHA or anti-bot systems.

Prices are scraped snapshots. Always open the product URL before making a purchase decision.

## Requirements

- Python 3.10+
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
