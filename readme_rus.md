# Marketplace MCP

English README: [README.md](README.md)

Marketplace MCP — read-only MCP-сервер для поиска товаров, компактного чтения
отзывов и сравнения предложений в Ozon, Wildberries, Яндекс Маркете и Авито.
Также он ищет публичные предложения Ozon Travel по авиабилетам и отелям на
заданные даты.

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
- `ozon_travel_flights_search` ищет авиабилеты Ozon Travel по маршруту, датам,
  пассажирам, классу обслуживания, требованию прямого рейса и сортировке.
- `ozon_travel_hotels_search` ищет отели Ozon Travel по направлению, датам,
  гостям, комнатам, рейтингу, звёздам и максимальной полной стоимости.
- `ozon_travel_hotel_details` читает тарифы номеров одного отеля Ozon Travel на
  заданные даты.

В ответе по товару есть marketplace, название, URL, image URL, цена, старая цена, валюта, рейтинг, число отзывов, наличие, доставка, время парсинга и warnings, если данные неполные.

В авиапредложениях отдельно сохраняются сегменты, авиакомпании, пересадки,
длительность, багаж и показанная полная цена. У отелей `nightly_price` и
`total_price` намеренно разделены. Цена «от» из карточки поиска не выдаётся за
точную стоимость всего проживания: для точной суммы на даты нужны details и
тарифы номеров.

Цена перелёта остаётся неизвестной, если на странице нет всех запрошенных
направлений. Дата прилёта учитывает показанный сдвиг дня; неоднозначная дата
ночного рейса остаётся неизвестной. Цены отелей не подтверждаются при
несовпадении показанного года или невозможности разделить цены тарифов.
Питание, отмена и условия оплаты относятся к каждому тарифу отдельно,
в том числе когда у разных тарифов одинаковая цена.

Поиск пакетных туров Ozon и чтение деталей соблюдают общий cooldown.
Ошибки браузера, занятый запрос и CAPTCHA возвращаются как структурированные
диагностические данные с исходной ссылкой. После ручной проверки в сохранённой
вкладке её состояние можно прочитать через
`ozon_tours_access_status(inspect_tab=true)`.

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
Цены и наличие для поездок — тоже снимок на момент поиска. Перед бронированием
их нужно перепроверить; сервер не резервирует и не бронирует билеты или отели.

Marketplace MCP по умолчанию использует Hive Web как источник загрузки страниц (`MARKETPLACES_WEB_BACKEND=hive_web`).
Режим `legacy` оставляет прежний путь через Playwright/httpx.
Режим `auto` сначала пробует Hive Web, и использует legacy только если Hive Web недоступен.

- `MARKETPLACES_WEB_BACKEND`: `hive_web` (по умолчанию), `auto`, `legacy`
- `MARKETPLACES_HIVE_WEB_MAX_TOKENS`: максимальный размер снапшота видимого текста (по умолчанию `12000`)
- `MARKETPLACES_CAMOFOX_URL`: необязательный адрес Camofox для анонимных
  временных read-only сессий.
- `MARKETPLACES_AVITO_REGION_SLUG`: региональный path Авито, по умолчанию `all`.
- `MARKETPLACES_AVITO_STATE_PATH`: общий state-файл ограничения запросов Авито
  (по умолчанию `~/.cache/marketplaces-mcp/avito-access-state.json`).
- `MARKETPLACES_AVITO_MIN_INTERVAL_SECONDS`: интервал live-запросов, по
  умолчанию 10 секунд.
- `MARKETPLACES_AVITO_BLOCK_COOLDOWN_SECONDS`: cooldown после явного IP-block,
  по умолчанию 21600 секунд.

Индексный fallback возвращает только каноническую ссылку без проверенной цены
и предупреждения `INDEX_DISCOVERY_ONLY`/`PRICE_UNVERIFIED`. Сниппет поисковика
не считается актуальной карточкой. Авито не входит в обычный retail compare,
потому что каждое б/у объявление описывает уникальный физический экземпляр.

Runtime-настройки также можно хранить в `~/.config/marketplaces-mcp/config.json` или в пути из `MARKETPLACES_CONFIG`:

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

Для локальной разработки `scripts/camofox-bridge.py` поднимает небольшой Camofox-compatible read-only API, который используют адаптеры (`POST /tabs`, `GET /tabs/{tabId}/snapshot`, `DELETE /sessions/{userId}`), поверх Hive Web/Playwright:

```bash
uv run python scripts/camofox-bridge.py --host 127.0.0.1 --port 8765 --headful
```

После этого укажите `"camofox_url": "http://127.0.0.1:8765"` в runtime config.

