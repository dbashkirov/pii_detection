"""
Тонкий LiteLLM guardrail — политика PII-фильтрации.

Вся тяжёлая работа (детекция, маскировка) делается в pii-service.
Этот модуль только читает имя модели и вызывает нужный endpoint.

Режимы (определяются по имени модели в запросе):
  - содержит "mask"  → маскировать ПД перед отправкой в LLM
  - содержит "block" → отклонить запрос если ПД обнаружены
  - иначе            → пропустить без изменений
"""

import logging
import os

import httpx
from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pii_guardrail")

PII_SERVICE_URL = os.environ.get("PII_SERVICE_URL", "http://pii-service:5001")


class PIIGuardrail(CustomGuardrail):

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        model: str = data.get("model", "")

        if "block" in model:
            mode = "block"
        elif "mask" in model:
            mode = "mask"
        else:
            return data  # llama3.2 без суффикса — пропускаем

        messages = data.get("messages", [])

        # Индексы всех сообщений пользователя с непустым текстом
        user_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "user" and m.get("content")
        ]
        if not user_indices:
            return data

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:

                if mode == "mask":
                    # Маскируем ВСЮ историю пользователя, а не только последнее сообщение.
                    # Open WebUI отправляет полный контекст с оригинальными (немаскированными)
                    # предыдущими репликами — без этого ПД «просачиваются» через историю.
                    masked_count = 0
                    for idx in user_indices:
                        text: str = messages[idx]["content"]
                        resp = await client.post(
                            f"{PII_SERVICE_URL}/anonymize",
                            json={"text": text},
                        )
                        resp.raise_for_status()
                        masked: str = resp.json()["text"]
                        if masked != text:
                            masked_count += 1
                        data["messages"][idx]["content"] = masked
                    if masked_count:
                        logger.info(
                            f"PIIGuardrail [mask]: ПД замаскированы в {masked_count} "
                            f"из {len(user_indices)} сообщений истории"
                        )

                elif mode == "block":
                    # Проверяем только последнее сообщение пользователя:
                    # предыдущие уже прошли через block-фильтр в момент отправки.
                    idx = user_indices[-1]
                    text = messages[idx]["content"]
                    resp = await client.post(
                        f"{PII_SERVICE_URL}/analyze",
                        json={"text": text},
                    )
                    resp.raise_for_status()
                    findings = resp.json()
                    if findings:
                        entities = sorted({f["entity_type"] for f in findings})
                        logger.info(f"PIIGuardrail [block]: запрос заблокирован — {entities}")
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Запрос заблокирован: в сообщении обнаружены персональные данные "
                                f"({', '.join(entities)}). "
                                f"Пожалуйста, удалите чувствительную информацию и повторите запрос."
                            ),
                        )

        except HTTPException:
            raise  # пробрасываем блокировку — LiteLLM вернёт HTTP 400
        except Exception as exc:
            # fail-open: ошибка связи с pii-service не должна блокировать весь сервис
            logger.error(f"PIIGuardrail [{mode}]: не удалось связаться с pii-service: {exc}")

        return data


# LiteLLM при загрузке строки "pii_guardrail.guardrail" получает уже готовый
# экземпляр, а не класс — иначе методы вызываются без self и падают с TypeError
guardrail = PIIGuardrail()
