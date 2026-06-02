import json

# SPECS 3031-3040

chat_3031 = [
    {"role": "user", "content": "Доброслав Сидоров, г. Забайкальск, наб. 9 мая, д. 12, кв. 135. Подтвердите получение документов."},
    {"role": "assistant", "content": "Документы получены и переданы в обработку."},
]

chat_3032 = [
    {"role": "user", "content": "Татьяна Семеновна и Фока Демидович — оба записаны в одно время?! Полный пиздец!"},
    {"role": "assistant", "content": "Приносим извинения, сейчас исправим ошибку в расписании."},
]

chat_3035 = [
    {"role": "user", "content": "Почему в одну запись добавили сразу двух человек?"},
    {"role": "assistant", "content": "Поясните, пожалуйста, о каких записях идёт речь."},
    {"role": "user", "content": "Клавдий Демьянович Фокин и София Андреевна Тимофеева — оба в одном слоте! Это невозможно!"},
    {"role": "assistant", "content": "Понял, исправляем немедленно. Прошу прощения за неудобство."},
]

chat_3039 = [
    {"role": "user", "content": "Родионов Радован Игнатьевич только что выиграл в нашем конкурсе!"},
    {"role": "assistant", "content": "Замечательно! Поздравляем победителя!"},
    {"role": "user", "content": "Передайте Родионов Радован Игнатьевич, что приз уже ждёт его!"},
]

records = [
    # 3031 — BOTH DIALOG NAME_FI ADDR_FULL formal short neutral position=beginning
    {"id": "dialog_synth_3031", "domain": "DIALOG", "entity_type": "BOTH", "name_form": "NAME_FI", "addr_form": "ADDR_FULL",
     "style": "formal", "length": "short", "expression": "neutral", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "beginning",
     "text": json.dumps(chat_3031, ensure_ascii=False),
     "entities": [{"text": "Доброслав Сидоров", "type": "NAME"}, {"text": "г. Забайкальск, наб. 9 мая, д. 12, кв. 135", "type": "ADDRESS"}]},

    # 3032 — NAME_ONLY DIALOG NAME_IO informal medium rage multi_entity=true position=beginning
    {"id": "dialog_synth_3032", "domain": "DIALOG", "entity_type": "NAME_ONLY", "name_form": "NAME_IO", "addr_form": None,
     "style": "informal", "length": "medium", "expression": "rage", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": True, "position": "beginning",
     "text": json.dumps(chat_3032, ensure_ascii=False),
     "entities": [{"text": "Татьяна Семеновна", "type": "NAME"}, {"text": "Фока Демидович", "type": "NAME"}]},

    # 3033 — ADDRESS_ONLY GOV ADDR_CSH informal medium sad position=end
    {"id": "gov_synth_3033", "domain": "GOV", "entity_type": "ADDRESS_ONLY", "name_form": None, "addr_form": "ADDR_CSH",
     "style": "informal", "length": "medium", "expression": "sad", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "end",
     "text": "Жалоба подана уже месяц назад, проверяющие до сих пор не появились. Все обращения остаются без ответа. Всё это происходит по адресу Красная Поляна, бул. Лесхозная 16 — жители устали ждать.",
     "entities": [{"text": "Красная Поляна, бул. Лесхозная 16", "type": "ADDRESS"}]},

    # 3034 — NEGATIVE DELIVERY mixed medium neutral org_names
    {"id": "neg_synth_3034", "domain": "DELIVERY", "entity_type": "NEGATIVE", "name_form": None, "addr_form": None,
     "style": "mixed", "length": "medium", "expression": "neutral", "neg_category": "org_names",
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": None,
     "text": "Заказ принят от ООО Иванов и партнёры. Всё оформлено в соответствии с договором поставки. Доставка планируется в течение трёх рабочих дней.",
     "entities": []},

    # 3035 — NAME_ONLY DIALOG NAME_FIO mixed long irritated multi_entity=true position=middle
    {"id": "dialog_synth_3035", "domain": "DIALOG", "entity_type": "NAME_ONLY", "name_form": "NAME_FIO", "addr_form": None,
     "style": "mixed", "length": "long", "expression": "irritated", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": True, "position": "middle",
     "text": json.dumps(chat_3035, ensure_ascii=False),
     "entities": [{"text": "Клавдий Демьянович Фокин", "type": "NAME"}, {"text": "София Андреевна Тимофеева", "type": "NAME"}]},

    # 3036 — NAME_ONLY AUTO NAME_FIO_DAT formal long neutral position=middle
    {"id": "auto_synth_3036", "domain": "AUTO", "entity_type": "NAME_ONLY", "name_form": "NAME_FIO_DAT", "addr_form": None,
     "style": "formal", "length": "long", "expression": "neutral", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "middle",
     "text": "Страховой полис ОСАГО направлен в офис для проверки. Уведомление о готовности документов будет отправлено Гавриловой Василисе Феликсовне в установленные сроки. Просим клиента иметь при себе паспорт при получении.",
     "entities": [{"text": "Гавриловой Василисе Феликсовне", "type": "NAME"}]},

    # 3037 — NAME_CONTEXT AUTO NAME_FI formal medium rage position=mixed
    {"id": "auto_synth_3037", "domain": "AUTO", "entity_type": "NAME_CONTEXT", "name_form": "NAME_FI", "addr_form": None,
     "style": "formal", "length": "medium", "expression": "rage", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "mixed",
     "text": "Степан Кудряшов подал жалобу три недели назад, и до сих пор ни хрена не сделано. Контактный номер +7 901 555-12-34 передан в отдел, но никто не перезвонил. Это сраное безобразие — Степан Кудряшов заслуживает нормального ответа.",
     "entities": [{"text": "Степан Кудряшов", "type": "NAME"}]},

    # 3038 — NEGATIVE LEGAL formal medium urgent neutral_service
    {"id": "neg_synth_3038", "domain": "LEGAL", "entity_type": "NEGATIVE", "name_form": None, "addr_form": None,
     "style": "formal", "length": "medium", "expression": "urgent", "neg_category": "neutral_service",
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": None,
     "text": "Сделка проходит регистрацию в установленном порядке. Срочно требуется предоставить дополнительные документы для завершения процедуры. Промедление может привести к аннулированию заявки.",
     "entities": []},

    # 3039 — NAME_ONLY DIALOG NAME_IFO mixed medium joy position=mixed
    {"id": "dialog_synth_3039", "domain": "DIALOG", "entity_type": "NAME_ONLY", "name_form": "NAME_IFO", "addr_form": None,
     "style": "mixed", "length": "medium", "expression": "joy", "neg_category": None,
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": "mixed",
     "text": json.dumps(chat_3039, ensure_ascii=False),
     "entities": [{"text": "Родионов Радован Игнатьевич", "type": "NAME"}]},

    # 3040 — NEGATIVE DELIVERY formal medium neutral address_fragments
    {"id": "neg_synth_3040", "domain": "DELIVERY", "entity_type": "NEGATIVE", "name_form": None, "addr_form": None,
     "style": "formal", "length": "medium", "expression": "neutral", "neg_category": "address_fragments",
     "edge_case": None, "has_typo": False, "multi_entity": False, "position": None,
     "text": "Груз доставляется на 2-й этаж, правое крыло здания. Контактное лицо будет уведомлено за час до прибытия курьера.",
     "entities": []},
]

for r in records:
    for e in r["entities"]:
        assert e["text"] in r["text"], f"FAIL {r['id']}: '{e['text']}' not in text"

with open("output/synthetic_pii.jsonl", "a", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"OK: appended {len(records)} records")
