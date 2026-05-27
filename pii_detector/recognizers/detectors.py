import re
from typing import Callable, List, Optional

import phonenumbers
from presidio_analyzer import Pattern, PatternRecognizer, EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts
from rapidfuzz.distance import Levenshtein as _Lev

from pii_detector.validators import (
    validate_inn, validate_snils, validate_ogrn, validate_ogrnip, validate_luhn,
)

_WINDOW = 60  # chars to look left/right for context keywords


def _context_match(window: str, keywords: set) -> bool:
    """Check if any keyword appears in pre-sliced, lowercased window (exact or Levenshtein ≤ 1)."""
    if any(kw in window for kw in keywords):
        return True
    tokens = [t for t in re.split(r'\W+', window) if t]
    single_kws = [kw for kw in keywords if ' ' not in kw]
    return any(
        _Lev.distance(tok, kw, score_cutoff=1) <= 1
        for tok in tokens
        for kw in single_kws
        if abs(len(tok) - len(kw)) <= 1
    )


def _has_context(text: str, start: int, end: int, keywords: set) -> bool:
    window = text[max(0, start - _WINDOW): end + _WINDOW].lower()
    return _context_match(window, keywords)


def _score_by_context(
        results: List[RecognizerResult],
        text: str,
        keywords: set,
        close: int,
        far: int,
        score_close: float,
        score_far: float,
        validator: Optional[Callable[[str], bool]] = None,
) -> List[RecognizerResult]:
    """Filter and score results by context proximity. Discards results with no context."""
    out = []
    text_lower = text.lower()
    for r in results:
        if validator is not None and not validator(text[r.start:r.end]):
            continue
        w_close = text_lower[max(0, r.start - close): r.end + close]
        if _context_match(w_close, keywords):
            r.score = score_close
        else:
            w_far = text_lower[max(0, r.start - far): r.end + far]
            if _context_match(w_far, keywords):
                r.score = score_far
            else:
                continue
        out.append(r)
    return out


