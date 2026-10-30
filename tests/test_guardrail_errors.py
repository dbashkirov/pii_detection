"""Ответы guardrail LiteLLM, когда pii-service не справился: длинный запрос, таймаут, недоступен.

Нужен установленный litellm — как для tests/test_guardrail_restore.py.
"""
import asyncio
import importlib.util
import json
import os

import httpx
import pytest

pytest.importorskip("litellm")
from fastapi import HTTPException  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.environ.get("PII_GUARDRAIL", os.path.join(_HERE, "..", "docker", "litellm", "pii_guardrail.py"))
_spec = importlib.util.spec_from_file_location("pii_guardrail", _PATH)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def mask(handler, timeout=7.0):
    guardrail = g.PIIGuardrail(pii_timeout=timeout)
    guardrail._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return asyncio.run(guardrail._mask(["Петров Иван Сергеевич"]))


def error(handler, **kw):
    with pytest.raises(HTTPException) as e:
        mask(handler, **kw)
    return e.value.status_code, e.value.detail["error"]


def test_sends_timeout_and_returns_result():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"texts": ["x"], "restore": [], "entities": {}, "blocked": []})

    assert mask(handler)["texts"] == ["x"]
    assert sent[0]["timeout"] == 7.0


def test_too_long():
    status, text = error(lambda r: httpx.Response(413, json={"detail": "..."}))
    assert status == 413 and "слишком длинный" in text


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(504, json={"detail": "..."}),
    lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=r)),
])
def test_too_slow(handler):
    status, text = error(handler, timeout=7.0)
    assert status == 504 and "не успела за 7 с" in text


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500, text="Internal Server Error"),
    lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)),
])
def test_unavailable(handler):
    status, text = error(handler)
    assert status == 503 and "недоступен" in text