Proxy применяется только к указанному маркетплейсу. Если для маркетплейса настроен proxy, adapter пропускает Hive Web для этого маркетплейса и использует proxied Playwright/httpx path. Для browser-heavy маркетплейсов используйте HTTP proxy с авторизацией: Chromium/Playwright не поддерживает authenticated SOCKS5 proxies. Переменные окружения имеют приоритет над файлом: `MARKETPLACES_PROXY_OZON_URL`, `MARKETPLACES_OZON_PROXY_URL`, `OZON_PROXY_URL`, `MARKETPLACES_PROXY_YANDEX_MARKET_URL`, `MARKETPLACES_YANDEX_MARKET_PROXY_URL`, `YANDEX_MARKET_PROXY_URL`.

Ozon рендерится с включённым JavaScript. Если для Ozon настроен proxy, адаптер держит Playwright в headful-режиме даже при `browser_headless=true`, потому что Ozon строже относится к headless. Отключать JavaScript как fallback бесполезно: Ozon возвращает anti-bot challenge с просьбой включить JavaScript, и adapter сообщает это как `CAPTCHA_OR_BLOCKED`.

Ozon Travel по умолчанию использует proxy-настройку Ozon. Индексный fallback
может найти канонические ссылки на рейсы и отели, но не выдумывает цену и
добавляет `INDEX_DISCOVERY_ONLY`, `PRICE_UNVERIFIED`, а для отелей ещё и
`DATE_AVAILABILITY_UNVERIFIED`.

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

Явные read-only canary для Ozon Travel:

```bash
uv run python scripts/smoke-travel.py flights MOW LED 2030-05-10
uv run python scripts/smoke-travel.py hotels "Сочи" 2030-05-10 2030-05-12
```

Live-поиск зависит от текущего поведения площадок. Ozon, Ozon Travel и Яндекс
Маркет могут включить rate limit, блокировку или поменять разметку. В таком
случае smoke test должен вернуть warning вроде `CAPTCHA_OR_BLOCKED`, а не
падать или выдумывать актуальную цену.

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

## Пакетные туры и диагностика доступа

`ozon_travel_tours_search` ищет настоящие пакеты Ozon, а
`ozon_travel_tour_details` проверяет номер, питание, оператора и цену на странице
отеля из той же выдачи. Для другого города вылета или страны выберите маршрут
в публичной форме Ozon и передайте скопированную ссылку поиска как `search_url`
в `ozon_travel_tours_search`. Ссылка задаёт всю поездку: вместе с ней можно
передать только `limit`. Полученный `source_url` и название отеля передаются
в `ozon_travel_tour_details`.

Сопоставление названий с идентификаторами пока знает только LED → ОАЭ.
Для других названий возвращается `OZON_TOURS_ROUTE_LOOKUP_REQUIRED` со ссылкой
на форму Ozon; подстановка знакомого маршрута и угадывание идентификаторов
не выполняются. Автоматический поиск остальных городов и стран ещё не реализован.
Общий разбор маршрутов и проверка контекста покрыты локальными тестами;
доступность живого Ozon зависит от окружения.

Оба способа ввода поддерживают один номер, точную дату вылета, 1–6 взрослых
и до трёх детей 0–16 лет; 0 означает младенца. Допустимы 2–21 ночь и до пяти
вариантов длительности за запрос: например, 5–9 и затем 10–12 ночей. Неполные,
противоречивые ссылки и неподдерживаемые фильтры поездки отклоняются, а известные
рекламные параметры удаляются. Поддерживаются существующие варианты фильтра
«всё включено»; для поиска всех типов питания не задавайте этот фильтр в форме
Ozon. Дополнительные фильтры курорта или отеля требуют отдельной поддержки.

Поисковая карточка даже с AI-фильтром может показывать завтраки, поэтому её
`total_price` неизвестна до details. Тариф тура с перелётом ещё требует выбора
рейсов: багаж, трансфер, дата обратного рейса и итоговая сумма не подтверждены.
`stay_end_date` означает окончание проживания. Бронирование не выполняется.

Нужен Camofox с рабочим display; проверены `CAMOFOX_INTERACTIVE=desktop` и
30-минутные таймауты неактивности вкладки/сессии. Закрытие старого context не
должно удалять заменившую его session. Вкладка сохраняется после таймаута
навигации, CAPTCHA требует ручного действия. `ozon_tours_access_status` по
умолчанию читает кэш, `inspect_tab=true` — открытую страницу без навигации;
явные probes соблюдают cooldown. `package_tours_search` использует отдельный
источник 1001tur и не выдаёт его результаты за Ozon.

`avito_access_status` сообщает состояние доступа и cooldown Авито;
`avito_game_search` различает картриджи, Game-Key Cards и цифровые предложения.
