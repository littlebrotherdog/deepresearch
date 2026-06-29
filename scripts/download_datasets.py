#!/usr/bin/env python3
"""Download benchmark datasets from HuggingFace and save as JSONL.

Usage:
    pip install datasets
    python scripts/download_datasets.py [ceval|cmmlu|mmlu|cmath|all]

Saves to data/datasets/{name}/test.jsonl + meta.json
"""
import json
import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATASETS_DIR = ROOT / "data" / "datasets"

# Default to the community mirror so downloads work where huggingface.co is
# blocked (e.g. mainland China). Override by exporting HF_ENDPOINT yourself.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")



def download_ceval():
    """Download C-Eval (Chinese, 52 subjects, multiple-choice).

    Upstream exposes one config *per subject* (there is no ``'all'`` combined
    config), so enumerate every subject's labelled validation split.
    """
    from datasets import load_dataset, get_dataset_config_names

    print("Downloading C-Eval...")
    ds_dir = DATASETS_DIR / "ceval"
    ds_dir.mkdir(parents=True, exist_ok=True)

    repo_id = "ceval/ceval-exam"
    try:
        # NOTE: ``trust_remote_code`` was removed in datasets>=2.x's later
        # releases and is unsupported on >=4.x; the repo ships standard splits.
        configs = get_dataset_config_names(repo_id)
    except Exception as e:
        raise RuntimeError(f"Failed to list C-Eval configs: {e}")
    configs = [c for c in configs if c and c != "default"] or ["all"]

    all_questions = []
    for ci, subj in enumerate(configs):
        ds = None
        last_err = None
        # Answers live in val/dev; the 'test' split is unlabelled.
        for split in ("val", "dev"):
            try:
                ds = load_dataset(
                    repo_id, subj, split=split,
                    verification_mode="no_checks",
                )
                break
            except Exception as e:
                last_err = e
                continue
        if ds is None:
            print(f"  skip '{subj}' ({last_err})")
            continue

        for i, r in enumerate(ds):
            ans = r.get("answer", "")
            all_questions.append({
                "question_id": f"ceval_{subj}_{i}",
                "subject": subj,
                "question": r.get("question", ""),
                "choices": [
                    f"A. {r.get('A', '')}", f"B. {r.get('B', '')}",
                    f"C. {r.get('C', '')}", f"D. {r.get('D', '')}",
                ],
                "answer": ans.upper() if isinstance(ans, str) else "",
                "answer_type": "mc",
            })

        if (ci + 1) % 10 == 0 or ci + 1 == len(configs):
            print(f"  loaded {ci + 1}/{len(configs)} subjects "
                  f"({len(all_questions)} questions)")

    _save_dataset(ds_dir, all_questions, sorted({q['subject'] for q in all_questions}))
    print(f"  C-Eval: {len(all_questions)} questions, {len(set(q['subject'] for q in all_questions))} subjects")


def download_cmmlu():
    """Download CMMLU by fetching the raw archive directly.

    The ``lmlmcat/cmmlu`` repo ships only an old-style loading script plus the
    bundled ``cmmlu_v1_0_1.zip``. Newer ``datasets`` versions no longer execute
    dataset scripts at all, so we bypass ``load_dataset`` and parse the zipped
    per-subject CSV files ourselves.
    """
    import csv
    import io
    import zipfile
    from huggingface_hub import hf_hub_download

    print("Downloading CMMLU...")
    ds_dir = DATASETS_DIR / "cmmlu"
    ds_dir.mkdir(parents=True, exist_ok=True)

    repo_id, filename = "lmlmcat/cmmlu", "cmmlu_v1_0_1.zip"
    try:
        zpath = hf_hub_download(repo_id, filename, repo_type="dataset")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {repo_id}/{filename}: {e}")

    all_questions = []
    subjects = set()
    with zipfile.ZipFile(zpath) as zf:
        members = [
            n for n in zf.namelist()
            if n.lower().endswith(".csv")
            and (n.lower().startswith("test/") or "test\\" in n.lower())
        ]
        for member in sorted(members):
            subj = Path(member).stem
            subjects.add(subj)
            raw = zf.read(member)
            text = None
            for enc in ("utf-8-sig", "gb18030"):  # tolerate either encoding
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if not text:
                continue
            reader = csv.DictReader(io.StringIO(text))
            for i, r in enumerate(reader):
                q = (r.get("Question") or "").strip()
                if not q:
                    continue
                a, b, c, d = [(r.get(k) or "") for k in ("A", "B", "C", "D")]
                ans = (r.get("Answer") or "").strip().upper()
                all_questions.append({
                    "question_id": f"cmmlu_{subj}_{i}",
                    "subject": subj,
                    "question": q,
                    "choices": [f"A. {a}", f"B. {b}", f"C. {c}", f"D. {d}"],
                    "answer": ans,
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

    ds = load_dataset("cais/mmlu", "all", split="test")

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
        ds = load_dataset("weitianwen/cmath", split="test")
    except Exception:
        ds = load_dataset("weitianwen/cmath", split="validation")

    for i, row in enumerate(ds):
        # CMATH fields vary; the real schema exposes the ground-truth number as
        # ``golden``. Fall back to common names defensively.
        question = row.get("question", row.get("problem", ""))
        answer = str(row.get("golden") or row.get("answer") or row.get("solution") or "")
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
