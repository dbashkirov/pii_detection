"""Объединяет пары .spacy файлов в combo-версии:
    training/data/dev.spacy   + training/data/dev_synth.spacy   → training/data/dev_combo.spacy
    training/data/train.spacy + training/data/train_synth.spacy → training/data/train_combo.spacy
"""
import random
import spacy
from spacy.tokens import DocBin
from pathlib import Path

SEED = 42


def merge(paths_in: list, path_out: Path, vocab) -> None:
    all_docs = []
    for p in paths_in:
        db = DocBin().from_disk(p)
        docs = list(db.get_docs(vocab))
        all_docs.extend(docs)
        print(f"  + {p}  ({len(docs)} docs)")

    random.Random(SEED).shuffle(all_docs)

    db_out = DocBin()
    for doc in all_docs:
        db_out.add(doc)
    db_out.to_disk(path_out)
    print(f"  → Saved {path_out}  (total {len(db_out)} docs, shuffled)\n")


nlp = spacy.blank("ru")
DATA = Path(__file__).parent.parent / "data"

print("=== dev_combo ===")
merge(
    [DATA / "dev.spacy", DATA / "dev_synth.spacy"],
    DATA / "dev_combo.spacy",
    nlp.vocab,
)

print("=== train_combo ===")
merge(
    [DATA / "train.spacy", DATA / "train_synth.spacy"],
    DATA / "train_combo.spacy",
    nlp.vocab,
)
