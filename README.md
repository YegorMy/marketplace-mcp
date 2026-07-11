# marketplaces-mcp

**Read-only Python MCP service** for comparing products across Ozon and Yandex Market.

Проект сделан в стиле `uv + src layout + FastMCP`, без checkout/order/login/captcha bypass.

## Что умеет
- `marketplaces_search` — поиск в выбранных маркетплейсах.
- `ozon_search` — поиск только на Ozon.
- `yandex_market_search` — поиск только на Яндекс Маркете.
- `marketplaces_compare` — поиск в обоих и групповое сравнение похожих продуктов.
- `marketplaces_product_details` — получение деталей товара по URL.
- `marketplaces_get_artifact` — чтение сохранённого артефакта.

## Быстрый старт (uv)

```bash
uv sync
uv run marketplaces-mcp
```

Через абсолютный путь uv для этой машины:

```bash
/Users/yegormy/.local/bin/uv sync
/Users/yegormy/.local/bin/uv run marketplaces-mcp
```

## Подключение к Hermes

Автоматически, если проект уже склонирован на машину с Hermes:

```bash
bash scripts/install-hermes-mcp.sh
```

На этой машине:

```yaml
mcp_servers:
  marketplaces:
    command: /Users/yegormy/.local/bin/uv
    args:
      - run
      - --project
      - /Users/yegormy/workspace/hermes/marketplaces-mcp
      - marketplaces-mcp
    connect_timeout: 60
    enabled: true
```

Для друга путь будет другим, но схема та же:

```bash
git clone <repo-url> ~/workspace/hermes/marketplaces-mcp
cd ~/workspace/hermes/marketplaces-mcp
uv sync
uv run pytest -q
bash scripts/install-hermes-mcp.sh
```

Потом добавить MCP в Hermes/Claude/Codex как stdio command `uv run --project /path/to/marketplaces-mcp marketplaces-mcp`.

Если друг не хочет запускать install script, достаточно добавить в Hermes config:

```yaml
mcp_servers:
  marketplaces:
    command: /absolute/path/to/uv
    args: ["run", "--project", "/absolute/path/to/marketplaces-mcp", "marketplaces-mcp"]
    connect_timeout: 60
    enabled: true
```

После подключения: `/reload-mcp` или новый чат.

## Проверка после правок

```bash
uv run pytest -q
uv run python scripts/test-mcp-client.py
uv run python scripts/smoke-search.py --query "бумага a4" --limit 2
```

## Структура

- `src/marketplaces_mcp/core/` — общая логика, модели, нормализация, матчинг.
- `src/marketplaces_mcp/adapters/` — парсеры Ozon / Yandex Market.
- `src/marketplaces_mcp/mcp_server/` — FastMCP инструменты и CLI.
- `scripts/` — локальные проверки.
- `tests/` — unit/fixture-тесты.

## Безопасность и ограничения
- Нет операций с оплатой, заказом и корзиной.
- Нет логина и использования личного кабинета.
- Нет попыток обхода антибота.
- Если страница блокирует, возвращаем `CAPTCHA_OR_BLOCKED` warning и корректный структурированный ответ с `search_url`.
- Цены — scraped snapshots; перед покупкой проверяйте карточку по ссылке.
