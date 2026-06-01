#!/usr/bin/env python3
"""
sample_next.py — случайная спецификация следующего примера для PII-датасета.

Использование:
    python data_gen/sample_next.py            # случайная спека
    python data_gen/sample_next.py 42         # фиксированный seed
    python data_gen/sample_next.py --stats    # целевые вероятности

Вывод: JSON в stdout. Claude читает его и генерирует один пример по спеке.
"""

import random

from faker import Faker

fake = Faker("ru_RU")


def weighted_choice(probs: dict) -> str:
    keys = list(probs.keys())
    weights = list(probs.values())
    return random.choices(keys, weights=weights, k=1)[0]


def normalize(d: dict) -> dict:
    total = sum(d.values())
    return {k: v / total for k, v in d.items()}


# ---------------------------------------------------------------------------
# Домены и ID-префиксы
# ---------------------------------------------------------------------------

DOMAIN_PREFIXES = {
    "DELIVERY": "del_synth",
    "DIALOG": "dialog_synth",
    "AUTO": "auto_synth",
    "BANK": "bank_synth",
    "HR": "hr_synth",
    "RE": "re_synth",
    "TELECOM": "st_synth",
    "NAME": "name_synth",
    "ADDRESS": "addr_synth",
    "MEDICAL": "med_synth",
    "GOV": "gov_synth",
    "LEGAL": "legal_synth",
    "SOCIAL": "social_synth",
}

# Веса сервисных доменов (для BOTH, NAME_CONTEXT, NEGATIVE)
# Целевые кол-ва: DIALOG 1000, DELIVERY 800, остальные 450-650
SERVICE_DOMAIN_WEIGHTS = normalize({
    "DIALOG": 0.14,
    "DELIVERY": 0.13,
    "AUTO": 0.09,
    "BANK": 0.09,
    "HR": 0.08,
    "RE": 0.07,
    "TELECOM": 0.09,
    "MEDICAL": 0.07,
    "GOV": 0.08,
    "LEGAL": 0.08,
    "SOCIAL": 0.08,
})

# Для NAME_ONLY: добавляем изолированный домен NAME
NAME_ONLY_DOMAIN_WEIGHTS = normalize({
    **SERVICE_DOMAIN_WEIGHTS,
    "NAME": 0.12,
})

# Для ADDRESS_ONLY: добавляем изолированный домен ADDRESS
ADDR_ONLY_DOMAIN_WEIGHTS = normalize({
    **SERVICE_DOMAIN_WEIGHTS,
    "ADDRESS": 0.12,
})

# ---------------------------------------------------------------------------
# Тип примера
# NAME_ONLY 20% | ADDRESS_ONLY 20% | BOTH 30% | NEGATIVE 25% | NAME_CONTEXT 5%
# ---------------------------------------------------------------------------

ENTITY_TYPE_PROBS = {
    "NAME_ONLY": 0.20,
    "ADDRESS_ONLY": 0.20,
    "BOTH": 0.30,
    "NEGATIVE": 0.25,
    "NAME_CONTEXT": 0.05,
}

# ---------------------------------------------------------------------------
# Формы имени и адреса
# ---------------------------------------------------------------------------

NAME_FORM_PROBS = {
    "NAME_FI": 0.25,
    "NAME_IF": 0.20,
    "NAME_FIO": 0.15,
    "NAME_IFO": 0.15,
    "NAME_IO": 0.07,
    "NAME_FI_GEN": 0.05,
    "NAME_INITF": 0.025,
    "NAME_FINIT": 0.025,
    "NAME_I": 0.03,
    "NAME_IF_GEN": 0.03,
    "NAME_FIO_GEN": 0.01,
    "NAME_FIO_DAT": 0.01,
}

