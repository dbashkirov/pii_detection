# Тестовый стенд с LLM и фильтрацией персональных данных

Локальный стенд для тестирования политик обработки ПД в диалоге с языковой моделью. Все компоненты работают на машине — запросы и данные не покидают окружение.

## Архитектура

```
[Open WebUI  :3000]  ──►  [LiteLLM  :4000]  ──►  [Ollama  :11434]
                                  │
                    [нативный Presidio guardrail]
                    (встроен в LiteLLM)
                                  │ HTTP  (Presidio REST API)
                          [pii-service  :5001]
                          HybridPIIDetector
                          (Presidio + spaCy NER)
```

| Сервис          | Роль                                                                 |
|-----------------|----------------------------------------------------------------------|
| **Open WebUI**  | Браузерный чат-интерфейс                                             |
| **LiteLLM**     | OpenAI-совместимый прокси с нативным Presidio PII-guardrail          |
| **pii-service** | FastAPI-обёртка над `HybridPIIDetector`, реализует Presidio REST API |
| **Ollama**      | Локальный LLM-сервер (`gemma3:4b`)                                   |
| **PostgreSQL**  | База данных LiteLLM UI — логи запросов, управление ключами           |

### Политика фильтрации

Задаётся в `docker/litellm_config.yaml` до запуска. Одна модель `gemma3:4b`, guardrail всегда активен.

| Значение  | Поведение                                                                                                                                                                                                   |
|-----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `"MASK"`  | ПД заменяются нумерованными плейсхолдерами до отправки в LLM: `Иван Петров` → `<NAME_1>`. LLM отвечает с плейсхолдерами, LiteLLM подставляет исходные значения обратно перед возвратом ответа пользователю. |
| `"BLOCK"` | Запросы с ПД отклоняются (HTTP 400).                                                                                                                                                                        |

Каждый тип сущности настраивается независимо в `pii_entities_config`. Чтобы переключить все в режим блокировки — заменить все `"MASK"` на `"BLOCK"` в `config.yaml` и выполнить `docker compose restart litellm` (пересборка не нужна — файл смонтирован томом).

Обнаруживаемые типы: `NAME`, `ADDRESS`, `PHONE_NUMBER`, `EMAIL`, `INN`, `SNILS`, `OGRN`, `OGRNIP`, `KPP`, `PASSPORT_NUMBER`, `BANK_CARD_NUMBER`, `CVC`, `TOKEN`.

---

## Требования

- Docker Desktop с Compose V2
- ~13 ГБ свободного места (образы ≈ 4 ГБ · gemma3:4b ≈ 3.3 ГБ · spaCy-модель ≈ 638 МБ)
- RAM: минимум 8 ГБ, рекомендуется 16 ГБ

---

## Запуск

### 1. Настройка секретов

```bash
cp .env.example .env
```

Отредактировать `.env`:

```env
# Должен начинаться с "sk-"
# Сгенерировать: echo "sk-$(openssl rand -hex 32)"
LITELLM_MASTER_KEY=sk-...

UI_USERNAME=admin
UI_PASSWORD=...

# Сгенерировать: openssl rand -hex 16
POSTGRES_PASSWORD=...
```

### 2. Настройка политики фильтрации

Открыть `docker/litellm_config.yaml` и выставить нужные значения в `pii_entities_config` (`"MASK"` или `"BLOCK"`). По умолчанию всё в режиме `"MASK"`.

### 3. Запуск стека

Из папки `docker/`:

```bash
docker compose up --build -d
```

Из корня проекта:

```bash
docker compose -f docker/docker-compose.yml --env-file docker/.env up --build -d
```

Первая сборка занимает 10–20 минут: установка зависимостей, копирование spaCy-модели (638 МБ), загрузка gemma3:4b (~3.3 ГБ, однократно).

### 4. Проверка готовности

```bash
# Детектор готов, когда появляется "HybridPIIDetector готов ✓"
docker logs -f pii_service

# Модель загружена, когда появляется ">>> gemma3:4b готова <<<"  (только первый запуск)
docker logs -f pii_ollama_init
```

---

## Интерфейсы

| Сервис          | Адрес                           | Описание                                             |
|-----------------|---------------------------------|------------------------------------------------------|
| **Open WebUI**  | http://localhost:3000           | Основной чат-интерфейс                               |
| **LiteLLM UI**  | http://localhost:4000/ui        | Дашборд прокси — логи запросов, управление ключами   |
| **LiteLLM API** | http://localhost:4000           | OpenAI-совместимый REST API                          |
| **pii-service** | http://localhost:5001/docs      | Swagger UI — интерактивные `/analyze` и `/anonymize` |
| **Ollama**      | http://localhost:11434/api/tags | REST API Ollama — список установленных моделей       |

---

## Проверка работоспособности

### Состояние сервисов

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Все сервисы кроме `pii_ollama_init` должны иметь статус `(healthy)`.

### Прямое обращение к pii-service

```bash
# Liveness
curl http://localhost:5001/health

# Детекция сущностей
curl -s -X POST http://localhost:5001/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "Меня зовут Иван Петров, ИНН 500100732259, тел. +7 916 123 45 67"}' \
  | python3 -m json.tool

# Анонимизация — возвращает text + items (формат Presidio)
curl -s -X POST http://localhost:5001/anonymize \
  -H "Content-Type: application/json" \
  -d '{"text": "Email: test@example.com, СНИЛС 112-233-445 95"}' \
  | python3 -m json.tool
```

### Сквозной тест через LiteLLM

```bash
KEY=<значение LITELLM_MASTER_KEY из .env>

# Список доступных моделей
curl -s -H "Authorization: Bearer $KEY" \
  http://localhost:4000/v1/models | python3 -m json.tool

# Режим MASK — LLM видит <NAME_1>, пользователь получает исходное имя (deanonymization)
curl -s -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma3:4b",
    "messages": [{"role": "user", "content": "Меня зовут Иван Петров, мой телефон +7 916 123 45 67"}]
  }' | python3 -m json.tool

# Режим BLOCK — ожидаемый ответ HTTP 400
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma3:4b",
    "messages": [{"role": "user", "content": "Мой email: test@example.com"}]
  }'

# Активность guardrail в логах
docker logs pii_litellm | grep -i presidio
```

---

## Управление стендом

```bash
# Остановить без удаления данных
docker compose down

# Остановить и удалить все тома (модели Ollama, история чата, БД)
docker compose down -v

# Сменить политику фильтрации (без пересборки)
# 1. Изменить значения в docker/litellm_config.yaml
# 2. Перезапустить только litellm:
docker compose restart litellm

# Обновить LiteLLM до последней версии
docker compose pull litellm && docker compose up -d litellm

# Пересобрать pii-service после изменений в pii_detector/
docker compose up --build -d pii-service

# Мониторинг ресурсов
docker stats pii_service pii_litellm pii_ollama pii_openwebui
```