# Marketplace MCP

Read in Russian: [readme_rus.md](readme_rus.md)

Marketplace MCP is a read-only MCP server for product search, review sampling,
and price comparison across Ozon, Wildberries, Yandex Market, and Avito. It also
searches public Ozon Travel flight and hotel offers for explicit travel dates.

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
- `ozon_travel_flights_search` searches Ozon Travel flights by route, dates,
  passengers, cabin class, direct-flight preference, and sort order.
- `ozon_travel_hotels_search` searches Ozon Travel hotels by destination, stay
  dates, guests, rooms, rating, stars, and maximum total stay price.
- `ozon_travel_hotel_details` reads room rates for one Ozon Travel hotel URL and
  the requested stay dates.

Returned product fields include marketplace, title, URL, image URL, price, old
price, currency, rating, review count, availability, delivery notes, seller
evidence, used-item condition and location, scraped timestamp, and warnings when
data is partial.

Flight offers keep segments, airlines, stops, duration, baggage evidence, and
the displayed total price. Hotel results deliberately keep `nightly_price` and
`total_price` separate. A search-card “from” price is never silently presented
as the exact total for the requested stay; use hotel details/rates when an exact
dated total is required.

Flight prices stay unknown when the page lacks the requested journey legs.
Arrival dates use displayed day offsets; ambiguous overnight dates stay unknown.
Indexed flight links must match the requested airport/city codes exactly: a
Pulkovo or all-Moscow route cannot satisfy an SVO request. Index links carry no
verified fare or dated availability. A visible Ozon Travel block stops browser
fallback; public-index discovery can still return a matching route link.
Hotel prices are withheld when the displayed year conflicts with the request or
individual tariff prices cannot be separated. Meals, cancellation and payment
terms belong to each tariff, including different tariffs with the same price.

## Package tours and access diagnostics

- `ozon_travel_tours_search` discovers Ozon package-tour hotel candidates.
- `ozon_travel_tour_details` reads dated room, meal-plan, operator and package-price evidence for a candidate from the same browser search.
- `ozon_tours_access_status` reads cached access state by default; `inspect_tab=true` inspects the retained page without navigating, and explicit probes respect shared cooldown.
- `package_tours_search` is a separate 1001tur source, never an Ozon quote.
- `avito_access_status` reports shared Avito access/cooldown state.
- `avito_game_search` distinguishes physical cartridges, Game-Key Cards and excluded digital/account listings.

Ozon package search and details share the same access cooldown. Browser failures,
busy requests and visible challenges return structured diagnostics with a source
URL. Completing verification manually in the retained tab can be checked with
`ozon_tours_access_status(inspect_tab=true)` before continuing.

Ozon package searches can use any departure city and destination country encoded
in a supported Ozon search link. Choose a route in Ozon's public tours form, copy
the resulting search URL and pass it as `search_url` to
`ozon_travel_tours_search`. In this mode, the link supplies the complete trip;
only `limit` may accompany it. The returned `source_url` can be passed to
`ozon_travel_tour_details` with the chosen hotel name.

Automatic name lookup currently knows only Saint Petersburg (`LED`) to UAE.
Other names return `OZON_TOURS_ROUTE_LOOKUP_REQUIRED` with a link to Ozon's form;
the server never substitutes that route or guesses provider IDs. Broader automatic
location lookup has not been implemented or verified. General route parsing and
context checks are covered offline; live Ozon access remains environment-dependent.

Both input modes quote one room, one exact departure date, 1–6 adults and up to
three children aged 0–16. Age 0 means an infant under one year. Request 2–21 nights
with at most five stay lengths per call, for example 5–9 and 10–12. Copied links
with incomplete, conflicting or unsupported trip filters are rejected rather
than silently broadened. Supported meal filters are the existing all-inclusive
options; omit the meal filter in Ozon's form to search all meal plans. Additional
resort/hotel filters require separate support. Known campaign tracking parameters
are discarded.

Search-card prices can belong to breakfast even when all-inclusive filters are
selected. Package search therefore returns `total_price=null`; use details to
read each room/meal/operator row. A package rate marked as including flights
still has `flight_selection_pending=true`: specific flights, baggage, transfer,
return-flight date and final booking total remain unconfirmed. `stay_end_date`
is the hotel checkout date, not proof of the return-flight date.

Ozon package tools require Camofox at `MARKETPLACES_CAMOFOX_URL`. Use a working
display (the supported `CAMOFOX_INTERACTIVE=desktop` mode was verified) and keep
tab/session inactivity timeouts long enough for a search and details workflow
(30 minutes was tested). Browser deployment must preserve a replacement session
when an older context finishes closing. A navigation timeout retains the tab;
visible CAPTCHA/block pages are reported for manual inspection rather than retried
with rotating profiles or addresses. No login, booking or payment is automated.

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
Travel availability and prices are also snapshots and must be rechecked before
booking. The server never reserves or books a flight or hotel.

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

For local development, `scripts/camofox-bridge.py` exposes the small Camofox-compatible read-only API used by the adapters (`POST /tabs`, `GET /tabs/{tabId}/snapshot`, `DELETE /sessions/{userId}`) on top of Hive Web/Playwright:

```bash
uv run python scripts/camofox-bridge.py --host 127.0.0.1 --port 8765 --headful
```

Then set `"camofox_url": "http://127.0.0.1:8765"` in the runtime config.

Per-marketplace proxy values are only applied to that marketplace. When a proxy is configured for a marketplace, the adapter skips Hive Web for that marketplace and uses the proxied Playwright/httpx path. Use an HTTP proxy with authentication for browser-heavy marketplaces because Chromium/Playwright does not support authenticated SOCKS5 proxies. Environment variables override file values: `MARKETPLACES_PROXY_OZON_URL`, `MARKETPLACES_OZON_PROXY_URL`, `OZON_PROXY_URL`, `MARKETPLACES_PROXY_YANDEX_MARKET_URL`, `MARKETPLACES_YANDEX_MARKET_PROXY_URL`, `YANDEX_MARKET_PROXY_URL`.

Ozon is rendered with JavaScript enabled. When an Ozon proxy is configured, the Ozon adapter keeps Playwright headful even if `browser_headless` is true, because Ozon is stricter in headless mode. Disabling JavaScript is not a useful fallback: Ozon returns an anti-bot challenge asking the browser to enable JavaScript, and the adapter reports it as `CAPTCHA_OR_BLOCKED`.

Ozon Travel uses the Ozon proxy setting by default. Search-index fallback can
discover canonical flight or hotel links, but it returns no invented price and
adds `INDEX_DISCOVERY_ONLY`, `PRICE_UNVERIFIED`, and, for hotels,
`DATE_AVAILABILITY_UNVERIFIED`.

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

Run explicit read-only Ozon Travel canaries:

```bash
uv run python scripts/smoke-travel.py flights MOW LED 2030-05-10
uv run python scripts/smoke-travel.py hotels "Сочи" 2030-05-10 2030-05-12
```

Live search depends on current marketplace behavior. Ozon, Ozon Travel, and
Yandex Market may rate-limit, block, or change page markup. In that case the
smoke test should return warnings such as `CAPTCHA_OR_BLOCKED` instead of
crashing or fabricating current prices.

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
