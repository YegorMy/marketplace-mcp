# AGENTS.md

Проект `marketplaces_mcp` — read-only MCP сервер для поиска и сравнения товаров.

## Правила проекта
- Сервис работает только на чтение.  
  Запрещены любые операции с корзиной/заказом/оплатой/логином.
- При подозрении на CAPTCHA/робота/блокировку:
  - не предпринимать обхода,
  - вернуть предупреждение `CAPTCHA_OR_BLOCKED` и `search_url`,
  - завершить обработку с корректным структурированным ответом.
- Режим `fixture` обязателен для тестов и должен работать с локальными HTML-строками/файлами без сетевых запросов.
- Структура ответа обязана соответствовать моделям в `core/models.py`.
- Важные ошибки/исключения не должны ломать сервер: всегда возвращается warning + частичный ответ.

## Для себя и друзей
- Установка зависимостей и запуск через `uv`:
  - generic: `uv run python -m marketplaces_mcp`
  - absolute path (для этой машины): `/Users/yegormy/.local/bin/uv run python -m marketplaces_mcp`
- Запуск проверок:
  - `uv run pytest -q`
  - `uv run python scripts/test-mcp-client.py`
  - `uv run python scripts/smoke-search.py --query "бумага a4" --limit 2`
