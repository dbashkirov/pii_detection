"""Guardrail LiteLLM: персональные данные не уходят в модель, а пользователь видит ответ с исходными.

Запрос: все тексты сообщений (история, system prompt, text-части, аргументы tool calls) одним
вызовом отправляются в pii-service /mask. Сервис заменяет ПД сквозными метками (одно значение —
одна метка во всём запросе), ФИО — псевдонимами в нужном падеже, и возвращает пары для обратной
замены. Найден тип с политикой BLOCK — запрос отклоняется (400). pii-service недоступен — запрос
тоже отклоняется (503): без проверки в модель ничего не уходит.

Ответ: исходные значения возвращаются в content, reasoning_content и аргументы tool calls. В стриме
чанки не копятся до конца ответа: придерживается только хвост, в котором может быть недописанная
замена (не длиннее самой длинной замены).

Пары замен хранятся только в памяти процесса LiteLLM (в метаданные запроса попадает лишь
непрозрачный идентификатор), поэтому исходные значения не попадают в логи и журналы расходов.

Подключение — docker/litellm_config.yaml:

    guardrails:
      - guardrail_name: pii
        litellm_params:
          guardrail: pii_guardrail.PIIGuardrail   # файл лежит рядом с конфигом
          mode: [pre_call, post_call]
          default_on: true
          pii_api_base: http://pii-service:5001
          pii_policy: {NAME: PSEUDONYMIZE, BANK_CARD_NUMBER: BLOCK, CVC: BLOCK, TOKEN: BLOCK}
"""
import re
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException

from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.types.guardrails import GuardrailEventHooks
from litellm.types.utils import Delta, ModelResponse, ModelResponseStream, StreamingChoices

CHAT_CALL_TYPES = {"completion", "acompletion"}
# Эндпоинты с текстом, которые guardrail не разбирает: по умолчанию такие запросы отклоняются,
# чтобы ПД не ушли в модель в обход проверки (pii_unsupported_call_types: allow — пропускать).
TEXT_CALL_TYPES = {
    "text_completion", "atext_completion", "responses", "aresponses", "anthropic_messages",
    "embedding", "aembedding", "moderation", "amoderation", "generate_content", "agenerate_content",
}
# Пример — метка из самого запроса: если модель процитирует подсказку, метка тоже восстановится.
PLACEHOLDER_HINT = (
    "Часть персональных данных в сообщениях заменена метками вида {example}. "
    "Если нужно упомянуть эти данные, пиши метки дословно, не изменяй и не расшифровывай их."
)
_METADATA_KEY = "pii_guardrail_ref"
_TTL_SECONDS = 3600


_SPACE_RE = re.compile(r"\s")


def _key_regex(key: str) -> str:
    # Границы слова только со стороны букв/цифр: «Денис» не должен сработать внутри «Денисов»,
    # а метка «<EMAIL_1>» может стоять вплотную к тексту. Пробел совпадает с любым одним пробельным
    # символом: модели пишут «Тарасова\u202fА.\u202fА.» (узкий неразрывный пробел).
    body = r"\s".join(re.escape(part) for part in key.split(" "))
    return (r"(?<!\w)" if key[0].isalnum() else "") + body + (r"(?!\w)" if key[-1].isalnum() else "")


def _norm(text: str) -> str:
    return _SPACE_RE.sub(" ", text)


class Restorer:
    """Обратная замена: псевдонимы и метки → исходные значения."""

    def __init__(self, pairs: List[List[str]]):
        self.map: Dict[str, str] = {}
        for replacement, original in pairs:
            self.map.setdefault(replacement, original)
        keys = sorted(self.map, key=len, reverse=True)  # длинные первыми: «Денис Андреевич» раньше «Денис»
        self.max_len = len(keys[0]) if keys else 0
        self.pattern = re.compile("|".join(_key_regex(k) for k in keys)) if keys else None

    def restore(self, text: Optional[str]) -> Optional[str]:
        if not text or self.pattern is None:
            return text
        return self.pattern.sub(lambda m: self.map[_norm(m.group(0))], text)

    def stream(self) -> "StreamRestorer":
        return StreamRestorer(self)


class StreamRestorer:
    """Обратная замена в потоке: отдаёт всё, кроме хвоста, где может быть недописанная замена."""

    def __init__(self, restorer: Restorer):
        self.r = restorer
        self.buf = ""
        self.prev = ""  # последний отданный символ исходного текста — для проверки границы слова

    def _emit(self, until: Optional[int]) -> str:
        text, off = self.prev + self.buf, len(self.prev)
        limit = len(text) if until is None else off + until
        out, pos = [], off
        for m in self.r.pattern.finditer(text, off):
            if m.start() >= limit:
                break
            out += [text[pos:m.start()], self.r.map[_norm(m.group(0))]]
            pos = m.end()  # совпадение, начатое до limit, целиком в буфере (буфер длиннее любой замены)
        end = max(limit, pos)
        out.append(text[pos:end])
        self.prev, self.buf = text[end - 1:end] if end > off else self.prev, text[end:]
        return "".join(out)

    def feed(self, chunk: Optional[str]) -> Optional[str]:
        if not chunk or self.r.pattern is None:
            return chunk
        self.buf += chunk
        safe = len(self.buf) - (self.r.max_len + 1)  # +1: символ после замены нужен для границы слова
        return self._emit(safe) if safe > 0 else ""

    def flush(self) -> str:
        if not self.buf or self.r.pattern is None:
            rest, self.buf = self.buf, ""
            return rest
        return self._emit(None)


