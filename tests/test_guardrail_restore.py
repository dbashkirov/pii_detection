"""Обратная замена в guardrail LiteLLM: целиком и в потоке при любой нарезке на чанки.

Нужен установленный litellm — проще всего в контейнере LiteLLM e2e-стенда:
    docker compose -p pii-after exec -T -e PII_GUARDRAIL=/app/pii_guardrail.py litellm \
        python - < ../../tests/test_guardrail_restore.py
"""
import importlib.util
import os
import random

try:
    import pytest

    pytest.importorskip("litellm")
except ImportError:  # запуск скриптом, без pytest
    pass

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__", ".")))
_PATH = os.environ.get("PII_GUARDRAIL", os.path.join(_HERE, "..", "docker", "litellm", "pii_guardrail.py"))
_spec = importlib.util.spec_from_file_location("pii_guardrail", _PATH)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

PAIRS = [
    ["Беляеву Кириллу Олеговичу", "Петрову Ивану Сергеевичу"],
    ["Кирилл Олегович", "Иван Сергеевич"],
    ["Кирилл", "Иван"],
    ["Беляев", "Петров"],
    ["Беляева", "Петрова"],
    ["<EMAIL_1>", "a.sidorova@example.ru"],
    ["[EMAIL_1]", "a.sidorova@example.ru"],
    ["EMAIL_1", "a.sidorova@example.ru"],
]
TEXT = ("Уважаемый Кирилл Олегович! Письмо для Беляеву Кириллу Олеговичу. Беляева нет, Беляевой тоже, "
        "Кириллица не имя. Пишите на <EMAIL_1> или [EMAIL_1], EMAIL_1.Кирилл")
EXPECTED = ("Уважаемый Иван Сергеевич! Письмо для Петрову Ивану Сергеевичу. Петрова нет, Беляевой тоже, "
            "Кириллица не имя. Пишите на a.sidorova@example.ru или a.sidorova@example.ru, a.sidorova@example.ru.Иван")


def test_restore_whole():
    assert g.Restorer(PAIRS).restore(TEXT) == EXPECTED


def test_restore_stream_any_chunking():
    r = g.Restorer(PAIRS)
    rnd = random.Random(1)
    for _ in range(500):
        s, out, i = r.stream(), [], 0
        while i < len(TEXT):
            n = rnd.randint(1, 12)
            out.append(s.feed(TEXT[i:i + n]))
            i += n
        out.append(s.flush())
        assert "".join(out) == EXPECTED


def test_stream_emits_early():
    """Поток не копится до конца: отдаётся всё, кроме хвоста длиной в самую длинную замену."""
    r = g.Restorer(PAIRS)
    s = r.stream()
    emitted = "".join(s.feed(w + " ") for w in ("слово",) * 40)
    assert len(emitted) >= 40 * 6 - (r.max_len + 1)


def test_any_single_whitespace_in_keys():
    """gpt-oss пишет инициалы через узкий неразрывный пробел: «Беляев\u202fК.\u202fО.»."""
    r = g.Restorer([["Беляев К. О.", "Петров И. С."], ["Беляев", "Петров"]])
    assert r.restore("Подпись: Беляев\u202fК.\u202fО.") == "Подпись: Петров И. С."
    s = r.stream()
    text = "Подпись: Беляев\u00a0К.\u202fО. и ещё немного текста"
    assert "".join(s.feed(ch) for ch in text) + s.flush() == "Подпись: Петров И. С. и ещё немного текста"


def test_no_pairs_passthrough():
    s = g.Restorer([]).stream()
    assert s.feed("abc") == "abc" and s.flush() == ""


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
