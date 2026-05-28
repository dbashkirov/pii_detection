# Path to the trained spaCy NER model (passed directly to spacy.load()).
SPACY_NER_MODEL = "./ft_spacy/model-best-combo-0.78"

# Confidence score assigned by SpacyRecognizer to all detected entities
SPACY_NER_STRENGTH = 0.85

ALL_ENTITIES = [
    "ADDRESS", "BANK_CARD_NUMBER", "EMAIL", "NAME", "PHONE_NUMBER",
    "TOKEN", "INN", "KPP", "OGRN", "OGRNIP", "SNILS", "PASSPORT_NUMBER", "CVC",
]
