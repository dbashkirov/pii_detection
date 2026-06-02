"""Объединяет пары .spacy файлов в combo-версии:
    training/data/dev.spacy   + training/data/dev_synth.spacy   → training/data/dev_combo.spacy
    training/data/train.spacy + training/data/train_synth.spacy → training/data/train_combo.spacy
"""
import spacy
from spacy.tokens import DocBin
from pathlib import Path


def merge(paths_in: list, path_out: Path, vocab) -> None:
    db_out = DocBin()
    for p in paths_in:
        db = DocBin().from_disk(p)
        docs = list(db.get_docs(vocab))
        for doc in docs:
            db_out.add(doc)
        print(f"  + {p}  ({len(docs)} docs)")
    db_out.to_disk(path_out)
    print(f"  → Saved {path_out}  (total {len(db_out)} docs)\n")


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
