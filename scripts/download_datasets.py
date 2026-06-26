#!/usr/bin/env python3
"""Download benchmark datasets from HuggingFace and save as JSONL.

Usage:
    pip install datasets
    python scripts/download_datasets.py [ceval|cmmlu|mmlu|cmath|all]

Saves to data/datasets/{name}/test.jsonl + meta.json
"""
import json
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATASETS_DIR = ROOT / "data" / "datasets"


def download_ceval():
    """Download C-Eval (Chinese, 52 subjects, multiple-choice)."""
    from datasets import load_dataset

    print("Downloading C-Eval...")
    ds_dir = DATASETS_DIR / "ceval"
    ds_dir.mkdir(parents=True, exist_ok=True)

    all_questions = []
    subjects = set()

    # C-Eval has per-subject configs
    # Load the "all" config which combines everything
    try:
        ds = load_dataset("ceval/ceval-exam", "all", split="test", trust_remote_code=True)
    except Exception:
        # Fallback: load validation split if test has no answers
        ds = load_dataset("ceval/ceval-exam", "all", split="val", trust_remote_code=True)

    for i, row in enumerate(ds):
        subj = row.get("subject", "unknown")
        subjects.add(subj)
        question = row.get("question", "")
        a = row.get("A", "")
        b = row.get("B", "")
        c = row.get("C", "")
        d = row.get("D", "")
        answer = row.get("answer", "")

        all_questions.append({
            "question_id": f"ceval_{i}",
            "subject": subj,
            "question": question,
            "choices": [f"A. {a}", f"B. {b}", f"C. {c}", f"D. {d}"],
            "answer": answer.upper() if answer else "",
            "answer_type": "mc",
        })

    _save_dataset(ds_dir, all_questions, sorted(subjects))
    print(f"  C-Eval: {len(all_questions)} questions, {len(subjects)} subjects")


def download_cmmlu():
    """Download CMMLU (Chinese, 67 subjects, multiple-choice)."""
    from datasets import load_dataset

    print("Downloading CMMLU...")
    ds_dir = DATASETS_DIR / "cmmlu"
    ds_dir.mkdir(parents=True, exist_ok=True)

    all_questions = []
    subjects = set()

    try:
        ds = load_dataset("lmlmcat/cmmlu", split="test", trust_remote_code=True)
    except Exception:
        ds = load_dataset("lmlmcat/cmmlu", split="validation", trust_remote_code=True)

    for i, row in enumerate(ds):
        subj = row.get("subject", "unknown")
        subjects.add(subj)
        question = row.get("question", "")
        a = row.get("A", "")
        b = row.get("B", "")
        c = row.get("C", "")
        d = row.get("D", "")
        answer = row.get("answer", "")

        all_questions.append({
            "question_id": f"cmmlu_{i}",
            "subject": subj,
            "question": question,
            "choices": [f"A. {a}", f"B. {b}", f"C. {c}", f"D. {d}"],
            "answer": answer.upper() if answer else "",
            "answer_type": "mc",
        })

    _save_dataset(ds_dir, all_questions, sorted(subjects))
    print(f"  CMMLU: {len(all_questions)} questions, {len(subjects)} subjects")


def download_mmlu():
    """Download MMLU (English, 57 subjects, multiple-choice)."""
    from datasets import load_dataset

    print("Downloading MMLU...")
    ds_dir = DATASETS_DIR / "mmlu"
    ds_dir.mkdir(parents=True, exist_ok=True)

    all_questions = []
    subjects = set()

    ds = load_dataset("cais/mmlu", "all", split="test", trust_remote_code=True)

    for i, row in enumerate(ds):
        subj = row.get("subject", "unknown")
        subjects.add(subj)
        question = row.get("question", "")
        choices = row.get("choices", ["", "", "", ""])
        answer = row.get("answer", "")

        # MMLU answer is integer 0-3, map to A-D
        if isinstance(answer, int):
            answer = "ABCD"[answer]

        all_questions.append({
            "question_id": f"mmlu_{i}",
            "subject": subj,
            "question": question,
            "choices": [f"A. {choices[0]}", f"B. {choices[1]}", f"C. {choices[2]}", f"D. {choices[3]}"],
            "answer": answer.upper() if answer else "",
            "answer_type": "mc",
        })

    _save_dataset(ds_dir, all_questions, sorted(subjects))
    print(f"  MMLU: {len(all_questions)} questions, {len(subjects)} subjects")


def download_cmath():
    """Download CMATH (Chinese elementary math, numeric answers)."""
    from datasets import load_dataset

    print("Downloading CMATH...")
    ds_dir = DATASETS_DIR / "cmath"
    ds_dir.mkdir(parents=True, exist_ok=True)

    all_questions = []
    subjects = set()

    try:
        ds = load_dataset("weitianwen/cmath", split="test", trust_remote_code=True)
    except Exception:
        ds = load_dataset("weitianwen/cmath", split="validation", trust_remote_code=True)

    for i, row in enumerate(ds):
        # CMATH fields vary; try common patterns
        question = row.get("question", row.get("problem", ""))
        answer = str(row.get("answer", row.get("solution", "")))
        grade = row.get("grade", "unknown")
        subjects.add(f"grade_{grade}")

        # Clean answer: extract just the number
        import re
        nums = re.findall(r'-?\d+\.?\d*', answer)
        clean_answer = nums[-1] if nums else answer.strip()

        all_questions.append({
            "question_id": f"cmath_{i}",
            "subject": f"grade_{grade}",
            "question": question,
            "choices": [],
            "answer": clean_answer,
            "answer_type": "numeric",
        })

    _save_dataset(ds_dir, all_questions, sorted(subjects))
    print(f"  CMATH: {len(all_questions)} questions, {len(subjects)} grades")


def _save_dataset(ds_dir: Path, questions: list, subjects: list):
    """Save questions as JSONL and write meta.json."""
    # Write test.jsonl
    with open(ds_dir / "test.jsonl", "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # Write meta.json
    meta = {
        "question_count": len(questions),
        "subjects": subjects,
    }
    with open(ds_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


DOWNLOADERS = {
    "ceval": download_ceval,
    "cmmlu": download_cmmlu,
    "mmlu": download_mmlu,
    "cmath": download_cmath,
}


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} [ceval|cmmlu|mmlu|cmath|all]")
        sys.exit(1)

    target = sys.argv[1].lower()

    if target == "all":
        for name, fn in DOWNLOADERS.items():
            try:
                fn()
            except Exception as e:
                print(f"  ERROR downloading {name}: {e}")
    elif target in DOWNLOADERS:
        DOWNLOADERS[target]()
    else:
        print(f"Unknown dataset: {target}. Available: {list(DOWNLOADERS.keys())}")
        sys.exit(1)

    print("\nDone!")


if __name__ == "__main__":
    main()
