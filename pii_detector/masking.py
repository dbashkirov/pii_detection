"""Маскирование всех текстов одного запроса к LLM разом (эндпоинт /mask pii-service).

В отличие от поштучного /anonymize, здесь одно значение получает одну метку во всех текстах
запроса (история чата, system prompt, аргументы tool calls), а разные значения — разные метки.
ФИО по умолчанию заменяются псевдонимами в нужном падеже (см. pseudonymizer.py).

Результат — замаскированные тексты и пары (замена → оригинал) для обратной подстановки в ответе
модели. Пары включают варианты, в которые модели обычно переписывают метки: [EMAIL_1], EMAIL_1.
"""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from pii_detector.pseudonymizer import Pseudonymizer

# MASK — метка <TYPE_n>; PSEUDONYMIZE — псевдоним (только NAME, иначе как MASK);
# BLOCK — запрос отклоняется; ALLOW — не трогать.
ACTIONS = ("MASK", "PSEUDONYMIZE", "BLOCK", "ALLOW")
DEFAULT_POLICY = {"NAME": "PSEUDONYMIZE"}


@dataclass
class MaskResult:
    texts: List[str]
    restore: List[Tuple[str, str]]
    entities: Dict[str, int]
    blocked: List[str]


def _placeholder_variants(name: str) -> List[str]:
    return [f"<{name}>", f"[{name}]", f"{{{name}}}", name]


def _drop_allowed(text: str, results, allow_list: Iterable[str]):
    """Убирает сущности, попадающие в термины allow-list (названия компаний, месторождений: «Сухой Лог»)."""
    lower = text.lower()
    spans = []
    for term in allow_list:
        t = term.strip().lower()
        if not t:
            continue
        i = lower.find(t)
        while i != -1:
            spans.append((i, i + len(t)))
            i = lower.find(t, i + 1)
    if not spans:
        return results
    # NER иногда захватывает соседнее слово («Сухой Лог добыто») — отбрасываем любое пересечение.
    return [r for r in results if not any(r.start < e and s < r.end for s, e in spans)]


def _propagate(texts: List[str], restore: List[Tuple[str, str]]) -> List[str]:
    """Заменяет оставшиеся вхождения уже найденных значений, которые NER пропустил.

    «Исполнитель — Петров Иван Сергеевич … позвоните Петрову» — второе упоминание детектор может
    не отметить, но раз человек найден в запросе, его фамилия в любом падеже тоже заменяется.
    """
    forward: Dict[str, str] = {}
    for replacement, original in restore:
        if replacement.startswith("[") or replacement.startswith("{") or replacement == original:
            continue
        if not replacement.startswith("<") and "_" in replacement and replacement.isupper():
            continue  # голый вариант метки EMAIL_1 — только для обратной замены
        forward.setdefault(original, replacement)
    if not forward:
        return texts
    keys = sorted(forward, key=len, reverse=True)
    pattern = re.compile("|".join(
        (r"(?<!\w)" if k[0].isalnum() else "") + re.escape(k) + (r"(?!\w)" if k[-1].isalnum() else "")
        for k in keys))
    return [pattern.sub(lambda m: forward[m.group(0)], t) for t in texts]


def mask_texts(
        detector,
        texts: List[str],
        policy: Optional[Dict[str, str]] = None,
        score_thresholds: Optional[Dict[str, float]] = None,
        allow_list: Iterable[str] = (),
) -> MaskResult:
    policy = {**DEFAULT_POLICY, **(policy or {})}
    thresholds = score_thresholds or {}
    allow_list = list(allow_list)

    found = []
    for text in texts:
        results = detector.analyze(text)
        results = [r for r in results
                   if r.score >= thresholds.get(r.entity_type, thresholds.get("ALL", 0.0))]
        results = _drop_allowed(text, results, allow_list)
        results = [r for r in results if policy.get(r.entity_type, "MASK") != "ALLOW"]
        found.append(sorted(results, key=lambda r: (r.start, -r.end)))

    counts = Counter(r.entity_type for results in found for r in results)
    blocked = sorted({r.entity_type for results in found for r in results
                      if policy.get(r.entity_type) == "BLOCK"})
    if blocked:
        return MaskResult(texts=[], restore=[], entities=dict(counts), blocked=blocked)

    pseudonymizer = Pseudonymizer(texts)
    placeholders: Dict[Tuple[str, str], str] = {}
    numbers: Counter = Counter()
    restore_placeholders: List[Tuple[str, str]] = []
    masked = []
    for text, results in zip(texts, found):
        pieces, pos = [], 0
        for r in results:
            if r.start < pos:
                continue  # пересечение с уже заменённым фрагментом
            value = text[r.start:r.end]
            replacement = None
            if r.entity_type == "NAME" and policy.get("NAME") == "PSEUDONYMIZE":
                replacement = pseudonymizer.mask(value)
            if replacement is None:
                key = (r.entity_type, " ".join(value.split()).casefold())
                if key not in placeholders:
                    numbers[r.entity_type] += 1
                    placeholders[key] = f"{r.entity_type}_{numbers[r.entity_type]}"
                    restore_placeholders += [(v, value) for v in _placeholder_variants(placeholders[key])]
                replacement = f"<{placeholders[key]}>"
            pieces += [text[pos:r.start], replacement]
            pos = r.end
        pieces.append(text[pos:])
        masked.append("".join(pieces))

    restore = pseudonymizer.restore_pairs() + restore_placeholders
    return MaskResult(
        texts=_propagate(masked, restore),
        restore=restore,
        entities=dict(counts),
        blocked=[],
    )
