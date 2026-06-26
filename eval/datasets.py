"""Dataset loading and normalization for benchmark evaluation.

Datasets are stored as JSONL files under data/datasets/{name}/test.jsonl.
Each line is a JSON object with fields matching EvalQuestion.
A meta.json file describes the dataset.

Download via: python scripts/download_datasets.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from config import DATASETS_DIR
from eval.models import EvalQuestion

logger = logging.getLogger(__name__)

# Registry of known datasets
DATASET_REGISTRY = {
    "ceval": {"name": "C-Eval", "hf_id": "ceval/ceval-exam", "lang": "zh", "answer_type": "mc"},
    "cmmlu": {"name": "CMMLU", "hf_id": "lmlmcat/cmmlu", "lang": "zh", "answer_type": "mc"},
    "mmlu":  {"name": "MMLU", "hf_id": "cais/mmlu", "lang": "en", "answer_type": "mc"},
    "cmath": {"name": "CMATH", "hf_id": "weitianwen/cmath", "lang": "zh", "answer_type": "numeric"},
}


def list_datasets() -> list[dict]:
    """List available datasets with metadata."""
    result = []
    for key, info in DATASET_REGISTRY.items():
        ds_dir = DATASETS_DIR / key
        test_file = ds_dir / "test.jsonl"
        meta_file = ds_dir / "meta.json"

        available = test_file.exists()
        subject_list: list[str] = []
        question_count = 0

        if available:
            # Load meta for subjects
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    subject_list = meta.get("subjects", [])
                    question_count = meta.get("question_count", 0)
                except Exception:
                    pass
            # Fallback: count from file
            if not question_count:
                try:
                    with open(test_file, encoding="utf-8") as f:
                        question_count = sum(1 for _ in f)
                except Exception:
                    pass
            # Fallback: get subjects from data
            if not subject_list:
                try:
                    subjects_set: set[str] = set()
                    with open(test_file, encoding="utf-8") as f:
                        for line in f:
                            obj = json.loads(line)
                            if "subject" in obj:
                                subjects_set.add(obj["subject"])
                    subject_list = sorted(subjects_set)
                except Exception:
                    pass

        result.append({
            "id": key,
            "name": info["name"],
            "lang": info["lang"],
            "answer_type": info["answer_type"],
            "available": available,
            "question_count": question_count,
            "subjects": subject_list,
        })
    return result


def load_dataset(
    name: str,
    subjects: list[str] | None = None,
    limit: int | None = None,
) -> list[EvalQuestion]:
    """Load a dataset and return a list of EvalQuestion objects.

    Args:
        name: Dataset ID (e.g., "ceval")
        subjects: Optional subject filter. Empty/None = all subjects.
        limit: Optional max number of questions to load.
    """
    if name not in DATASET_REGISTRY:
        raise ValueError(f"Unknown dataset: {name}. Available: {list(DATASET_REGISTRY.keys())}")

    ds_dir = DATASETS_DIR / name
    test_file = ds_dir / "test.jsonl"

    if not test_file.exists():
        raise FileNotFoundError(
            f"Dataset '{name}' not found at {test_file}. "
            f"Run: python scripts/download_datasets.py"
        )

    questions: list[EvalQuestion] = []
    subject_set = set(subjects) if subjects else None

    with open(test_file, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Subject filter
            subj = obj.get("subject", "")
            if subject_set and subj not in subject_set:
                continue

            q = EvalQuestion(
                question_id=obj.get("question_id", f"{name}_{i}"),
                subject=subj,
                question=obj.get("question", ""),
                choices=obj.get("choices", []),
                answer=obj.get("answer", ""),
                answer_type=obj.get("answer_type", DATASET_REGISTRY[name]["answer_type"]),
            )
            questions.append(q)

    return questions
