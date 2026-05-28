FROM python:3.11-slim
WORKDIR /app

# ── Зависимости (кешируются отдельно от кода) ────────────────────────────────
COPY docker/pii_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# spaCy 3.8.x — строго по meta.json модели (требует >=3.8.0,<3.9.0)
RUN pip install --no-cache-dir "spacy>=3.8.0,<3.9.0"

# curl нужен для healthcheck в docker-compose
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ── Код детектора ────────────────────────────────────────────────────────────
COPY pii_detector/ /app/pii_detector/

# ── Обученная модель (тяжёлый слой, меняется редко → кешируется) ───
COPY ft_spacy/model-best-combo-0.78/ /app/model-best-combo-0.78/

# ── FastAPI приложение ───────────────────────────────────────────────────────
COPY docker/pii_service/main.py /app/main.py

ENV PYTHONPATH="/app"
ENV PII_SPACY_MODEL_PATH="/app/model-best-combo-0.78"

EXPOSE 5001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001"]
