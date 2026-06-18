FROM python:3.11-slim
WORKDIR /app

# ── Зависимости (кешируются отдельно от кода) ────────────────────────────────
COPY docker/pii_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# spaCy 3.8.x —────────────────────────────────────────────────────────────────
RUN pip install --no-cache-dir "spacy>=3.8.0,<3.9.0"

# curl нужен для healthcheck в docker-compose
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ── Код детектора ────────────────────────────────────────────────────────────
COPY pii_detector/ /app/pii_detector/

# ── Скачать модель с HF Hub  ─────────────────────────────────────────────────
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('alrosait/spacy_ru_core_news_lg_pii')"

# ── FastAPI приложение ───────────────────────────────────────────────────────
COPY docker/pii_service/main.py /app/main.py

ENV PYTHONPATH="/app"
ENV PII_SPACY_MODEL_PATH="alrosait/spacy_ru_core_news_lg_pii"

EXPOSE 5001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001"]
