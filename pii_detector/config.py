# Path to the trained spaCy NER model (passed directly to spacy.load()).
SPACY_NER_MODEL = "alrosait/spacy_ru_core_news_lg_pii"

# Confidence score assigned by SpacyRecognizer to all detected entities
SPACY_NER_STRENGTH = 0.85

ALL_ENTITIES = [
    "ADDRESS", "BANK_CARD_NUMBER", "EMAIL", "NAME", "PHONE_NUMBER",
    "TOKEN", "INN", "KPP", "OGRN", "OGRNIP", "SNILS", "PASSPORT_NUMBER", "CVC",
]

# Long texts are analyzed in chunks (pii_detector/chunking.py): spaCy and Presidio memory grows with
# the length of the analyzed text. Overlap covers regex context windows (up to 150 chars) and
# entities on chunk boundaries.
CHUNK_CHARS = 20_000
CHUNK_OVERLAP = 1_000
# Chunks analyzed at once across all requests: bounds peak memory under concurrent long requests.
MAX_PARALLEL = 2
