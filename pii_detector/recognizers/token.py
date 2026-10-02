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

# Маркеры ищутся с начала слова: «ключ» не должен находиться в «заключении» и «включить».
_TOKEN_MARKERS_RE = re.compile(r'\b(?:' + '|'.join([
    'токен', 'ключ', 'пароль', 'секрет', 'подтвержд', 'активац', 'авторизац',
    'token', 'key', 'secret', 'api', 'bearer', 'access',
    'refresh', 'authorization', 'credentials', 'auth', 'confirm',
    'password', 'passphrase',
]) + ')')
_STRONG_MARKERS = [
    'токен:', 'ключ:', 'token:', 'secret:', 'api_key:', 'bearer ', 'api key:', 'api token:',
]

# Одноразовый код. Слова ищутся целиком: «код» не должен находиться в «кодексе» и «кодировке»,
# «пин» — в «пинге», «code» — в «decode». Сами по себе «код» и «code» встречаются слишком часто
# («код ошибки 5003», «код ОКВЭД», «Python code»), поэтому нужен уточнитель рядом: «код
# подтверждения», «код из СМС», «код доступа». Маркеров из _OTP_STRONG_RE достаточно самих по себе.
_OTP_STRONG_RE = re.compile(
    r'\b(?:otp|totp|2fa|pin|пин(?:-?код\w*)?|одноразов\w*|парол[ьяюеи]\w*|password|passcode)\b')
_OTP_CODE_RE = re.compile(r'\b(?:код|кода|коду|кодом|коде|коды|кодов|code|codes)\b')
_OTP_QUALIFIER_RE = re.compile(
    r'подтвержд|подтверди|активац|верификац|авторизац|восстановл|\bсброс|\bвход(?:а|е|у|ом)?\b|\bдоступ|'
    r'\bсмс\b|\bsms\b|никому|verif|confirm|one-time|\blogin\b|\bauth|\baccess\b|\bsecurity\b')
_ANTI_OTP = ['паспорт', 'серия', 'номер карты', 'карта', 'руб', '₽', 'списали', 'платёж']
# Год, а не код: «с 2026 года», «в 2024 г.», «2025 год»
_YEAR_AFTER_RE = re.compile(r'\s*(?:г\.|гг?\b|год)')


def _ctx(text: str, start: int, end: int, window: int = 60) -> str:
    return text[max(0, start - window):min(len(text), end + window)].lower()


def _has_token_ctx(text: str, start: int, end: int) -> bool:
    return bool(_TOKEN_MARKERS_RE.search(_ctx(text, start, end)))


def _has_strong_ctx(text: str, start: int, end: int) -> bool:
    c = _ctx(text, start, end)
    return any(m in c for m in _STRONG_MARKERS)


def _is_year(text: str, start: int, end: int) -> bool:
    value = text[start:end]
    return len(value) == 4 and value[:2] in ('19', '20') and bool(_YEAR_AFTER_RE.match(text, end))


def _has_otp_ctx(text: str, start: int, end: int) -> bool:
    c = _ctx(text, start, end, window=40)
    if any(m in c for m in _ANTI_OTP) or _is_year(text, start, end):
        return False
    if _OTP_STRONG_RE.search(c):
        return True
    return bool(_OTP_CODE_RE.search(c) and _OTP_QUALIFIER_RE.search(c))


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

# Хэши (sha256-digest образа, коммит git, md5) — высокоэнтропийные, но не секреты.
# Пропускаем hex-строку стандартной длины с префиксом алгоритма или рядом со словами про хэш,
# если рядом нет явного маркера секрета («token:», «api key:»…).
_HEX_RE = re.compile(r'[0-9a-fA-F]+')
_HASH_LENGTHS = {32, 40, 56, 64, 96, 128}
_HASH_PREFIX_RE = re.compile(r'(?:sha(?:1|224|256|384|512)|md5)[:=@-]$', re.IGNORECASE)
_HASH_MARKERS = ['digest', 'sha', 'commit', 'коммит', 'hash', 'хэш', 'хеш', 'checksum', 'контрольн']


def _is_hash(text: str, start: int, end: int) -> bool:
    candidate = text[start:end]
    if len(candidate) not in _HASH_LENGTHS or not _HEX_RE.fullmatch(candidate):
        return False
    if _has_strong_ctx(text, start, end):
        return False
    if _HASH_PREFIX_RE.search(text[max(0, start - 8):start]):
        return True
    c = _ctx(text, start, end, window=40)
    return any(m in c for m in _HASH_MARKERS)


# Пути модулей, имена переменных и файлов из кода: openpyxl.worksheet.datavalidation,
# calculate_total_revenue_by_region, src/components/UserProfile. По длине и энтропии они похожи
# на ключ, но каждая часть — обычные слова (snake_case, camelCase, CONSTANT) и короткие числа.
# В случайной строке цифры стоят внутри частей, а «слова» из букв выходят по одной-две буквы.
_WORD_CHUNK_RE = re.compile(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+')


def _is_identifier(candidate: str) -> bool:
    if '=' in candidate or '+' in candidate:  # base64
        return False
    chunks = 0
    for part in filter(None, re.split(r'[._/\-]', candidate)):
        if part.isdigit():
            if len(part) > 4:
                return False
            continue
        word = part.rstrip('0123456789')
        if not word or len(part) - len(word) > 2:
            return False
        found = _WORD_CHUNK_RE.findall(word)
        if ''.join(found) != word:  # цифры в середине
            return False
        chunks += len(found)
    letters = sum(ch.isalpha() for ch in candidate)
    return chunks > 0 and letters / chunks >= 3


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
            if _is_hash(text, m.start(), m.end()):
                continue
            strong = _has_strong_ctx(text, m.start(), m.end())
            if not strong and _is_identifier(candidate):
                continue
            score = 0.90 if strong else 0.75 if has_ctx else 0.65
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