ADDR_FORM_PROBS = {
    "ADDR_FULL": 0.20,
    "ADDR_CSH": 0.20,
    "ADDR_SHA": 0.15,
    "ADDR_SH": 0.15,
    "ADDR_SHAP": 0.10,
    "ADDR_ABBR": 0.05,
    "ADDR_WORDS": 0.05,
    "ADDR_REGION": 0.05,
    "ADDR_LOW": 0.03,
    "ADDR_INDEX": 0.02,
}

# ---------------------------------------------------------------------------
# Стиль и длина
# ---------------------------------------------------------------------------

STYLE_PROBS = {
    "formal": 0.35,
    "informal": 0.35,
    "mixed": 0.30,
}

LENGTH_PROBS = {
    "short": 0.20,
    "medium": 0.55,
    "long": 0.25,
}

POSITION_PROBS = {
    "beginning": 0.30,
    "middle": 0.30,
    "end": 0.25,
    "mixed": 0.15,
}

# При multi_entity вес mixed выше — сущности естественно расходятся по тексту
POSITION_PROBS_MULTI = {
    "beginning": 0.18,
    "middle": 0.20,
    "end": 0.17,
    "mixed": 0.45,
}

# ---------------------------------------------------------------------------
# Эмоциональный тон (expression)
# ---------------------------------------------------------------------------

EXPRESSION_PROBS = {
    "joy": 0.08,  # радость, восторг, благодарность
    "neutral": 0.40,  # нейтральный, деловой тон
    "irritated": 0.14,  # раздражение, недовольство
    "sad": 0.10,  # грусть, расстроенность
    "urgent": 0.12,  # срочность, паника
    "worried": 0.10,  # тревога, беспокойство
    "rage": 0.06,  # ярость, мат обязателен
}

# ---------------------------------------------------------------------------
# Негативные примеры
# ---------------------------------------------------------------------------

NEG_CATEGORY_PROBS = {
    "professions_roles": 0.25,
    "city_homonyms": 0.15,
    "memorial_streets": 0.15,
    "address_fragments": 0.15,
    "email_names": 0.10,
    "neutral_service": 0.15,
    "org_names": 0.05,
}

# ---------------------------------------------------------------------------
# Edge cases (вероятность 20% среди позитивных)
# ---------------------------------------------------------------------------

EDGE_CASE_PROB = 0.20

EDGE_CASES_NAME = [
    "hyphenated_surname",
    "non_slavic_name",
    "name_with_title",
    "initials_no_space",
    "name_in_brackets",
    "declined_full_fio",
]

EDGE_CASES_ADDR = [
    "abbr_no_dot",
    "complex_house_number",
    "no_space_after_dot",
    "lowercase_city",
    "typo_in_addr",
    "village_vs_house_d",
]


# ---------------------------------------------------------------------------
# Сэмплирование имени
# ---------------------------------------------------------------------------

def sample_name(edge_case=None):
    gender = random.choice(["M", "F"])

    if edge_case == "hyphenated_surname":
        if gender == "M":
            surname = f"{fake.last_name_male()}-{fake.last_name_male()}"
            firstname, patronymic = fake.first_name_male(), fake.middle_name_male()
        else:
            surname = f"{fake.last_name_female()}-{fake.last_name_female()}"
            firstname, patronymic = fake.first_name_female(), fake.middle_name_female()
    else:
        if gender == "M":
            surname = fake.last_name_male()
            firstname = fake.first_name_male()
            patronymic = fake.middle_name_male()
        else:
            surname = fake.last_name_female()
            firstname = fake.first_name_female()
            patronymic = fake.middle_name_female()

    return {
        "gender": gender,
        "surname": surname,
        "firstname": firstname,
        "patronymic": patronymic,
        "full_fio": f"{surname} {firstname} {patronymic}",
    }


# ---------------------------------------------------------------------------
# Сэмплирование адреса
# ---------------------------------------------------------------------------

_HOUSE_SUFFIXES = ["а", "б", "в", "/2", "/3", "к2", "к3", " корп. 2", " стр. 1"]

