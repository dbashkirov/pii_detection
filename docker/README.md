# PII Detector — локальный стенд с LLM и фильтрацией персональных данных

Изолированная инфраструктура для тестирования политик обработки персональных данных в диалоге с языковой моделью. Все компоненты работают локально — ни запросы, ни данные не покидают машину.

## Как это устроено

```
[Open WebUI  :3000]  ──►  [LiteLLM  :4000]  ──►  [Ollama  :11434]
                                  │
                           [PII Guardrail]
                                  │ HTTP
                          [pii-service  :5001]
                          HybridPIIDetector
                          (Presidio + spaCy NER)
```

Пользователь общается с моделью через браузерный интерфейс Open WebUI. Все сообщения проходят через LiteLLM-прокси, где к ним применяется guardrail: запрос уходит в `pii-service`, который на базе Presidio и дообученной spaCy-модели находит персональные данные. Дальнейшее поведение зависит от выбранной политики.

### Сервисы

| Сервис | Роль |
|---|---|
| **Open WebUI** | Браузерный чат-интерфейс |
| **LiteLLM** | OpenAI-совместимый прокси с PII-guardrail |
| **pii-service** | FastAPI-обёртка над `HybridPIIDetector`; детекция и маскировка ПД |
| **Ollama** | Локальный LLM-сервер (`llama3.2`) |
| **PostgreSQL** | База данных для LiteLLM UI (логи, ключи) |

### Политики фильтрации

Политика выбирается через выпадающий список моделей в Open WebUI:

| Модель | Политика |
|---|---|
| `llama3.2` | Без фильтрации — сообщения передаются как есть |
| `llama3.2-mask` | ПД заменяются на типизированные теги: `Иван Петров` → `<NAME>` |
| `llama3.2-block` | Запросы с ПД отклоняются (HTTP 400) |

Обнаруживаемые типы сущностей: `NAME`, `ADDRESS`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `INN`, `SNILS`, `OGRN`, `OGRNIP`, `KPP`, `PASSPORT_NUMBER`, `BANK_CARD_NUMBER`, `CVC`, `TOKEN`.

---

## Требования

- Docker Desktop с Compose V2
- ~12 ГБ свободного места (образы ≈ 4 ГБ · llama3.2 ≈ 2 ГБ · spaCy-модель ≈ 638 МБ)
- RAM: минимум 8 ГБ, рекомендуется 16 ГБ

---

## Запуск

### 1. Конфигурация секретов

Рабочий конфигурационный файл создаётся на основе шаблона:

```bash
cp .env.example .env
```

В `.env` нужно заполнить три значения:

```env
# Мастер-ключ LiteLLM — обязательно с префиксом sk-
# Сгенерировать: echo "sk-$(openssl rand -hex 32)"
LITELLM_MASTER_KEY=sk-...

# Учётные данные для входа в LiteLLM UI
UI_USERNAME=admin
UI_PASSWORD=...

# Пароль PostgreSQL (используется только внутри сети Docker)
# Сгенерировать: openssl rand -hex 16
POSTGRES_PASSWORD=...
```

> **Важно:** `LITELLM_MASTER_KEY` должен начинаться с `sk-` — без этого префикса LiteLLM отвергает ключ и авторизация не работает.

### 2. Запуск стека

Из папки `docker/`:

```bash
docker compose up --build -d
```

Из корня проекта:

```bash
docker compose -f docker/docker-compose.yml --env-file docker/.env up --build -d
```

Первая сборка занимает 10–20 минут: установка зависимостей, копирование spaCy-модели (638 МБ), загрузка llama3.2 (~2 ГБ, однократно).

### 3. Проверка готовности

```bash
# Детектор готов, когда в логах появляется "HybridPIIDetector готов ✓"
docker logs -f pii_service

# Модель llama3.2 загружена, когда появляется ">>> llama3.2 готова <<<"
docker logs -f pii_ollama_init
```

После этого все сервисы операционны.

---

## Интерфейсы

| Сервис | Адрес | Описание |
|---|---|---|
| **Open WebUI** | http://localhost:3000 | Основной чат-интерфейс |
| **LiteLLM UI** | http://localhost:4000/ui | Дашборд прокси — логи запросов, управление ключами |
| **LiteLLM API** | http://localhost:4000 | OpenAI-совместимый REST API |
| **pii-service** | http://localhost:5001/docs | Swagger UI — интерактивные `/analyze` и `/anonymize` |
| **Ollama** | http://localhost:11434/api/tags | REST API Ollama — список установленных моделей |

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

# Маскировка
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

# Политика mask — LLM получит <NAME> и <PHONE_NUMBER> вместо реальных данных
curl -s -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2-mask",
    "messages": [{"role": "user", "content": "Меня зовут Иван Петров, мой телефон +7 916 123 45 67"}]
  }' | python3 -m json.tool

# Политика block — ожидаемый ответ HTTP 400
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2-block",
    "messages": [{"role": "user", "content": "Мой email: test@example.com"}]
  }'

# Лог guardrail
docker logs pii_litellm | grep PIIGuardrail
```

---

## Управление стеком

```bash
# Остановить без удаления контейнеров и данных
docker compose stop

# Поднять остановленный стек без пересборки
docker compose start

# Остановить и удалить контейнеры (тома с данными сохраняются)
docker compose down

# Полный сброс включая тома (модели Ollama, история чата, БД)
docker compose down -v

# Пересобрать pii-service после изменений в pii_detector/
docker compose up --build -d pii-service

# Пересобрать litellm после изменений в pii_guardrail.py
docker compose up --build -d litellm

# Мониторинг ресурсов
docker stats pii_service pii_litellm pii_ollama pii_openwebui
```