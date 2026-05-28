FROM ghcr.io/berriai/litellm:main-stable

# Кастомный guardrail — тонкий HTTP-клиент
COPY docker/litellm/pii_guardrail.py /app/pii_guardrail.py

# Добавляем /app в PYTHONPATH чтобы LiteLLM нашёл pii_guardrail модуль
ENV PYTHONPATH="/app:${PYTHONPATH}"
