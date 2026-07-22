# Marketplace MCP

English README: [README.md](README.md)

Marketplace MCP — read-only MCP-сервер для поиска товаров, компактного чтения
отзывов и сравнения предложений в Ozon, Wildberries, Яндекс Маркете и Авито.

Он нужен агентам, которым важны marketplace-данные, но не нужен доступ к аккаунту, корзине или checkout. Сервер возвращает нормализованные карточки товаров, группы похожих товаров, предупреждения и исходные ссылки. Если маркетплейс блокирует запрос или показывает антибот-защиту, инструмент сообщает об этом и не пытается обходить ограничение.

## Инструменты

- `marketplaces_search` ищет в одном или нескольких маркетплейсах.
- `ozon_search` ищет только в Ozon.
- `wildberries_search` ищет только в Wildberries.
- `yandex_market_search` ищет только в Яндекс Маркете.
- `avito_search` выполняет отдельный явный поиск б/у объявлений Авито.
- `marketplaces_compare` ищет по retail-площадкам и группирует похожие товары;
  Авито включается только через `include_avito=true`.
- `marketplaces_product_details` читает карточку товара по URL.
- `marketplaces_product_reviews` возвращает компактную выборку отзывов для
  поддерживаемых площадок.
- `marketplaces_get_artifact` читает сохранённый артефакт результата.

В ответе по товару есть marketplace, название, URL, image URL, цена, старая цена, валюта, рейтинг, число отзывов, наличие, доставка, время парсинга и warnings, если данные неполные.

## Модель безопасности

Marketplace MCP намеренно работает только на чтение.

По умолчанию он не делает следующее:

- не логинится в маркетплейсы;
- не использует cookies или пользовательские сессии;
- не добавляет товары в корзину;
- не оформляет заказы;
- не резервирует товары;
- не отправляет платежи;
- не обходит CAPTCHA или антибот-защиту.

Цены — это scraped snapshots. Перед покупкой всегда открывайте исходную ссылку и проверяйте карточку товара.

Marketplace MCP по умолчанию использует Hive Web как источник загрузки страниц (`MARKETPLACES_WEB_BACKEND=hive_web`).
Режим `legacy` оставляет прежний путь через Playwright/httpx.
Режим `auto` сначала пробует Hive Web, и использует legacy только если Hive Web недоступен.

- `MARKETPLACES_WEB_BACKEND`: `hive_web` (по умолчанию), `auto`, `legacy`
- `MARKETPLACES_HIVE_WEB_MAX_TOKENS`: максимальный размер снапшота видимого текста (по умолчанию `12000`)
- `MARKETPLACES_CAMOFOX_URL`: необязательный адрес Camofox для анонимных
  временных read-only сессий.
- `MARKETPLACES_AVITO_REGION_SLUG`: региональный path Авито, по умолчанию `all`.
- `MARKETPLACES_AVITO_STATE_PATH`: общий state-файл ограничения запросов Авито.
- `MARKETPLACES_AVITO_MIN_INTERVAL_SECONDS`: интервал live-запросов, по
  умолчанию 10 секунд.
- `MARKETPLACES_AVITO_BLOCK_COOLDOWN_SECONDS`: cooldown после явного IP-block,
  по умолчанию 21600 секунд.

Индексный fallback возвращает только каноническую ссылку без проверенной цены
и предупреждения `INDEX_DISCOVERY_ONLY`/`PRICE_UNVERIFIED`. Сниппет поисковика
не считается актуальной карточкой. Авито не входит в обычный retail compare,
потому что каждое б/у объявление описывает уникальный физический экземпляр.

## Требования

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Hermes или другой MCP-клиент

## Установка

```bash
git clone https://github.com/YegorMy/marketplace-mcp.git
cd marketplace-mcp
uv sync
```

Запуск тестов:

```bash
uv run pytest -q
```

MCP smoke test:

```bash
uv run python scripts/test-mcp-client.py
```

Live smoke test для поиска:

```bash
uv run python scripts/smoke-search.py --query "бумага a4" --limit 2
```

Один явный Avito canary без запросов к retail-площадкам:

```bash
uv run python scripts/live_canary.py --avito-only --avito-query "кроватка Stokke"
```

Live-поиск зависит от текущего поведения маркетплейсов. Ozon и Яндекс Маркет могут включить rate limit, блокировку или поменять разметку. В таком случае smoke test должен вернуть warning вроде `CAPTCHA_OR_BLOCKED`, а не падать с исключением.

## Подключение к Hermes

Скрипт прописывает MCP-сервер `marketplaces` в `~/.hermes/config.yaml` и сразу проверяет подключение:

```bash
bash scripts/install-hermes-mcp.sh
```

Имя MCP-сервера можно переопределить:

```bash
SERVER_NAME=marketplaces bash scripts/install-hermes-mcp.sh
```

Ручная конфигурация Hermes:

```yaml
mcp_servers:
  marketplaces:
    command: /absolute/path/to/uv
    args: ["run", "--project", "/absolute/path/to/marketplace-mcp", "marketplaces-mcp"]
    connect_timeout: 60
    enabled: true
```

После изменения MCP-конфига перезагрузите MCP в клиенте или начните новую сессию.

## Другие MCP-клиенты

Любой MCP-клиент со stdio-транспортом может запустить ту же команду:

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

OpenCode использует ту же stdio-команду в своём MCP-конфиге:

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

## Разработка

```bash
uv sync
uv run pytest -q
uv run python scripts/test-mcp-client.py
uv run python scripts/smoke-search.py --query "бумага a4" --limit 2
```

Адаптеры лежат в `src/marketplaces_mcp/adapters/`. Тесты по возможности используют fixtures, чтобы базовое поведение не зависело от живых страниц маркетплейсов.

## Лицензия

MIT
