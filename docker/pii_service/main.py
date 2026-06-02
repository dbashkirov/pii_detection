import os
import logging
from contextlib import asynccontextmanager
from typing import Any, List, Optional

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _detector
    model_path = os.environ.get("PII_SPACY_MODEL_PATH", "/app/model-best-combo-0.78")
    logger.info(f"Загружаем HybridPIIDetector из {model_path} ...")
    from pii_detector import HybridPIIDetector
    _detector = HybridPIIDetector(spacy_model_path=model_path)
    logger.info("HybridPIIDetector готов ✓")
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