class InnRecognizer(PatternRecognizer):
    _KEYWORDS = {"инн", "идентификацинн", "налогоплательщик"}
    _CLOSE = _WINDOW // 2
    _FAR = _WINDOW

    def __init__(self):
        super().__init__(
            supported_entity="INN",
            patterns=[
                Pattern("INN_12", r"\b\d{12}\b", 0.5),
                Pattern("INN_10", r"\b\d{10}\b", 0.5),
            ],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        return _score_by_context(results, text, self._KEYWORDS,
                                 self._CLOSE, self._FAR, 0.9, 0.7, validate_inn)


class SnilsRecognizer(PatternRecognizer):
    _KEYWORDS = {"снилс", "страхов", "пенсионн"}
    _CLOSE = _WINDOW // 2
    _FAR = _WINDOW

    def __init__(self):
        super().__init__(
            supported_entity="SNILS",
            patterns=[
                Pattern("SNILS_FMT", r"\b\d{3}-\d{3}-\d{3}\s\d{2}\b", 0.9),
                Pattern("SNILS_RAW", r"\b\d{11}\b", 0.7),
            ],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        # SNILS_FMT (XXX-XXX-XXX XX) is self-contextualizing — format is distinctive enough without checksum
        fmt = [r for r in results if r.score >= 0.9]
        raw = _score_by_context(
            [r for r in results if r.score < 0.9],
            text, self._KEYWORDS, self._CLOSE, self._FAR, 1.0, 0.85, validate_snils,
        )
        return fmt + raw


class OgrnRecognizer(PatternRecognizer):
    _KEYWORDS = {"огрн", "государственный регистрационный"}
    _CLOSE = _WINDOW // 2
    _FAR = _WINDOW

    def __init__(self):
        super().__init__(
            supported_entity="OGRN",
            patterns=[
                Pattern("OGRN", r"\b[15]\d{12}\b", 0.7),
                Pattern("OGRN_DASH", r"\b[15]-\d{2}-\d{2}-\d{7}-\d\b", 0.7),
            ],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        return _score_by_context(results, text, self._KEYWORDS,
                                 self._CLOSE, self._FAR, 1.0, 0.85, validate_ogrn)


class OgrnipRecognizer(PatternRecognizer):
    _KEYWORDS = {"огрнип", "предпринимател", "огрн ип"}
    _CLOSE = _WINDOW // 2
    _FAR = _WINDOW

    def __init__(self):
        super().__init__(
            supported_entity="OGRNIP",
            patterns=[
                Pattern("OGRNIP", r"\b[34]\d{14}\b", 0.7),
                Pattern("OGRNIP_DASH", r"\b[34]-\d{2}-\d{2}-\d{9}-\d\b", 0.7),
            ],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        return _score_by_context(results, text, self._KEYWORDS,
                                 self._CLOSE, self._FAR, 1.0, 0.85, validate_ogrnip)


class KppRecognizer(PatternRecognizer):
    _KEYWORDS = {"кпп", "причина постановки", "причины постановки"}
    _CLOSE = _WINDOW // 2
    _FAR = _WINDOW

    def __init__(self):
        super().__init__(
            supported_entity="KPP",
            patterns=[
                Pattern("KPP_RAW", r"\b\d{4}[\dA-Z]{2}\d{3}\b", 0.5),
                Pattern("KPP_DASH", r"\b\d{4}-[\dA-Z]{2}-\d{3}\b", 0.6),
            ],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        raw = [r for r in results if r.score == 0.5]
        dash = [r for r in results if r.score == 0.6]
        return (
                _score_by_context(raw, text, self._KEYWORDS, self._CLOSE, self._FAR, 0.9, 0.7, validator=None) +
                _score_by_context(dash, text, self._KEYWORDS, self._CLOSE, self._FAR, 1.0, 0.8, validator=None)
        )


class PassportRecognizer(PatternRecognizer):
    _KEYWORDS = {"паспорт", "паспортн", "сери", "документ", "удостовер"}
    _CLOSE = _WINDOW // 2
    _FAR = _WINDOW

    def __init__(self):
        super().__init__(
            supported_entity="PASSPORT_NUMBER",
            patterns=[
                # self-contextualizing: always kept as-is
                Pattern("PASSPORT_TEXT", r"серия\s+\d{4}\s+номер\s+\d{6}", 0.90),
                # distinctive formats: boosted by context
                Pattern("PASSPORT_SPACED", r"\b\d{2}\s\d{2}\s\d{6}\b", 0.70),
                Pattern("PASSPORT_COMPACT", r"\b\d{4}\s\d{6}\b", 0.55),
                Pattern("PASSPORT_DASH", r"\b\d{4}[-]\d{6}\b", 0.55),
                # generic: requires context, deliberately low to lose to INN/SNILS
                Pattern("PASSPORT_NOSPACE", r"\b\d{10}\b", 0.30),
            ],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        out = []
        text_lower = text.lower()
        for r in results:
            # PASSPORT_TEXT contains "серия"/"номер" — self-contextualizing
            if r.score >= 0.90:
                out.append(r)
                continue

            base = r.score
            w_close = text_lower[max(0, r.start - self._CLOSE): r.end + self._CLOSE]
            if _context_match(w_close, self._KEYWORDS):
                score = round(min(base + 0.4, 1.0), 2)
            else:
                w_far = text_lower[max(0, r.start - self._FAR): r.end + self._FAR]
                if _context_match(w_far, self._KEYWORDS):
                    score = round(base + 0.2, 2)
                else:
                    if base < 0.5:  # NOSPACE without context → discard
                        continue
                    score = base
            r.score = score
            out.append(r)
        return out


class EmailRecognizer(PatternRecognizer):
    def __init__(self):
        super().__init__(
            supported_entity="EMAIL",
            patterns=[
                Pattern(
                    "EMAIL",
                    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
                    0.9,
                )
            ],
        )


class PhoneRecognizer(EntityRecognizer):
    _KEYWORDS = {"телефон", "тел", "мобильн", "сотов", "звонок", "звонк", "позвон"}
    _CLOSE = _WINDOW // 2
    _FAR = _WINDOW

    def __init__(self):
        super().__init__(supported_entities=["PHONE_NUMBER"], name="PhoneRecognizer")

    def load(self):
        pass

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None) \
            -> List[RecognizerResult]:
        results = []
        text_lower = text.lower()
        for match in phonenumbers.PhoneNumberMatcher(text, "RU"):
            raw = match.raw_string
            digits = re.sub(r"\D", "", raw)

            # Base score from format
            if re.search(r'[+()\-]', raw) or re.search(r'\d \d', raw):
                score = 0.65  # clearly phone-formatted
            elif len(digits) == 11:
                score = 0.50  # 11 bare digits
            else:
                score = 0.40  # 10 bare digits — most ambiguous

            # Validity bonus
            if phonenumbers.is_valid_number(match.number):
                score += 0.15

            # Context bonus
            s, e = match.start, match.end
            w_close = text_lower[max(0, s - self._CLOSE): e + self._CLOSE]
            if any(kw in w_close for kw in self._KEYWORDS):
                score += 0.15
            else:
                w_far = text_lower[max(0, s - self._FAR): e + self._FAR]
                if any(kw in w_far for kw in self._KEYWORDS):
                    score += 0.10

            results.append(RecognizerResult(
                entity_type="PHONE_NUMBER",
                start=match.start,
                end=match.end,
                score=round(min(score, 1.0), 2),
            ))
        return results


class BankCardRecognizer(PatternRecognizer):
    _KEYWORDS = {"карт", "card", "visa", "mastercard", "мир", "maestro"}
    _CLOSE = 30
    _FAR = 60

    def __init__(self):
        super().__init__(
            supported_entity="BANK_CARD_NUMBER",
            patterns=[Pattern("BANK_CARD", r"\b\d(?:[ \-]?\d){12,18}\b", 0.5)],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        out = []
        text_lower = text.lower()
        for r in results:
            span = text[r.start:r.end]
            if not validate_luhn(span):
                continue

            score = 0.5
            digits = re.sub(r"\D", "", span)
            if len(digits) == 16:
                score += 0.2

            close = text_lower[max(0, r.start - self._CLOSE): r.end + self._CLOSE]
            if any(kw in close for kw in self._KEYWORDS):
                score += 0.3
            else:
                far = text_lower[max(0, r.start - self._FAR): r.end + self._FAR]
                if any(kw in far for kw in self._KEYWORDS):
                    score += 0.15

            r.score = round(score, 2)
            out.append(r)
        return out


_CVC_CONTEXT_WORDS = {
    # латиница
    "cvc", "cvv", "cvс", "cvc2", "cvv2", "cvv/cvc", "cvc/cvv",
    "security code", "card verification",
    # кириллица
    "цвц", "цвс", "квв", "квс", "свс", "свц",
    # явные метки
    "код карты", "секретный код", "код безопасност",
    # обратная сторона карты
    "обратной сторон", "обратная сторон", "оборот", "сзади карт",
    "с обратной", "на обороте", "на обратной",
    # описательные фразы
    "три цифр", "трёх цифр", "трехзначн", "трёхзначн",
    "код подтвержден", "код верификац",
    "цифры карт", "цифр карт",
}
_CVC_WINDOW = 60


class CvcRecognizer(PatternRecognizer):
    _CLOSE = _CVC_WINDOW // 2
    _FAR = _CVC_WINDOW

    def __init__(self):
        super().__init__(
            supported_entity="CVC",
            patterns=[Pattern("CVC", r"\b\d{3,4}\b", 0.4)],
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None,
                regex_flags: Optional[int] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        out = []
        text_lower = text.lower()
        for r in results:
            close = text_lower[max(0, r.start - self._CLOSE): r.end + self._CLOSE]
            if any(w in close for w in _CVC_CONTEXT_WORDS):
                score = 0.7
            else:
                far = text_lower[max(0, r.start - self._FAR): r.end + self._FAR]
                if any(w in far for w in _CVC_CONTEXT_WORDS):
                    score = 0.5
                else:
                    continue
            r.score = score
            out.append(r)
        return out
