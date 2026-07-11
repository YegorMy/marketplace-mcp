# Agent notes

`marketplaces_mcp` is a read-only MCP server for product search and comparison across Ozon and Yandex Market.

## Rules

- Keep the service read-only. Do not add login, account sessions, cart actions, orders, reservations, or payments.
- Do not bypass CAPTCHA, anti-bot pages, or rate limits. Return `CAPTCHA_OR_BLOCKED` and a useful source/search URL instead.
- Tests must work in `fixture` mode with local HTML strings or files and no network access.
- Tool outputs must match the schemas in `core/models.py`.
- Marketplace failures should not crash the MCP server. Return warnings and partial structured data when possible.

## Verification

```bash
uv run pytest -q
uv run python scripts/test-mcp-client.py
uv run python scripts/smoke-search.py --query "бумага a4" --limit 2
```

Live marketplace smoke tests may return warnings if a marketplace blocks scraping. That is acceptable when the MCP response stays structured and includes a source URL.
