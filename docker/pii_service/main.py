import os
import logging
from contextlib import asynccontextmanager
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("pii-service")


# ── Схемы запросов и ответов ─────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text: str
    language: str = "en"


class EntityResult(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float


class AnonymizeResponse(BaseModel):
    text: str


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


app = FastAPI(title="PII Service", version="1.0.0", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Healthcheck для docker-compose depends_on.
    Возвращает 503 пока детектор не загружен — иначе curl -sf считает контейнер
    healthy сразу после старта uvicorn, до завершения инициализации spaCy-модели.
    """
    if _detector is None:
        raise HTTPException(503, detail="Детектор инициализируется, подождите")
    return {"status": "ok", "detector_ready": True}


@app.post("/analyze", response_model=List[EntityResult])
def analyze(req: AnalyzeRequest):
    """Обнаружить ПД в тексте, вернуть список сущностей с позициями."""
    if _detector is None:
        raise HTTPException(503, detail="Детектор не готов — подождите завершения инициализации")
    results = _detector.analyze(req.text, language=req.language)
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
def anonymize(req: AnalyzeRequest):
    """Заменить ПД в тексте на теги вида <ENTITY_TYPE>."""
    if _detector is None:
        raise HTTPException(503, detail="Детектор не готов — подождите завершения инициализации")
    masked = _detector.anonymize(req.text, language=req.language)
    return AnonymizeResponse(text=masked)
