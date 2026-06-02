from typing import List

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer
from presidio_anonymizer import AnonymizerEngine

from pii_detector.config import (
    SPACY_NER_MODEL,
    SPACY_NER_STRENGTH,
    ALL_ENTITIES,
)
from pii_detector.recognizers.detectors import (
    InnRecognizer, SnilsRecognizer, OgrnRecognizer,
    OgrnipRecognizer, KppRecognizer, PassportRecognizer,
    EmailRecognizer, PhoneRecognizer, BankCardRecognizer, CvcRecognizer,
)
from pii_detector.recognizers.token import TokenRecognizer


class HybridPIIDetector:
    def __init__(self,
                 spacy_model_path: str = SPACY_NER_MODEL,
                 ner_strength: float = SPACY_NER_STRENGTH):
        """
        Parameters
        ----------
        spacy_model_path : str
            Path (or installed package name) passed to spacy.load().
            Defaults to SPACY_NER_MODEL from config.
        ner_strength : float
            Confidence score assigned by SpacyRecognizer to NAME / ADDRESS entities.
        """
        self._analyzer = self._build_analyzer(spacy_model_path, ner_strength)
        self._anonymizer = AnonymizerEngine()

    @staticmethod
    def _build_analyzer(spacy_model_path: str, ner_strength: float) -> AnalyzerEngine:
        # Use the trained spaCy NER model as the Presidio NLP engine.
        # spacy.load() accepts both installed package names and file-system paths.
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": spacy_model_path}],
        }
        provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
        nlp_engine = provider.create_engine()

        # Empty registry — we define all recognizers ourselves
        registry = RecognizerRegistry(recognizers=[])

        # --- spaCy NER layer (NAME + ADDRESS) ---
        # SpacyRecognizer reads entities from nlp_artifacts produced by the NLP engine above.
        # Our model labels (NAME, ADDRESS) map directly to the Presidio entity types.
        registry.add_recognizer(SpacyRecognizer(
            supported_entities=["NAME", "ADDRESS"],
            check_label_groups=[
                ({"NAME"},    {"NAME"}),
                ({"ADDRESS"}, {"ADDRESS"}),
            ],
            ner_strength=ner_strength,
            supported_language="en",
        ))

        # --- detect-secrets TOKEN layer ---
        registry.add_recognizer(TokenRecognizer())

        # --- Regex + checksum layer ---
        registry.add_recognizer(InnRecognizer())
        registry.add_recognizer(SnilsRecognizer())
        registry.add_recognizer(OgrnRecognizer())
        registry.add_recognizer(OgrnipRecognizer())
        registry.add_recognizer(KppRecognizer())
        registry.add_recognizer(PassportRecognizer())
        registry.add_recognizer(BankCardRecognizer())
        registry.add_recognizer(PhoneRecognizer())
        registry.add_recognizer(EmailRecognizer())
        registry.add_recognizer(CvcRecognizer())

        return AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=["en"],
        )

    @staticmethod
    def _deduplicate(results: List[RecognizerResult]) -> List[RecognizerResult]:
        """Remove overlapping/contained spans with context-aware rules:
        - Same span, different types → keep highest score.
        - Same type, one span contains the other → keep the longer span (more complete entity).
        - Different types, one span contains the other → keep highest score.
        """
        if not results:
            return results

        # Step 1: exact same (start, end) → keep max score
        best: dict[tuple[int, int], RecognizerResult] = {}
        for r in results:
            key = (r.start, r.end)
            if key not in best or r.score > best[key].score:
                best[key] = r
        deduped = list(best.values())

        # Step 2: containment resolution
        # Sort: longer spans first; ties broken by higher score
        deduped.sort(key=lambda r: (r.end - r.start, r.score), reverse=True)
        kept: List[RecognizerResult] = []
        for r in deduped:
            dominated = False
            for k in kept:
                if k is r:
                    continue
                contains = k.start <= r.start and k.end >= r.end
                if not contains:
                    continue
                # Same entity type: longer span already kept (k is longer) → drop r
                if k.entity_type == r.entity_type:
                    dominated = True
                    break
                # Different entity types: higher score wins
                if k.score >= r.score:
                    dominated = True
                    break
            if not dominated:
                kept.append(r)
        return kept

    # TOKEN: label words that the model confuses with the entity itself
    _TOKEN_STOPLIST = {
        "токен", "token", "ключ", "key", "secret", "api key", "api token",
    }

    # ADDRESS: field labels without actual address value
    _ADDRESS_MIN_LEN = 3
    _ADDRESS_STOPLIST = {
        "адрес", "ваш адрес", "адрес доставки", "адрес получателя",
        "адрес отправителя", "адрес регистрации", "адрес проживания",
        "юридический адрес", "фактический адрес", "почтовый адрес",
        "адрес электронной почты", "домашний адрес",
    }

    def _postprocess(self, results: List[RecognizerResult], text: str) -> List[RecognizerResult]:
        filtered = []
        for r in results:
            span = text[r.start:r.end]

            if r.entity_type == "ADDRESS":
                if len(span.strip()) < self._ADDRESS_MIN_LEN:
                    continue
                if span.strip().lower() in self._ADDRESS_STOPLIST:
                    continue

            if r.entity_type == "TOKEN":
                if span.strip().lower() in self._TOKEN_STOPLIST:
                    continue

            filtered.append(r)
        return filtered

    def analyze(self, text: str, language: str = "en") -> List[RecognizerResult]:
        raw = self._analyzer.analyze(
            text=text,
            entities=ALL_ENTITIES,
            language=language,
        )
        # spaCy may confuse email addresses with ADDRESS/NAME (dots, domain-like structure).
        # Drop such misclassifications before dedup so EmailRecognizer's result survives.
        raw = [r for r in raw
               if not (r.entity_type in ("ADDRESS", "NAME") and "@" in text[r.start:r.end])]
        deduped = self._deduplicate(raw)
        return self._postprocess(deduped, text)

    def anonymize(self, text: str, language: str = "en") -> str:
        results = self.analyze(text, language)
        if not results:
            return text
        anonymized = self._anonymizer.anonymize(text=text, analyzer_results=results)
        return anonymized.text or ''

    def anonymize_with_items(self, text: str, language: str = "en"):
        """Return (anonymized_text, items) where items is the Presidio OperatorResult list.

        items[i] is a dict with keys: start, end, entity_type, text (placeholder), operator.
        Positions in items refer to the anonymized text, not the original.
        Useful for demonstrating deanonymization: the original spans can be recovered from
        analyze() results paired with these items.
        """
        results = self.analyze(text, language)
        if not results:
            return text, []
        engine_result = self._anonymizer.anonymize(text=text, analyzer_results=results)
        items = [vars(item) for item in (engine_result.items or [])]
        return engine_result.text or '', items
