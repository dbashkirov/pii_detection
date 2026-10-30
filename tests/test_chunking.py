"""Анализ длинного текста кусками: тот же результат, что и целиком, включая сущности на стыках.

Детектор подменён регулярками, одна из них — с контекстом, как у правил ИНН и OTP. Нужен
presidio-analyzer — проще всего в образе pii-service (см. tests/test_recognizers.py).
"""
import random
import re
import threading
import time

import pytest
from presidio_analyzer import RecognizerResult

from pii_detector.chunking import DeadlineExceeded, FairSlots, analyze_in_chunks, chunk_spans
from pii_detector.engine import HybridPIIDetector

PATTERNS = {
    "NAME": r"Петров[а-я]* Иван[а-я]* Сергеевич[а-я]*",
    "EMAIL": r"[\w.]+@example\.ru",
    "PHONE_NUMBER": r"\+7 \d{3} \d{3}-\d{2}-\d{2}",
    "TOKEN": r"\bsk-[A-Za-z0-9]{20,}",
}
INN_RE = re.compile(r"\b\d{12}\b")
FILLER = ["Объём горной массы составил 1520 тыс. м³.", "Работы выполнены в срок.",
          "Комиссия приняла решение о продлении сроков на 12 рабочих дней!", "Пробы отобраны по ГОСТ;"]
PII = ["Ответственный — Петров Иван Сергеевич.", "Звонить Петрову Ивану Сергеевичу: +7 914 123-45-67.",
       "Почта i.petrov@example.ru.", "ИНН организации 386018159000.", "Ключ sk-abcdefghijklmnopqrstuvwx."]


def fake_analyze(text):
    found = [RecognizerResult(t, m.start(), m.end(), 0.9)
             for t, p in PATTERNS.items() for m in re.finditer(p, text)]
    # Как правила детектора: число считается ИНН, только если слово «ИНН» не дальше 60 символов.
    found += [RecognizerResult("INN", m.start(), m.end(), 0.9) for m in INN_RE.finditer(text)
              if "инн" in text[max(0, m.start() - 60):m.end() + 60].lower()]
    return found


def no_dedup(results):
    return results


def spans(results):
    return sorted((r.entity_type, r.start, r.end) for r in results)


def document(paragraphs, seed=1):
    r = random.Random(seed)
    return "\n\n".join(" ".join(r.choice(PII if r.random() < 0.4 else FILLER) for _ in range(r.randint(2, 6)))
                       for _ in range(paragraphs))


def test_spans_cover_text_and_respect_size():
    text = document(200)
    size, overlap = 500, 100
    parts = chunk_spans(text, size, overlap)
    assert parts[0][1] == 0 and parts[-1][2] == len(text)
    for (w0, s, e, w1), nxt in zip(parts, parts[1:] + [None]):
        assert 0 < e - s <= size
        assert w0 <= s < e <= w1 and s - w0 <= overlap and w1 - e <= overlap
        if nxt:
            assert nxt[1] == e
            assert text[e - 1] in " \n"  # режем по границе абзаца, предложения или слова
        assert w0 == 0 or text[w0 - 1] in " \n\t"  # окно не начинается с середины слова


def test_prefers_paragraph_boundary():
    text = "а" * 300 + "\n\n" + "б" * 100 + ". " + "в" * 50
    (_, _, end, _), _ = chunk_spans(text, 420, 10)
    assert end == 302


def test_short_text_in_one_piece():
    calls = []
    analyze_in_chunks("короткий", lambda t: calls.append(t) or [], no_dedup, 100, 10)
    assert calls == ["короткий"]


@pytest.mark.parametrize("size", range(150, 420, 13))
def test_same_as_whole_text_with_entities_on_seams(size):
    # Размер куска сдвигается, и стыки проходят через все места текста, в том числе через сущности.
    text = document(60)
    whole = fake_analyze(text)
    assert {r.entity_type for r in whole} == {"NAME", "EMAIL", "PHONE_NUMBER", "TOKEN", "INN"}
    chunked = analyze_in_chunks(text, fake_analyze, no_dedup, size, 100)
    assert spans(chunked) == spans(whole)


def test_entity_longer_than_overlap_is_glued():
    secret = "sk-" + "Ab1" * 400
    text = document(5) + " Ключ " + secret + " и дальше. " + document(5, seed=2)
    start = text.index(secret)
    chunked = analyze_in_chunks(text, fake_analyze, no_dedup, 300, 50)
    tokens = [(r.start, r.end) for r in chunked if r.entity_type == "TOKEN" and r.start <= start < r.end]
    assert tokens == [(start, start + len(secret))]


def test_text_without_separators():
    text = "x" * 1000
    parts = chunk_spans(text, 300, 50)
    assert [(s, e) for _, s, e, _ in parts] == [(0, 300), (300, 600), (600, 900), (900, 1000)]


def test_deadline_stops_between_chunks():
    calls = []

    def slow(t):
        calls.append(t)
        time.sleep(0.05)
        return []

    with pytest.raises(DeadlineExceeded):
        analyze_in_chunks(document(100), slow, no_dedup, 300, 50, deadline=time.monotonic() + 0.12)
    assert 1 <= len(calls) <= 4
    with pytest.raises(DeadlineExceeded):
        analyze_in_chunks("коротко", slow, no_dedup, 300, 50, deadline=time.monotonic() - 1)


class FakeAnalyzerEngine:
    def __init__(self):
        self.active = self.max_active = 0
        self.lock = threading.Lock()

    def analyze(self, text, entities, language):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.002)
        with self.lock:
            self.active -= 1
        return fake_analyze(text)


def detector(chunk_chars, max_parallel=2):
    d = object.__new__(HybridPIIDetector)
    d._analyzer = FakeAnalyzerEngine()
    d._chunk_chars, d._chunk_overlap = chunk_chars, 100
    d._slots = FairSlots(max_parallel)
    return d


def test_detector_chunked_same_as_whole():
    text = document(80)
    assert spans(detector(300).analyze(text)) == spans(detector(10 ** 6).analyze(text))


def test_detector_limits_parallel_chunks():
    d = detector(300, max_parallel=1)
    threads = [threading.Thread(target=d.analyze, args=(document(20, seed=i),)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert d._analyzer.max_active == 1


def test_slots_go_to_longest_waiting():
    # Длинный запрос отпускает слот и сразу просит снова — слот должен уйти короткому, который ждёт.
    slots, order = FairSlots(1), []
    assert slots.acquire()
    short = threading.Thread(target=lambda: slots.acquire() and order.append("short"))
    short.start()
    while not slots._waiters:
        time.sleep(0.001)
    slots.release()
    assert slots.acquire(timeout=0.2) is False  # слот уже у короткого
    short.join()
    assert order == ["short"]
    slots.release()
    assert slots.acquire(timeout=0) and not slots.acquire(timeout=0.01)


def test_slots_timeout_leaves_queue():
    slots = FairSlots(1)
    slots.acquire()
    assert slots.acquire(timeout=0.01) is False and not slots._waiters
    slots.release()
    assert slots.acquire(timeout=0)
