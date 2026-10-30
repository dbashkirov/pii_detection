"""Анализ длинного текста кусками с перекрытием.

Пиковая память spaCy и Presidio растёт с длиной текста: документ в сотни тысяч символов или длинная
история чата за один проход съедают гигабайты, и контейнер убивается по OOM. Поэтому длинный текст
режется на куски по `size` символов (по границе абзаца, строки, предложения или слова) и
анализируется по очереди. Память ограничена размером куска, а не всего текста.

Чтобы не терять сущности на стыке и контекст регулярных правил («ИНН» за 60 символов от числа,
«карта» за 150), каждый кусок анализируется в окне, расширенном на `overlap` символов в обе стороны.
Из окна берутся сущности, задевающие сам кусок; одна и та же сущность из соседних окон
склеивается. Сущность, упёршаяся в край окна посреди слова (ключ или base64 длиннее перекрытия),
продлевается до конца слова: в следующем окне хвост без префикса «sk-» или «eyJ» правило может
и не узнать.
"""
import re
import threading
import time
from collections import deque
from typing import Callable, List, Optional, Tuple

from presidio_analyzer import RecognizerResult

# Где резать, по убыванию предпочтения: абзац, строка, предложение, слово.
_SEPARATORS = ("\n\n", "\n", ". ", "! ", "? ", "; ", " ")
_SPACES = (" ", "\n", "\t")
_WORD_TAIL = re.compile(r"\S*")


class DeadlineExceeded(Exception):
    """Клиент перестал ждать: дальше анализировать незачем."""


def check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise DeadlineExceeded()


class FairSlots:
    """Семафор с очередью: освободившийся слот достаётся тому, кто ждёт дольше всех.

    У threading.Semaphore поток, только что отпустивший слот, тут же забирает его снова: длинный
    запрос, который анализирует кусок за куском, держал бы короткие в ожидании до их таймаута.
    Здесь каждый следующий кусок встаёт в конец очереди — запросы идут по очереди кусками.
    """

    def __init__(self, n: int):
        self._lock = threading.Lock()
        self._free = n
        self._waiters: deque = deque()

    def acquire(self, timeout: Optional[float] = None) -> bool:
        with self._lock:
            if self._free and not self._waiters:
                self._free -= 1
                return True
            granted = threading.Event()
            self._waiters.append(granted)
        if granted.wait(timeout):
            return True
        with self._lock:
            if granted.is_set():  # слот передали в последний момент
                return True
            self._waiters.remove(granted)
            return False

    def release(self) -> None:
        with self._lock:
            if self._waiters:
                self._waiters.popleft().set()  # слот переходит ждущему, минуя _free
            else:
                self._free += 1


def _cut(text: str, lo: int, hi: int) -> int:
    """Позиция разреза в (lo, hi]: после последнего разделителя самого сильного вида, иначе hi."""
    for sep in _SEPARATORS:
        i = text.rfind(sep, lo, hi)
        if i != -1:
            return i + len(sep)
    return hi


def chunk_spans(text: str, size: int, overlap: int) -> List[Tuple[int, int, int, int]]:
    """Куски текста: (начало окна, начало куска, конец куска, конец окна).

    Куски идут подряд и покрывают весь текст, каждый не длиннее size. Окно — кусок плюс overlap
    с каждой стороны, края окна сдвинуты к пробелу, чтобы не начинать с половины слова.
    """
    n = len(text)
    spans = []
    start = 0
    while True:
        end = n if n - start <= size else _cut(text, start + size // 2, start + size)
        win_start = max(0, start - overlap)
        if win_start > 0:
            found = [i for i in (text.find(c, win_start, start) for c in _SPACES) if i != -1]
            win_start = min(found) + 1 if found else win_start
        win_end = min(n, end + overlap)
        if win_end < n:
            found = [i for i in (text.rfind(c, end, win_end) for c in _SPACES) if i != -1]
            win_end = max(found) if found else win_end
        spans.append((win_start, start, end, win_end))
        if end >= n:
            return spans
        start = end


def _merge_windows(results: List[Tuple[int, RecognizerResult]]) -> List[RecognizerResult]:
    """Склеивает пересекающиеся сущности одного типа из разных окон в одну."""
    merged: List[Tuple[int, RecognizerResult]] = []
    for window, r in sorted(results, key=lambda x: (x[1].entity_type, x[1].start, x[1].end)):
        if merged:
            prev_window, prev = merged[-1]
            if prev.entity_type == r.entity_type and prev_window != window and r.start < prev.end:
                prev.end = max(prev.end, r.end)
                prev.score = max(prev.score, r.score)
                merged[-1] = (window, prev)
                continue
        merged.append((window, r))
    return [r for _, r in merged]


def analyze_in_chunks(
        text: str,
        analyze: Callable[[str], List[RecognizerResult]],
        deduplicate: Callable[[List[RecognizerResult]], List[RecognizerResult]],
        size: int,
        overlap: int,
        deadline: Optional[float] = None,
) -> List[RecognizerResult]:
    """analyze(text) для длинного текста: по кускам, позиции — в координатах всего текста."""
    check_deadline(deadline)
    if len(text) <= size:
        return analyze(text)
    found: List[Tuple[int, RecognizerResult]] = []
    for window, (win_start, start, end, win_end) in enumerate(chunk_spans(text, size, overlap)):
        check_deadline(deadline)
        for r in analyze(text[win_start:win_end]):
            r.start += win_start
            r.end += win_start
            if r.end == win_end < len(text):
                r.end = _WORD_TAIL.match(text, r.end).end()
            if r.end > start and r.start < end:
                found.append((window, r))
    return deduplicate(_merge_windows(found))