def _text_slots(messages: List[dict]):
    """Все строки сообщений, которые уходят в модель: (получить, записать)."""
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            yield (lambda m=m: m["content"]), (lambda v, m=m: m.__setitem__("content", v))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                    yield (lambda p=part: p["text"]), (lambda v, p=part: p.__setitem__("text", v))
        for call in m.get("tool_calls") or []:
            fn = call.get("function") if isinstance(call, dict) else None
            if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
                yield (lambda f=fn: f["arguments"]), (lambda v, f=fn: f.__setitem__("arguments", v))


def _add_hint(messages: List[dict], example: str) -> None:
    hint = PLACEHOLDER_HINT.format(example=example)
    first = messages[0] if messages else None
    if isinstance(first, dict) and first.get("role") == "system":
        if isinstance(first.get("content"), str):
            first["content"] = f"{first['content']}\n\n{hint}"
            return
        if isinstance(first.get("content"), list):
            first["content"].append({"type": "text", "text": hint})
            return
    messages.insert(0, {"role": "system", "content": hint})


class PIIGuardrail(CustomGuardrail):
    def __init__(
            self,
            pii_api_base: str = "http://pii-service:5001",
            pii_policy: Optional[Dict[str, str]] = None,
            pii_score_thresholds: Optional[Dict[str, float]] = None,
            pii_allow_list: Optional[List[str]] = None,
            pii_timeout: float = 10.0,
            pii_placeholder_hint: bool = True,
            pii_unsupported_call_types: str = "block",
            **kwargs,
    ):
        self.pii_api_base = pii_api_base.rstrip("/")
        self.pii_policy = pii_policy or {}
        self.pii_score_thresholds = pii_score_thresholds
        self.pii_allow_list = pii_allow_list or []
        self.pii_timeout = float(pii_timeout)
        self.pii_placeholder_hint = pii_placeholder_hint
        self.pii_unsupported_call_types = pii_unsupported_call_types
        self._client: Optional[httpx.AsyncClient] = None
        self._restorers: Dict[str, Tuple[float, Restorer]] = {}
        kwargs.setdefault("supported_event_hooks", [GuardrailEventHooks.pre_call, GuardrailEventHooks.post_call])
        super().__init__(**kwargs)

    # ── хранение пар замен между хуками одного запроса ───────────────────────

    def _put(self, restorer: Restorer) -> str:
        now = time.monotonic()
        for ref in [r for r, (t, _) in self._restorers.items() if now - t > _TTL_SECONDS]:
            self._restorers.pop(ref, None)
        ref = uuid.uuid4().hex
        self._restorers[ref] = (now, restorer)
        return ref

    @staticmethod
    def _ref(data: Optional[dict]) -> Optional[str]:
        for key in ("metadata", "litellm_metadata"):
            meta = (data or {}).get(key)
            if isinstance(meta, dict) and meta.get(_METADATA_KEY):
                return meta[_METADATA_KEY]
        return None

    def _get(self, data: Optional[dict]) -> Optional[Restorer]:
        entry = self._restorers.get(self._ref(data) or "")
        return entry[1] if entry else None

    def _drop(self, data: Optional[dict]) -> None:
        self._restorers.pop(self._ref(data) or "", None)

    # ── pii-service ──────────────────────────────────────────────────────────

    async def _mask(self, texts: List[str]) -> dict:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.pii_timeout, connect=2.0))
        try:
            response = await self._client.post(f"{self.pii_api_base}/mask", json={
                "texts": texts,
                "policy": self.pii_policy,
                "score_thresholds": self.pii_score_thresholds,
                "allow_list": self.pii_allow_list,
            })
            response.raise_for_status()
            return response.json()
        except Exception as e:
            # Текст исключения может содержать тело запроса — пишем только тип.
            verbose_proxy_logger.error("PII guardrail: pii-service недоступен (%s)", type(e).__name__)
            raise HTTPException(status_code=503, detail={
                "error": "Сервис проверки персональных данных недоступен, запрос не отправлен в модель"})

    # ── хуки LiteLLM ─────────────────────────────────────────────────────────

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type: str):
        if call_type not in CHAT_CALL_TYPES:
            if call_type in TEXT_CALL_TYPES and self.pii_unsupported_call_types == "block":
                raise HTTPException(status_code=400, detail={
                    "error": f"PII guardrail: запросы {call_type} не проверяются на персональные данные и отклонены"})
            return data

        messages = data.get("messages") or []
        slots = list(_text_slots(messages))
        texts = [get() for get, _ in slots]
        if not any(t.strip() for t in texts):
            return data

        start = time.time()
        result = await self._mask(texts)
        entities = result.get("entities") or {}
        if result.get("blocked"):
            self.add_standard_logging_guardrail_information_to_request_data(
                guardrail_json_response={"blocked": result["blocked"]}, request_data=data,
                guardrail_status="guardrail_intervened", start_time=start, end_time=time.time(),
                masked_entity_count=entities, guardrail_provider="pii_service",
                event_type=GuardrailEventHooks.pre_call)
            raise HTTPException(status_code=400, detail={
                "error": "Запрос содержит данные, которые нельзя отправлять в модель: " + ", ".join(result["blocked"])})

        if result.get("restore"):
            for (_, set_text), text in zip(slots, result["texts"]):
                set_text(text)
            example = next((r for r, _ in result["restore"] if r.startswith("<")), None)
            if self.pii_placeholder_hint and example:
                _add_hint(messages, example)
            meta_key = "litellm_metadata" if "litellm_metadata" in data and "metadata" not in data else "metadata"
            data.setdefault(meta_key, {})[_METADATA_KEY] = self._put(Restorer(result["restore"]))

        self.add_standard_logging_guardrail_information_to_request_data(
            guardrail_json_response={"entities": entities}, request_data=data,
            guardrail_status="success", start_time=start, end_time=time.time(),
            masked_entity_count=entities, guardrail_provider="pii_service",
            event_type=GuardrailEventHooks.pre_call)
        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        restorer = self._get(data)
        if restorer is None or not isinstance(response, ModelResponse):
            return response
        for choice in response.choices:
            message = getattr(choice, "message", None)
            if message is None:
                continue
            if isinstance(message.content, str):
                message.content = restorer.restore(message.content)
            if isinstance(getattr(message, "reasoning_content", None), str):
                message.reasoning_content = restorer.restore(message.reasoning_content)
            for call in getattr(message, "tool_calls", None) or []:
                if call.function is not None and isinstance(call.function.arguments, str):
                    call.function.arguments = restorer.restore(call.function.arguments)
        self._drop(data)
        return response

    async def async_post_call_failure_hook(self, request_data: dict, original_exception, user_api_key_dict, traceback_str=None):
        self._drop(request_data)

    async def async_post_call_streaming_iterator_hook(
            self, user_api_key_dict, response: Any, request_data: dict,
    ) -> AsyncGenerator[Any, None]:
        restorer = self._get(request_data)
        if restorer is None:
            async for chunk in response:
                yield chunk
            return

        streams: Dict[tuple, StreamRestorer] = {}
        last: Optional[ModelResponseStream] = None
        try:
            async for chunk in response:
                if isinstance(chunk, ModelResponseStream):
                    self._restore_chunk(chunk, restorer, streams)
                    last = chunk
                yield chunk
            tail = self._tail_chunk(streams, last)
            if tail is not None:
                yield tail
        finally:
            self._drop(request_data)

    @staticmethod
    def _restore_chunk(chunk: ModelResponseStream, restorer: Restorer, streams: Dict[tuple, StreamRestorer]) -> None:
        for choice in chunk.choices:
            idx, delta = choice.index, choice.delta
            if delta is None:
                continue
            if delta.content:
                delta.content = streams.setdefault((idx, "content"), restorer.stream()).feed(delta.content)
            if getattr(delta, "reasoning_content", None):
                delta.reasoning_content = streams.setdefault((idx, "reasoning"), restorer.stream()).feed(delta.reasoning_content)
            for call in delta.tool_calls or []:
                if call.function is not None and call.function.arguments:
                    key = (idx, "tool", call.index)
                    call.function.arguments = streams.setdefault(key, restorer.stream()).feed(call.function.arguments)
            if choice.finish_reason:
                PIIGuardrail._flush_into(delta, idx, streams)

    @staticmethod
    def _flush_into(delta: Delta, idx: int, streams: Dict[tuple, StreamRestorer]) -> bool:
        """Дописывает придержанные хвосты choice idx в delta. -> было ли что дописать."""
        wrote = False
        for key, stream in list(streams.items()):
            if key[0] != idx:
                continue
            rest = stream.flush()
            del streams[key]
            if not rest:
                continue
            wrote = True
            if key[1] == "content":
                delta.content = (delta.content or "") + rest
            elif key[1] == "reasoning":
                delta.reasoning_content = (getattr(delta, "reasoning_content", None) or "") + rest
            else:
                extra = Delta(tool_calls=[{"index": key[2], "type": "function", "function": {"arguments": rest}}])
                delta.tool_calls = (delta.tool_calls or []) + list(extra.tool_calls)
        return wrote

    @staticmethod
    def _tail_chunk(streams: Dict[tuple, StreamRestorer], last: Optional[ModelResponseStream]):
        """Стрим закончился без finish_reason — остаток отдаётся отдельным чанком."""
        if not streams or last is None:
            return None
        choices = []
        for idx in sorted({k[0] for k in streams}):
            delta = Delta(content=None)
            if PIIGuardrail._flush_into(delta, idx, streams):
                choices.append(StreamingChoices(index=idx, delta=delta, finish_reason=None))
        if not choices:
            return None
        return ModelResponseStream(id=last.id, model=last.model, created=last.created, choices=choices)
