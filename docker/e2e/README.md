# e2e-проверка PII-guardrail

Тест-кейсы прогоняются через настоящий LiteLLM. Вместо модели — заглушка (`mock_upstream.py`),
которая записывает в `log/<стенд>/upstream.jsonl` всё, что LiteLLM отправил «в модель», и отвечает
эхом. Так видно и что ушло наружу, и что вернулось пользователю. Результаты — в
[`docs/litellm_guardrail.md`](../../docs/litellm_guardrail.md).

«Было» (встроенный guardrail `presidio` + pii-service из `master`) и «стало» (`pii_guardrail.py` +
`/mask`) поднимаются рядом:

```bash
cd docker/e2e

# образ pii-service этой ветки; для «было» — собрать то же из master и назвать pii-service:before
docker build -f ../pii_service/Dockerfile -t pii-service:e2e ../..

E2E_CONFIG=litellm_before.yaml PII_IMAGE=pii-service:before LITELLM_PORT=24000 PII_PORT=25001 \
  E2E_LOG_DIR=./log/before docker compose -p pii-before up -d --no-build
E2E_CONFIG=litellm_after.yaml PII_IMAGE=pii-service:e2e LITELLM_PORT=34000 PII_PORT=35001 \
  E2E_LOG_DIR=./log/after docker compose -p pii-after up -d --no-build

python3 run_cases.py run --label before --litellm http://127.0.0.1:24000 --pii http://127.0.0.1:25001 \
  --log log/before/upstream.jsonl --project pii-before --out results/before.json
python3 run_cases.py run --label after --litellm http://127.0.0.1:34000 --pii http://127.0.0.1:35001 \
  --log log/after/upstream.jsonl --project pii-after --out results/after.json
python3 run_cases.py report results/before.json results/after.json
```

`--project` нужен кейсам, которые останавливают pii-service (TC-14) и читают журнал LiteLLM и логи
контейнеров (TC-15). Версия LiteLLM — `LITELLM_IMAGE` (по умолчанию `v1.100.1`).

## Настоящие модели

Кейсы с падежами и временем рассуждений (`--real-models`) нужны настоящие модели. Добавьте их в копию
конфига, ключ передайте через окружение:

```yaml
  - model_name: qwen3.6-35b-a3b
    litellm_params: {model: openai/<id модели>, api_base: os.environ/REAL_API_BASE, api_key: os.environ/REAL_API_KEY}
```

```bash
REAL_API_BASE=https://... REAL_API_KEY=... E2E_CONFIG=local/after_real.yaml ... docker compose -p pii-after up -d
python3 run_cases.py run ... --only NONE --real-models qwen3.6-35b-a3b,gpt-oss-120b --real-repeat 2 --out results/after_real.json
```

Каталог `local/` в git не попадает.

## Юнит-тесты

```bash
pytest tests/test_masking.py                        # нужны presidio-analyzer и pymorphy3
docker compose -p pii-after exec -T -e PII_GUARDRAIL=/app/pii_guardrail.py litellm \
  python - < ../../tests/test_guardrail_restore.py      # нужен litellm — запускаем в его контейнере
```
