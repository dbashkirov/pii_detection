# Path to the trained spaCy NER model (passed directly to spacy.load()).
SPACY_NER_MODEL = "alrosait/spacy_ru_core_news_lg_pii"

# Confidence score assigned by SpacyRecognizer to all detected entities
SPACY_NER_STRENGTH = 0.85

ALL_ENTITIES = [
    "ADDRESS", "BANK_CARD_NUMBER", "EMAIL", "NAME", "PHONE_NUMBER",
    "TOKEN", "INN", "KPP", "OGRN", "OGRNIP", "SNILS", "PASSPORT_NUMBER", "CVC",
]
