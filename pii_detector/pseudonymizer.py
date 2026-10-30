"""Псевдонимизация ФИО с сохранением падежа.

Вместо метки <NAME_1> в текст подставляется правдоподобное ФИО того же рода и в том же падеже:
«письмо Петрову Ивану Сергеевичу» → «письмо Тарасову Денису Андреевичу». Модель пишет
грамматичный текст и не спотыкается о метки, а обратная замена знает все падежные формы
псевдонима: «Уважаемый Денис Андреевич» → «Уважаемый Иван Сергеевич».

Один и тот же человек во всех текстах запроса получает один псевдоним, в том числе если
упоминается по-разному («Петров Иван Сергеевич», «Ивану Сергеевичу», «И. С. Петров»).
Если упоминание не разбирается как русское ФИО, возвращается None — вызывающий код
подставляет обычную метку.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pymorphy3

CASES = ("nomn", "gent", "datv", "accs", "ablt", "loct")
ROLES = ("Surn", "Name", "Patr")

# Порядок слов, который считаем ФИО. Остальные сочетания — не ФИО (или ошибка NER).
_PATTERNS = {
    ("Surn", "Name", "Patr"), ("Name", "Patr", "Surn"),
    ("Surn", "Name"), ("Name", "Surn"), ("Name", "Patr"),
    ("Surn",), ("Name",),
}

# Пул псевдонимов: pymorphy3 знает эти слова как фамилии/имена/отчества и склоняет во всех
# падежах; в нижнем регистре они не совпадают с обычными словами («Орлов» — «орлов», поэтому нет).
_SURNAMES = (
    "Тарасов", "Беляев", "Ларионов", "Никитин", "Осипов", "Прохоров", "Рябов", "Савин",
    "Устинов", "Харитонов", "Шубин", "Юдин", "Якушев", "Гусев", "Лаврентьев", "Малахов",
    "Назаров", "Олейников", "Панкратов", "Родионов", "Сафонов",
)
_NAMES = {
    "masc": ("Денис", "Кирилл", "Олег", "Тимур", "Глеб", "Арсений", "Филипп", "Матвей", "Всеволод", "Ярослав"),
    "femn": ("Алина", "Ксения", "Полина", "Дарья", "Ульяна", "Кристина", "Олеся", "Милана", "Эльвира", "Таисия"),
}
_PATRONYMICS = {
    "masc": ("Андреевич", "Олегович", "Павлович", "Романович", "Кириллович", "Денисович", "Глебович", "Тимурович"),
    "femn": ("Андреевна", "Олеговна", "Павловна", "Романовна", "Кирилловна", "Денисовна", "Глебовна", "Тимуровна"),
}

_WORD_RE = re.compile(r"[А-ЯЁ][а-яё]+|[А-ЯЁ]{2,}")
_INITIAL_RE = re.compile(r"[А-ЯЁ]\.")
_TOKEN_RE = re.compile(r"[А-ЯЁ][а-яё]+|[А-ЯЁ]{2,}|[А-ЯЁ]\.|\S")


def _gender_ok(parse, gender: str) -> bool:
    return "ms-f" in parse.tag or parse.tag.gender == gender


def _style(sample: str, word: str) -> str:
    return word.upper() if sample.isupper() and len(sample) > 1 else word.capitalize()


@dataclass
class _Word:
    role: str
    parse: object  # pymorphy3 Parse исходного слова (для склонения оригинала)


@dataclass
class _Person:
    gender: str
    parts: Dict[str, _Word] = field(default_factory=dict)  # роль -> слово оригинала
    nomn: Dict[str, str] = field(default_factory=dict)  # роль -> форма оригинала в им. п.
    initials: Dict[str, str] = field(default_factory=dict)  # роль (Name/Patr) -> инициал
    fake: Dict[str, str] = field(default_factory=dict)  # роль -> псевдоним в им. п.


class Pseudonymizer:
    """Состояние одного запроса: реестр людей и выданных псевдонимов."""

    _morph: Optional[pymorphy3.MorphAnalyzer] = None

    def __init__(self, texts: List[str] = ()):
        if Pseudonymizer._morph is None:
            Pseudonymizer._morph = pymorphy3.MorphAnalyzer()
        self.m = Pseudonymizer._morph
        self.people: List[_Person] = []
        self.mentions: List[Tuple[str, str]] = []  # (псевдоним как в тексте, оригинал как в тексте)
        self._text_words = set(re.findall(r"[а-яё]+", " ".join(texts).casefold()))

    # ── разбор упоминания ────────────────────────────────────────────────────

    def _analyze(self, span: str):
        """-> (gender, case, [(token, role|'init:<role>', parse|None)]) или None."""
        tokens = _TOKEN_RE.findall(span)
        if not tokens or len(tokens) > 5:
            return None
        words = [t for t in tokens if _WORD_RE.fullmatch(t)]
        inits = [t for t in tokens if _INITIAL_RE.fullmatch(t)]
        if len(words) + len(inits) != len(tokens) or not words or len(words) > 3 or len(inits) > 2:
            return None
        if inits and len(words) != 1:
            return None  # «И. С. Петров» / «Петров И.С.» — одна фамилия и инициалы

        best = None
        for gender in ("masc", "femn"):
            for case in CASES:
                choice, score = [], 1.0
                for w in words:
                    cands = [p for p in self.m.parse(w.lower())
                             if {"Surn", "Name", "Patr"} & set(p.tag.grammemes)
                             and p.tag.case == case and _gender_ok(p, gender)
                             and p.tag.number in ("sing", None)]
                    if not cands:
                        break
                    p = max(cands, key=lambda x: x.score)
                    role = next(r for r in ROLES if r in p.tag)
                    choice.append((w, role, p))
                    score *= p.score
                else:
                    roles = tuple(r for _, r, _ in choice)
                    if inits:
                        if roles != ("Surn",):
                            continue
                    elif roles not in _PATTERNS:
                        continue
                    if best is None or score > best[0]:
                        best = (score, gender, case, choice)
        if best is None:
            return None
        _, gender, case, choice = best
        if inits:
            init_roles = ["init:Name", "init:Patr"][:len(inits)]
            it = iter(zip(inits, init_roles))
            items = []
            for t in tokens:
                if _INITIAL_RE.fullmatch(t):
                    tok, r = next(it)
                    items.append((tok, r, None))
                else:
                    items.append(choice[0])
            return gender, case, items
        return gender, case, choice

    def _nomn(self, parse, role: str) -> Optional[str]:
        f = parse.inflect({"nomn", "sing"})
        return f.word.capitalize() if f else None

    # ── реестр людей ─────────────────────────────────────────────────────────

    def _find_or_add(self, gender: str, items) -> Optional[_Person]:
        nomn, parts, initials = {}, {}, {}
        for tok, role, parse in items:
            if role.startswith("init:"):
                initials[role[5:]] = tok[0]
                continue
            n = self._nomn(parse, role)
            if n is None:
                return None
            nomn[role], parts[role] = n, _Word(role, parse)
            if role in ("Name", "Patr"):
                initials[role] = n[0]

        for person in self.people:
            if person.gender != gender:
                continue
            if any(person.nomn.get(r) not in (None, v) for r, v in nomn.items()):
                continue
            if any(person.initials.get(r) not in (None, v) for r, v in initials.items()):
                continue
            if not (set(person.nomn) & set(nomn)):
                continue  # «Иван» и «Петров» порознь не склеиваем
            for r, v in nomn.items():
                person.nomn.setdefault(r, v)
                person.parts.setdefault(r, parts[r])
            for r, v in initials.items():
                person.initials.setdefault(r, v)
            return person

        person = _Person(gender=gender, parts=parts, nomn=nomn, initials=initials)
        if not self._assign_fake(person):
            return None
        self.people.append(person)
        return person

    def _assign_fake(self, person: _Person) -> bool:
        used = {v for p in self.people for v in p.fake.values()}
        names, patrs = _NAMES[person.gender], _PATRONYMICS[person.gender]
        k = len(self.people)

        def free(word: str, role: str) -> bool:
            if word in used:
                return False
            forms = {self._inflect(word, role, person.gender, c) for c in CASES}
            return None not in forms and not ({f.casefold() for f in forms} & self._text_words)

        fem = "а" if person.gender == "femn" else ""
        surn = next((s + fem for s in _SURNAMES[k:] + _SURNAMES[:k] if free(s + fem, "Surn")), None)
        name = next((n for n in names[k:] + names[:k] if free(n, "Name")), None)
        patr = next((p for p in patrs[k:] + patrs[:k] if free(p, "Patr")), None)
        if not (surn and name and patr):
            return False
        person.fake = {"Surn": surn, "Name": name, "Patr": patr}
        return True

    # ── формы ────────────────────────────────────────────────────────────────

    def _inflect(self, word: str, role: str, gender: str, case: str) -> Optional[str]:
        for p in self.m.parse(word):
            if role in p.tag and _gender_ok(p, gender) and p.tag.case == "nomn":
                f = p.inflect({case, "sing"})
                return f.word.capitalize() if f else None
        return None

    def _fake_form(self, person: _Person, role: str, case: str) -> Optional[str]:
        return self._inflect(person.fake[role], role, person.gender, case)

    def _orig_form(self, person: _Person, role: str, case: str) -> Optional[str]:
        f = person.parts[role].parse.inflect({case, "sing"})
        return f.word.capitalize() if f else None

    # ── API ──────────────────────────────────────────────────────────────────

    def mask(self, span: str) -> Optional[str]:
        """Псевдоним для упоминания в том же падеже или None, если это не ФИО."""
        parsed = self._analyze(span)
        if parsed is None:
            return None
        gender, case, items = parsed
        person = self._find_or_add(gender, items)
        if person is None:
            return None
        out = []
        for tok, role, _ in items:
            if role.startswith("init:"):
                out.append(person.fake[role[5:]][0] + ".")
            else:
                form = self._fake_form(person, role, case)
                if form is None:
                    return None
                out.append(_style(tok, form))
        fake = _join_like(span, out)
        self.mentions.append((fake, span))
        return fake

    def restore_pairs(self) -> List[Tuple[str, str]]:
        """Пары (псевдоним → оригинал) для всех падежей и распространённых способов записи ФИО."""
        pairs: List[Tuple[str, str]] = list(self.mentions)
        for person in self.people:
            have = set(person.parts)
            templates = [t for t in (
                ("Surn", "Name", "Patr"), ("Name", "Patr", "Surn"), ("Surn", "Name"), ("Name", "Surn"),
                ("Name", "Patr"), ("Surn",), ("Name",),
            ) if set(t) <= have]
            for case in CASES:
                fk = {r: self._fake_form(person, r, case) for r in have}
                og = {r: self._orig_form(person, r, case) for r in have}
                if any(v is None for v in list(fk.values()) + list(og.values())):
                    continue
                for t in templates:
                    pairs.append((" ".join(fk[r] for r in t), " ".join(og[r] for r in t)))
                if "Surn" in have and "Name" in person.initials:
                    fi = [person.fake["Name"][0] + "."]
                    oi = [person.initials["Name"] + "."]
                    if "Patr" in person.initials:
                        fi.append(person.fake["Patr"][0] + ".")
                        oi.append(person.initials["Patr"] + ".")
                    for sep in (" ", ""):
                        f_in, o_in = sep.join(fi), sep.join(oi)
                        pairs.append((f"{f_in} {fk['Surn']}", f"{o_in} {og['Surn']}"))
                        pairs.append((f"{fk['Surn']} {f_in}", f"{og['Surn']} {o_in}"))
        return pairs


def _join_like(span: str, words: List[str]) -> str:
    """Собирает псевдоним, сохраняя разделители исходного упоминания («И. С. Петров», «Петров И.С.»)."""
    tokens = _TOKEN_RE.findall(span)
    out, pos = [], 0
    for tok, new in zip(tokens, words):
        i = span.index(tok, pos)
        out.append(span[pos:i])
        out.append(new)
        pos = i + len(tok)
    out.append(span[pos:])
    return "".join(out)
