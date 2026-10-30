"""Маскирование запроса и псевдонимизация ФИО. Детектор подменён: нужны только pymorphy3 и presidio."""
import re

from presidio_analyzer import RecognizerResult

from pii_detector.masking import mask_texts
from pii_detector.pseudonymizer import Pseudonymizer

PATTERNS = {
    "NAME": r"Петров[а-я]* Иван[а-я]* Сергеевич[а-я]*|Сидоров[а-я]* Анн[а-я]* Викторовн[а-я]*",
    "EMAIL": r"[\w.]+@[\w.]+\w",
    "PHONE_NUMBER": r"\+7 \d{3} \d{3}-\d{2}-\d{2}",
    "BANK_CARD_NUMBER": r"4111 1111 1111 1111",
    "ADDRESS": r"Сухой Лог добыто",
}


class FakeDetector:
    def analyze(self, text, language="en", deadline=None):
        return [RecognizerResult(t, m.start(), m.end(), 0.9)
                for t, p in PATTERNS.items() for m in re.finditer(p, text)]


def restore(text, pairs):
    for fake, orig in sorted(pairs, key=lambda p: -len(p[0])):
        text = re.sub(r"(?<!\w)" + re.escape(fake) + r"(?!\w)", orig, text)
    return text


def test_pseudonym_keeps_case_and_gender():
    p = Pseudonymizer()
    assert p.mask("Петрову Ивану Сергеевичу").split()[0].endswith("у")  # дательный
    assert p.mask("Сидоровой Анны Викторовны").split()[0].endswith("ой")  # женский род, родительный


def test_same_person_same_pseudonym_any_case():
    p = Pseudonymizer()
    a = p.mask("Петров Иван Сергеевич")
    b = p.mask("Петрову Ивану Сергеевичу")
    c = p.mask("И. С. Петров")
    assert a.split()[0] in b and a.split()[0][:5] == c.split()[-1][:5]
    assert len(p.people) == 1


def test_restore_pairs_cover_other_cases():
    p = Pseudonymizer()
    p.mask("Петрову Ивану Сергеевичу")
    pairs = dict(p.restore_pairs())
    # модель обращается по имени-отчеству в именительном — оригинал тоже в именительном
    nomn = [k for k in pairs if pairs[k] == "Иван Сергеевич"]
    assert nomn, pairs


def test_not_a_name_returns_none():
    p = Pseudonymizer()
    assert p.mask("John Smith") is None
    assert p.mask("Ленских") is None


def test_request_wide_numbering_and_roles():
    texts = ["Руководитель — Сидорова Анна Викторовна.", "Понял.",
             "Исполнитель — Петров Иван Сергеевич, тел. +7 914 123-45-67.",
             "Ещё раз: тел. +7 914 123-45-67, почта a.sidorova@example.ru, звоните Петрову."]
    r = mask_texts(FakeDetector(), texts)
    assert not any("Сидоров" in t or "Петров" in t for t in r.texts)  # в т.ч. «Петрову», которого нет в разметке
    assert r.texts[2].count("<PHONE_NUMBER_1>") == 1 and r.texts[3].count("<PHONE_NUMBER_1>") == 1
    lead = r.texts[0].split("— ")[1].rstrip(".")
    doer = r.texts[2].split("— ")[1].split(",")[0]
    assert lead != doer
    assert [restore(t, r.restore) for t in r.texts] == texts


def test_block_and_allow():
    r = mask_texts(FakeDetector(), ["карта 4111 1111 1111 1111"], policy={"BANK_CARD_NUMBER": "BLOCK"})
    assert r.blocked == ["BANK_CARD_NUMBER"] and r.texts == []
    r = mask_texts(FakeDetector(), ["На месторождении Сухой Лог добыто 1520 кг"], allow_list=["Сухой Лог"])
    assert r.texts == ["На месторождении Сухой Лог добыто 1520 кг"]


def test_placeholder_variants_restored():
    r = mask_texts(FakeDetector(), ["почта a.sidorova@example.ru"], policy={"NAME": "MASK"})
    assert r.texts == ["почта <EMAIL_1>"]
    assert restore("Пишите на [EMAIL_1] или EMAIL_1", r.restore) == "Пишите на a.sidorova@example.ru или a.sidorova@example.ru"
