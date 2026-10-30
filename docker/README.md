# Тестовый стенд с LLM и фильтрацией персональных данных

Локальный стенд для тестирования политик обработки ПД в диалоге с языковой моделью. Все компоненты работают на машине — запросы и данные не покидают окружение.

## Архитектура

```
[Open WebUI  :3000]  ──►  [LiteLLM  :4000]  ──►  [Ollama  :11434]
                                  │
                    [PII-guardrail pii_guardrail.py]
                    (litellm/pii_guardrail.py)
                                  │ HTTP  POST /mask
                          [pii-service  :5001]
                          HybridPIIDetector
                          (Presidio + spaCy NER)
```

| Сервис          | Роль                                                                 |
|-----------------|----------------------------------------------------------------------|
| **Open WebUI**  | Браузерный чат-интерфейс                                             |
| **LiteLLM**     | OpenAI-совместимый прокси с PII-guardrail (`litellm/pii_guardrail.py`) |
| **pii-service** | FastAPI-обёртка над `HybridPIIDetector`: `/mask` для guardrail, Presidio REST API (`/analyze`, `/anonymize`) |
| **Ollama**      | Локальный LLM-сервер (`gemma3:4b`)                                   |
| **PostgreSQL**  | База данных LiteLLM UI — логи запросов, управление ключами           |

### Политика фильтрации

Задаётся в `docker/litellm_config.yaml` до запуска. Одна модель `gemma3:4b`, guardrail всегда активен.

| Значение  | Поведение                                                                                                                                                                                                   |
|-----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `"PSEUDONYMIZE"` | Только `NAME`: ФИО заменяется правдоподобным ФИО того же рода и в том же падеже: `Петрову Ивану Сергеевичу` → `Тарасову Денису Андреевичу`. Модель пишет грамматичный текст, в ответе возвращается исходное ФИО в нужном падеже: «Уважаемый Денис Андреевич» → «Уважаемый Иван Сергеевич». Если упоминание не разбирается как русское ФИО — как `MASK`. |
| `"MASK"`  | ПД заменяются метками до отправки в LLM: `test@example.com` → `<EMAIL_1>`. LLM отвечает с метками, LiteLLM подставляет исходные значения обратно перед возвратом ответа пользователю. |
| `"BLOCK"` | Запросы с ПД отклоняются (HTTP 400).                                                                                                                                                                        |
| `"ALLOW"` | Тип не обрабатывается.                                                                                                                                                                                      |

Каждый тип сущности настраивается независимо в `pii_policy`, не указанные типы — `MASK`. Чтобы переключить все в режим блокировки — заменить значения на `"BLOCK"` в `litellm_config.yaml` и выполнить `docker compose restart litellm` (пересборка не нужна — файл смонтирован томом).

Замены сквозные на весь запрос: одно значение получает одну метку (или один псевдоним) во всей истории чата, разные — разные. Если значение найдено хоть в одном месте запроса, заменяются и остальные его вхождения, даже те, что пропустил NER. Исходные значения восстанавливаются в `content`, `reasoning_content` и аргументах tool calls, в том числе в стриме — без ожидания конца ответа. Если pii-service недоступен, запрос отклоняется (HTTP 503), а не уходит в модель без проверки. Сравнение со встроенным guardrail `presidio` LiteLLM — [`docs/litellm_guardrail.md`](../docs/litellm_guardrail.md).

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
| **pii-service** | http://localhost:5001/docs      | Swagger UI — `/mask`, `/analyze` и `/anonymize`      |
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

# Маскирование текстов одного запроса (так работает guardrail): сквозные метки, псевдонимы ФИО
# и пары для обратной замены
curl -s -X POST http://localhost:5001/mask \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Руководитель — Сидорова Анна Викторовна.", "Позвоните Сидоровой на test@example.com"]}' \
  | python3 -m json.tool

# Анонимизация — возвращает text + items (формат Presidio)
curl -s -X POST http://localhost:5001/anonymize \
  -H "Content-Type: application/json" \
  -d '{"text": "Email: test@example.com, СНИЛС 112-233-445 95"}' \
  | python3 -m json.tool
```

### Длинные тексты и память

Память spaCy и Presidio растёт с длиной анализируемого текста: без нарезки текст в 1 млн символов
занимает ~3,8 ГБ (в покое ~1 ГБ). Поэтому тексты длиннее `PII_CHUNK_CHARS` анализируются кусками
по границе абзаца, строки или предложения, каждый — с перекрытием `PII_CHUNK_OVERLAP` символов
контекста с обеих сторон; сущности на стыках склеиваются, результат тот же, что и целиком
(`pii_detector/chunking.py`, `tests/test_chunking.py`). Пик памяти от длины запроса не зависит:
1 млн символов — ~1,1 ГБ.

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `PII_CHUNK_CHARS` | 20000 | Длина куска, символов |
| `PII_CHUNK_OVERLAP` | 1000 | Перекрытие с каждой стороны, символов |
| `PII_MAX_PARALLEL` | 2 | Сколько кусков анализируется одновременно во всех запросах |
| `PII_MAX_TEXT_CHARS` | 2000000 | Больше (суммарно по текстам запроса) — 413 без анализа |

`/mask` принимает `timeout` — сколько секунд клиент ждёт ответа (guardrail передаёт `pii_timeout`).
Не уложились — 504, и сервис бросает работу, а не считает впустую после таймаута клиента.

### Сквозной тест через LiteLLM

```bash
KEY=<значение LITELLM_MASTER_KEY из .env>

# Список доступных моделей
curl -s -H "Authorization: Bearer $KEY" \
  http://localhost:4000/v1/models | python3 -m json.tool

# LLM видит псевдоним вместо имени и <PHONE_NUMBER_1> вместо телефона, пользователь — исходные значения
curl -s -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma3:4b",
    "messages": [{"role": "user", "content": "Меня зовут Иван Петров, мой телефон +7 916 123 45 67"}]
  }' | python3 -m json.tool

# Режим BLOCK (если в pii_policy задано EMAIL: "BLOCK") — ожидаемый ответ HTTP 400
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma3:4b",
    "messages": [{"role": "user", "content": "Мой email: test@example.com"}]
  }'

# Ошибки guardrail в логах (сколько сущностей найдено — в LiteLLM UI, логи запросов → guardrail)
docker logs pii_litellm | grep -i "PII guardrail"
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

# Обновить LiteLLM: сменить тег образа в docker-compose.yml, прогнать e2e-кейсы (docker/e2e/README.md)
docker compose up -d litellm

# Пересобрать pii-service после изменений в pii_detector/
docker compose up --build -d pii-service

# Мониторинг ресурсов
docker stats pii_service pii_litellm pii_ollama pii_openwebui
```