import json

# SPECS 4491-4500

chat_4491 = [
    {"role": "user", "content": "Привет, можешь подсказать по заказу?"},
    {"role": "assistant", "content": "Конечно, куда доставка? г. Вуктыл, пер. Радужная, д. 94, кв. 277 — верно?"},
    {"role": "user", "content": "Да, всё точно."},
]

chat_4496 = [
    {"role": "user", "content": "Почему до сих пор не обработана моя заявка?"},
    {"role": "user", "content": "Александра Ильинична Терентьева, подавала ещё неделю назад!"},
    {"role": "assistant", "content": "Прошу прощения за задержку, проверяю информацию."},
]

records = [
    # 4491 — ADDRESS_ONLY DIALOG ADDR_FULL informal medium neutral position=middle
    {"id": "dialog_synth_4491", "domain": "DIALOG", "entity_type": "ADDRESS_ONLY", "name_form": None, "addr_form": "ADDR_FULL",
     "style": "informal", "length": "medium", "expression": "neutral", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "middle",
     "text": json.dumps(chat_4491, ensure_ascii=False),
     "entities": [{"text": "г. Вуктыл, пер. Радужная, д. 94, кв. 277", "type": "ADDRESS"}]},

    # 4492 — BOTH BANK NAME_FIO ADDR_CSH informal long neutral position=mixed
    {"id": "bank_synth_4492", "domain": "BANK", "entity_type": "BOTH", "name_form": "NAME_FIO", "addr_form": "ADDR_CSH",
     "style": "informal", "length": "long", "expression": "neutral", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "mixed",
     "text": "Заявка на ипотеку подана через мобильное приложение банка. Все документы загружены и проверены автоматической системой. Моисей Германович Красильников указан основным заёмщиком в анкете. Адрес объекта залога — Усть-Баргузин, пр. Березовая 169, прописан в кадастровых документах.",
     "entities": [{"text": "Моисей Германович Красильников", "type": "NAME"}, {"text": "Усть-Баргузин, пр. Березовая 169", "type": "ADDRESS"}]},

    # 4493 — NAME_ONLY SOCIAL NAME_FI informal medium worried edge_case=hyphenated_surname position=middle
    {"id": "social_synth_4493", "domain": "SOCIAL", "entity_type": "NAME_ONLY", "name_form": "NAME_FI", "addr_form": None,
     "style": "informal", "length": "medium", "expression": "worried", "neg_category": None,
     "edge_case": "hyphenated_surname", "has_typo": False, "multi_entity": False, "position": "middle",
     "text": "В чате класса все обсуждают завтрашнюю контрольную. Агата Жукова-Григорьева переживает, что не успела повторить тему. Надеюсь, всё обойдётся.",
     "entities": [{"text": "Агата Жукова-Григорьева", "type": "NAME"}]},

    # 4494 — NEGATIVE GOV professions_roles formal medium joy
    {"id": "neg_synth_4494", "domain": "GOV", "entity_type": "NEGATIVE", "name_form": None, "addr_form": None,
     "style": "formal", "length": "medium", "expression": "joy", "neg_category": "professions_roles",
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": None,
     "text": "Специалист отдела приёма граждан провёл консультацию быстро и доброжелательно. Очень приятно, когда обращение в госучреждение проходит так гладко.",
     "entities": []},

    # 4495 — NAME_ONLY HR NAME_FI mixed long neutral position=mixed
    {"id": "hr_synth_4495", "domain": "HR", "entity_type": "NAME_ONLY", "name_form": "NAME_FI", "addr_form": None,
     "style": "mixed", "length": "long", "expression": "neutral", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "mixed",
     "text": "Собеседование назначено на следующую неделю в офисе компании. Алла Константинова прислала резюме и сопроводительное письмо заранее. Отдел кадров уже согласовал время встречи с руководителем. Алла Константинова подтвердила своё участие по электронной почте.",
     "entities": [{"text": "Алла Константинова", "type": "NAME"}]},

    # 4496 — NAME_ONLY DIALOG NAME_FIO formal medium irritated position=middle
    {"id": "dialog_synth_4496", "domain": "DIALOG", "entity_type": "NAME_ONLY", "name_form": "NAME_FIO", "addr_form": None,
     "style": "formal", "length": "medium", "expression": "irritated", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "middle",
     "text": json.dumps(chat_4496, ensure_ascii=False),
     "entities": [{"text": "Александра Ильинична Терентьева", "type": "NAME"}]},

    # 4497 — NAME_ONLY AUTO NAME_FI informal medium sad position=middle
    {"id": "auto_synth_4497", "domain": "AUTO", "entity_type": "NAME_ONLY", "name_form": "NAME_FI", "addr_form": None,
     "style": "informal", "length": "medium", "expression": "sad", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "middle",
     "text": "Машину разбили на парковке у дома. Зоя Захарова очень расстроена, ведь авто было совсем новым. Страховая обещала перезвонить позже.",
     "entities": [{"text": "Зоя Захарова", "type": "NAME"}]},

    # 4498 — NAME_ONLY TELECOM NAME_FI_GEN formal long sad position=end
    {"id": "st_synth_4498", "domain": "TELECOM", "entity_type": "NAME_ONLY", "name_form": "NAME_FI_GEN", "addr_form": None,
     "style": "formal", "length": "long", "expression": "sad", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "end",
     "text": "Заявка на отключение услуги была подана через личный кабинет. Все технические работы проведены в стандартные сроки. Оператор связи зафиксировал расторжение договора в системе. Очень жаль, что пришлось отказаться от услуг именно для Евгении Дроздовой.",
     "entities": [{"text": "Евгении Дроздовой", "type": "NAME"}]},

    # 4499 — NEGATIVE DELIVERY neutral_service informal medium neutral
    {"id": "neg_synth_4499", "domain": "DELIVERY", "entity_type": "NEGATIVE", "name_form": None, "addr_form": None,
     "style": "informal", "length": "medium", "expression": "neutral", "neg_category": "neutral_service",
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": None,
     "text": "Заказ подтверждён, всё ок. Курьер выехал, скоро будет на месте.",
     "entities": []},

    # 4500 — NAME_CONTEXT HR NAME_IFO formal long joy position=end
    {"id": "hr_synth_4500", "domain": "HR", "entity_type": "NAME_CONTEXT", "name_form": "NAME_IFO", "addr_form": None,
     "style": "formal", "length": "long", "expression": "joy", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "end",
     "text": "Собеседование прошло в тёплой и доброжелательной атмосфере. Кандидат показал отличные профессиональные навыки и опыт работы. Руководитель отдела остался очень довольным результатами встречи. Уведомление о приёме на работу будет получено по адресу электронной почты subbotina.oksana@mail.ru, который указала Субботина Оксана Анатольевна.",
     "entities": [{"text": "Субботина Оксана Анатольевна", "type": "NAME"}]},
]

for r in records:
    for e in r["entities"]:
        assert e["text"] in r["text"], f"FAIL {r['id']}: '{e['text']}' not in text"

with open("output/synthetic_pii.jsonl", "a", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"OK: appended {len(records)} records")
