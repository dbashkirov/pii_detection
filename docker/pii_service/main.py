import os
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("pii-service")


# ── Схемы запросов и ответов ─────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text: str
    language: str = "en"
    score_threshold: Optional[float] = None
    entities: Optional[List[str]] = None
    # LiteLLM может слать дополнительные поля (ad_hoc_recognizers, correlation_id и др.)
    model_config = ConfigDict(extra="allow")


class EntityResult(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float


class AnalyzerResultItem(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float = 0.0


class OperatorResultItem(BaseModel):
    operator: str
    entity_type: str
    start: int
    end: int
    text: str  # плейсхолдер в анонимизированном тексте, напр. "<NAME>"


class AnonymizeRequest(BaseModel):
    text: str
    language: str = "en"
    # LiteLLM передаёт готовые результаты анализа чтобы не запускать детекцию повторно
    analyzer_results: Optional[List[AnalyzerResultItem]] = None
    anonymizers: Optional[Any] = None  # принимаем, не используем — всегда <ENTITY_TYPE>
    model_config = ConfigDict(extra="allow")


class AnonymizeResponse(BaseModel):
    text: str
    items: List[OperatorResultItem]  # нужны LiteLLM для логирования и deanonymization


# ── Инициализация детектора ──────────────────────────────────────────────────

_detector = None
_allow_list: List[str] = []

# Больше этого (суммарно по текстам запроса) не анализируем — 413 вместо долгого ожидания.
# Память от длины не зависит (тексты режутся на куски), растёт только время.
_MAX_TEXT_CHARS = int(os.environ.get("PII_MAX_TEXT_CHARS", "2000000"))


def _check_size(texts: List[str]) -> None:
    total = sum(len(t) for t in texts)
    if total > _MAX_TEXT_CHARS:
        raise HTTPException(413, detail=f"Текст запроса слишком длинный для проверки: {total} символов, "
                                        f"не больше {_MAX_TEXT_CHARS}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _detector
    model_path = os.environ.get("PII_SPACY_MODEL_PATH", "alrosait/spacy_ru_core_news_lg_pii")
    logger.info(f"Загружаем HybridPIIDetector из {model_path} ...")
    from pii_detector import HybridPIIDetector, config
    _detector = HybridPIIDetector(
        spacy_model_path=model_path,
        chunk_chars=int(os.environ.get("PII_CHUNK_CHARS", config.CHUNK_CHARS)),
        chunk_overlap=int(os.environ.get("PII_CHUNK_OVERLAP", config.CHUNK_OVERLAP)),
        max_parallel=int(os.environ.get("PII_MAX_PARALLEL", config.MAX_PARALLEL)),
    )
    logger.info("HybridPIIDetector готов ✓")
    allow_path = os.environ.get("PII_ALLOW_LIST_FILE")
    if allow_path:
        with open(allow_path, encoding="utf-8") as f:
            _allow_list.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
        logger.info(f"Allow-list: {len(_allow_list)} терминов из {allow_path}")
    yield
    logger.info("pii-service остановлен")


app = FastAPI(title="PII Service", version="2.0.0", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Healthcheck для docker-compose depends_on.
    Возвращает 503 пока детектор не загружен.
    """
    if _detector is None:
        raise HTTPException(503, detail="Детектор инициализируется, подождите")
    return {"status": "ok", "detector_ready": True}


@app.post("/analyze", response_model=List[EntityResult])
def analyze(req: AnalyzeRequest):
    """Presidio-совместимый эндпоинт анализа.

    LiteLLM отправляет: {"text": "...", "language": "en", "entities": [...]}
    Возвращает список обнаруженных сущностей с позициями и score.
    """
    if _detector is None:
        raise HTTPException(503, detail="Детектор не готов")
    _check_size([req.text])

    results = _detector.analyze(req.text, language=req.language)

    # Фильтрация по конкретным типам если LiteLLM передал список
    if req.entities:
        results = [r for r in results if r.entity_type in req.entities]

    # Фильтрация по минимальному score если задан порог
    if req.score_threshold is not None:
        results = [r for r in results if r.score >= req.score_threshold]

    return [
        EntityResult(
            entity_type=r.entity_type,
            start=r.start,
            end=r.end,
            score=r.score,
        )
        for r in results
    ]


@app.post("/anonymize", response_model=AnonymizeResponse)
def anonymize(req: AnonymizeRequest):
    """Presidio-совместимый эндпоинт анонимизации.

    LiteLLM отправляет: {"text": "...", "analyzer_results": [...]}
    Возвращает {"text": "...", "items": [...]} где items описывают замены.

    Если analyzer_results переданы — используем их напрямую без повторного анализа.
    Если нет — запускаем полный пайплайн.
    """
    if _detector is None:
        raise HTTPException(503, detail="Детектор не готов")

    if req.analyzer_results:
        # Реконструируем RecognizerResult из JSON чтобы не запускать анализ повторно
        from presidio_analyzer import RecognizerResult
        presidio_results = [
            RecognizerResult(
                entity_type=r.entity_type,
                start=r.start,
                end=r.end,
                score=r.score,
            )
            for r in req.analyzer_results
        ]
    else:
        presidio_results = _detector.analyze(req.text, language=req.language)

    if not presidio_results:
        return AnonymizeResponse(text=req.text, items=[])

    engine_result = _detector._anonymizer.anonymize(
        text=req.text,
        analyzer_results=presidio_results,
    )

    items = [
        OperatorResultItem(
            operator=item.operator,
            entity_type=item.entity_type,
            start=item.start,
            end=item.end,
            text=item.text,
        )
        for item in (engine_result.items or [])
    ]

    return AnonymizeResponse(text=engine_result.text or '', items=items)


# ── /mask: маскирование всех текстов запроса к LLM разом ─────────────────────

class MaskRequest(BaseModel):
    texts: List[str]
    # Действие по типу сущности: MASK | PSEUDONYMIZE | BLOCK | ALLOW (по умолчанию MASK, NAME — PSEUDONYMIZE)
    policy: Optional[Dict[str, str]] = None
    # Минимальный score по типу; ключ "ALL" — для остальных типов
    score_thresholds: Optional[Dict[str, float]] = None
    # Термины, которые не считаются ПД (дополняют PII_ALLOW_LIST_FILE)
    allow_list: Optional[List[str]] = None
    # Сколько секунд клиент ждёт ответа. Не успели — 504, а не работа впустую после его таймаута.
    timeout: Optional[float] = None


class MaskResponse(BaseModel):
    texts: List[str]
    restore: List[List[str]]  # пары [замена, оригинал] для обратной подстановки в ответе модели
    entities: Dict[str, int]  # сколько найдено по типам
    blocked: List[str]  # типы с политикой BLOCK, найденные в запросе; тогда texts и restore пустые


@app.post("/mask", response_model=MaskResponse)
def mask(req: MaskRequest):
    """Маскирует тексты одного запроса со сквозными метками и псевдонимами ФИО.

    Используется guardrail-ом LiteLLM (docker/litellm/pii_guardrail.py).
    """
    if _detector is None:
        raise HTTPException(503, detail="Детектор не готов")
    from pii_detector.chunking import DeadlineExceeded
    from pii_detector.masking import ACTIONS, mask_texts

    bad = {k: v for k, v in (req.policy or {}).items() if v not in ACTIONS}
    if bad:
        raise HTTPException(422, detail=f"Неизвестные действия {bad}, допустимые: {ACTIONS}")
    _check_size(req.texts)

    started = time.monotonic()
    try:
        result = mask_texts(
            _detector,
            req.texts,
            policy=req.policy,
            score_thresholds=req.score_thresholds,
            allow_list=_allow_list + (req.allow_list or []),
            deadline=started + req.timeout if req.timeout else None,
        )
    except DeadlineExceeded:
        chars = sum(len(t) for t in req.texts)
        logger.warning(f"/mask: не успели за {req.timeout} с ({len(req.texts)} текстов, {chars} символов)")
        raise HTTPException(504, detail=f"Проверка не успела за {req.timeout} с")
    return MaskResponse(
        texts=result.texts,
        restore=[[a, b] for a, b in result.restore],
        entities=result.entities,
        blocked=result.blocked,
    )