_TYPO_MAP = {
    "подъезд": "подьезд",
    "квартира": "кв-ра",
    "улица": "улца",
    "переулок": "переулк",
}


def _apply_addr_edge(city, st_type, st_name, house, edge_case):
    extra = {}
    if edge_case == "abbr_no_dot":
        st_type = st_type.rstrip(".")
    elif edge_case == "complex_house_number":
        house = house + random.choice(_HOUSE_SUFFIXES)
    elif edge_case == "lowercase_city":
        city = city.lower()
        st_type = st_type.lower()
        st_name = st_name.lower()
    elif edge_case == "village_vs_house_d":
        city = "д. " + fake.city_name()
        house = str(fake.random_int(1, 50))
    elif edge_case == "no_space_after_dot":
        extra["no_space"] = True
    elif edge_case == "typo_in_addr":
        extra["typo"] = True
    return city, st_type, st_name, house, extra


def _compose(addr_form, city, city_abbr, st_type, st_name, house, apt, entrance, postcode, region, extra):
    no_space = extra.get("no_space", False)

    def sep(s):
        return s.replace(". ", ".") if no_space else s

    mapping = {
        "ADDR_FULL": f"г. {city}, {sep(st_type + ' ')}{st_name}, д. {house}, кв. {apt}",
        "ADDR_CSH": f"{city}, {sep(st_type + ' ')}{st_name} {house}",
        "ADDR_SHA": f"{sep(st_type + ' ')}{st_name} {house} кв. {apt}",
        "ADDR_SH": f"{sep(st_type + ' ')}{st_name} {house}",
        "ADDR_SHAP": f"{sep(st_type + ' ')}{st_name} {house} кв. {apt} подъезд {entrance}",
        "ADDR_ABBR": f"{city_abbr}, {st_name} {house} кв {apt}",
        "ADDR_WORDS": f"улица {st_name} дом {house} квартира {apt}",
        "ADDR_REGION": f"{region}, {city}, {sep(st_type + ' ')}{st_name} {house}",
        "ADDR_LOW": f"{st_type} {st_name} {house} кв. {apt}".lower(),
        "ADDR_INDEX": f"{postcode}, г. {city}, {sep(st_type + ' ')}{st_name}, д. {house}",
    }
    result = mapping.get(addr_form, f"{st_type} {st_name} {house}")

    if extra.get("typo"):
        for correct, wrong in _TYPO_MAP.items():
            if correct in result:
                result = result.replace(correct, wrong, 1)
                break

    return result


def sample_address(addr_form, edge_case=None):
    city = fake.city_name()
    st_type = fake.street_suffix()
    st_name = fake.street_title()
    house = str(fake.random_int(1, 200))
    apt = str(fake.random_int(1, 400))
    entrance = str(fake.random_int(1, 8))
    postcode = fake.postcode()
    region = fake.region()
    city_abbr = city[:3].lower()

    city, st_type, st_name, house, extra = _apply_addr_edge(city, st_type, st_name, house, edge_case)

    address_string = _compose(
        addr_form, city, city_abbr, st_type, st_name, house, apt, entrance, postcode, region, extra
    )

    return {
        "city": city,
        "city_abbr": city_abbr,
        "region": region,
        "street_type": st_type,
        "street_name": st_name,
        "house": house,
        "apartment": apt,
        "entrance": entrance,
        "postal_code": postcode,
        "address_string": address_string,
    }


# ---------------------------------------------------------------------------
# Edge case picker
# ---------------------------------------------------------------------------

