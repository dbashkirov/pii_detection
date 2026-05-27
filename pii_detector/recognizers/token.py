import math
import re
from collections import Counter
from typing import List, Optional

from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts


# ── Энтропия ──────────────────────────────────────────────────────────────────

def _entropy(s: str) -> float:
    if len(s) < 2:
        return 0.0
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


# ── Контекст ──────────────────────────────────────────────────────────────────

_TOKEN_MARKERS = [
    'токен', 'ключ', 'пароль', 'секрет', 'подтвержд', 'активац', 'авторизац',
    'token', 'key', 'secret', 'api', 'bearer', 'access',
    'refresh', 'authorization', 'credentials', 'auth', 'confirm',
    'password', 'passphrase',
]
_STRONG_MARKERS = [
    'токен:', 'ключ:', 'token:', 'secret:', 'api_key:', 'bearer ', 'api key:', 'api token:',
]
_OTP_MARKERS = ['код', 'code', 'подтвержд', 'confirm', 'активац', 'otp', 'пин', 'pin']
_ANTI_OTP = ['паспорт', 'серия', 'номер карты', 'карта', 'руб', '₽', 'списали', 'платёж']


def _ctx(text: str, start: int, end: int, window: int = 60) -> str:
    return text[max(0, start - window):min(len(text), end + window)].lower()


def _has_token_ctx(text: str, start: int, end: int) -> bool:
    c = _ctx(text, start, end)
    return any(m in c for m in _TOKEN_MARKERS)


def _has_strong_ctx(text: str, start: int, end: int) -> bool:
    c = _ctx(text, start, end)
    return any(m in c for m in _STRONG_MARKERS)


def _has_otp_ctx(text: str, start: int, end: int) -> bool:
    c = _ctx(text, start, end, window=40)
    return any(m in c for m in _OTP_MARKERS) and not any(m in c for m in _ANTI_OTP)


# ── Type 1: специфические форматы ─────────────────────────────────────────────

_SPECIFIC: list[tuple[re.Pattern, float]] = [
    (re.compile(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'), 0.95),  # JWT
    (re.compile(r'\bgh[psoure]_[A-Za-z0-9]{36,}\b'), 0.95),  # GitHub
    (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'), 0.95),  # GitHub PAT
    (re.compile(r'\bglpat-[A-Za-z0-9_-]{20,}\b'), 0.95),  # GitLab
    (re.compile(r'\bsk-[A-Za-z0-9\-]{20,}\b'), 0.95),  # OpenAI / Anthropic
    (re.compile(r'\b(sk|rk)_(live|test)_[A-Za-z0-9]{24,}\b'), 0.95),  # Stripe
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), 0.95),  # AWS
    (re.compile(r'\bhf_[A-Za-z0-9]{20,}\b'), 0.95),  # HuggingFace
    (re.compile(r'\b\d{8,10}:[A-Za-z0-9_-]{35}\b'), 0.95),  # Telegram
    (re.compile(r'\b[A-Za-z][A-Za-z0-9]{1,19}[-_][A-Za-z0-9]{16,}\b'), 0.85),  # universal prefixed
]

# ── Type 2: высокоэнтропийные Latin-строки ────────────────────────────────────
# Включает: Latin + digits + base64-padding (+/=) + разделители (-_) + точки (dot-sep токены)
_CAND_RE = re.compile(r'[A-Za-z0-9+/=_\-]+(?:\.[A-Za-z0-9+/=_\-]+)*')

_NO_CTX = (3.5, 32)  # (min_entropy, min_len) без контекста
_CTX = (3.3, 16)  # с контекстом

# ── Type 3: OTP ───────────────────────────────────────────────────────────────
_OTP_RE = re.compile(r'\b\d{4,8}\b')


class TokenRecognizer(EntityRecognizer):
    def __init__(self):
        super().__init__(supported_entities=["TOKEN"], name="TokenRecognizer")

    def load(self):
        pass

    def analyze(
            self,
            text: str,
            entities: List[str],
            nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        results: List[RecognizerResult] = []
        seen: set[tuple[int, int]] = set()

        # Type 1: специфические форматы
        for pattern, base_score in _SPECIFIC:
            for m in pattern.finditer(text):
                span = (m.start(), m.end())
                if span in seen:
                    continue
                score = base_score
                if _has_strong_ctx(text, m.start(), m.end()):
                    score = min(0.97, score + 0.05)
                elif _has_token_ctx(text, m.start(), m.end()):
                    score = min(0.95, score + 0.02)
                seen.add(span)
                results.append(RecognizerResult("TOKEN", m.start(), m.end(), score))

        # Type 2: высокоэнтропийные Latin-строки
        for m in _CAND_RE.finditer(text):
            span = (m.start(), m.end())
            if span in seen:
                continue
            candidate = m.group()
            has_ctx = _has_token_ctx(text, m.start(), m.end())
            min_ent, min_len = _CTX if has_ctx else _NO_CTX
            if len(candidate) < min_len or _entropy(candidate) < min_ent:
                continue
            score = 0.90 if _has_strong_ctx(text, m.start(), m.end()) else 0.75 if has_ctx else 0.65
            seen.add(span)
            results.append(RecognizerResult("TOKEN", m.start(), m.end(), score))

        # Type 3: OTP — только при строгом контексте
        for m in _OTP_RE.finditer(text):
            span = (m.start(), m.end())
            if span in seen:
                continue
            if _has_otp_ctx(text, m.start(), m.end()):
                seen.add(span)
                results.append(RecognizerResult("TOKEN", m.start(), m.end(), 0.80))

        return results