def _pick_edge_case(has_name, has_addr):
    if random.random() >= EDGE_CASE_PROB:
        return None
    candidates = []
    if has_name:
        candidates.extend(EDGE_CASES_NAME)
    if has_addr:
        candidates.extend(EDGE_CASES_ADDR)
    return random.choice(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def sample():
    entity_type = weighted_choice(ENTITY_TYPE_PROBS)

    if entity_type == "NEGATIVE":
        domain = weighted_choice(SERVICE_DOMAIN_WEIGHTS)
        neg_category = weighted_choice(NEG_CATEGORY_PROBS)
        edge_case = None
        id_prefix = "neg_synth"
        name_form = None
        addr_form = None
    elif entity_type == "NAME_ONLY":
        domain = weighted_choice(NAME_ONLY_DOMAIN_WEIGHTS)
        neg_category = None
        edge_case = _pick_edge_case(has_name=True, has_addr=False)
        id_prefix = DOMAIN_PREFIXES[domain]
        name_form = weighted_choice(NAME_FORM_PROBS)
        addr_form = None
    elif entity_type == "ADDRESS_ONLY":
        domain = weighted_choice(ADDR_ONLY_DOMAIN_WEIGHTS)
        neg_category = None
        edge_case = _pick_edge_case(has_name=False, has_addr=True)
        id_prefix = DOMAIN_PREFIXES[domain]
        name_form = None
        addr_form = weighted_choice(ADDR_FORM_PROBS)
    elif entity_type == "BOTH":
        domain = weighted_choice(SERVICE_DOMAIN_WEIGHTS)
        neg_category = None
        edge_case = _pick_edge_case(has_name=True, has_addr=True)
        id_prefix = DOMAIN_PREFIXES[domain]
        name_form = weighted_choice(NAME_FORM_PROBS)
        addr_form = weighted_choice(ADDR_FORM_PROBS)
    else:  # NAME_CONTEXT
        domain = weighted_choice(SERVICE_DOMAIN_WEIGHTS)
        neg_category = None
        edge_case = _pick_edge_case(has_name=True, has_addr=False)
        id_prefix = DOMAIN_PREFIXES[domain]
        name_form = weighted_choice(NAME_FORM_PROBS)
        addr_form = None

    style = weighted_choice(STYLE_PROBS)
    length = weighted_choice(LENGTH_PROBS)
    expression = weighted_choice(EXPRESSION_PROBS)

    has_typo = (entity_type != "NEGATIVE") and random.random() < 0.05
    multi_entity = (entity_type in ("NAME_ONLY", "ADDRESS_ONLY", "BOTH")) and random.random() < 0.12

    if entity_type == "NEGATIVE":
        position = None
    elif multi_entity:
        position = weighted_choice(POSITION_PROBS_MULTI)
    else:
        position = weighted_choice(POSITION_PROBS)

    # Данные
    name_edge = edge_case if edge_case in EDGE_CASES_NAME else None
    addr_edge = edge_case if edge_case in EDGE_CASES_ADDR else None

    name_data = sample_name(name_edge) if name_form is not None else None
    addr_data = sample_address(addr_form, addr_edge) if addr_form is not None else None

    name_data_2 = None
    addr_data_2 = None
    if multi_entity:
        if entity_type == "NAME_ONLY":
            name_data_2 = sample_name()
        elif entity_type == "ADDRESS_ONLY":
            addr_data_2 = sample_address(addr_form)
        elif entity_type == "BOTH":
            if random.random() < 0.5:
                name_data_2 = sample_name()
            else:
                addr_data_2 = sample_address(addr_form)

    result = {
        "entity_type": entity_type,
        "domain": domain,
        "name_form": name_form,
        "addr_form": addr_form,
        "style": style,
        "length": length,
        "expression": expression,
        "neg_category": neg_category,
        "edge_case": edge_case,
        "has_typo": has_typo,
        "multi_entity": multi_entity,
        "position": position,
        "id_prefix": id_prefix,
    }

    if name_data is not None:
        result["name_data"] = name_data
    if addr_data is not None:
        result["addr_data"] = addr_data
    if name_data_2 is not None:
        result["name_data_2"] = name_data_2
    if addr_data_2 is not None:
        result["addr_data_2"] = addr_data_2

    return result
