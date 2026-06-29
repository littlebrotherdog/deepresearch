"""Evaluation data models — questions, answers, and run records."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from config import EVALS_DIR


@dataclass
class EvalQuestion:
    """A single benchmark question."""
    question_id: str
    subject: str
    question: str
    choices: list[str]       # ["A. ...", "B. ...", "C. ...", "D. ..."] — empty for numeric
    answer: str              # "A"/"B"/"C"/"D" or numeric string
    answer_type: str         # "mc" (multiple choice) or "numeric"


@dataclass
class ModelAnswer:
    """One model's answer to one question."""
    model_name: str
    question_id: str
    subject: str
    correct_answer: str
    raw_response: str
    extracted_answer: str
    is_correct: bool
    latency_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvalRun:
    """A complete evaluation run record."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    dataset_name: str = ""
    models: list[dict] = field(default_factory=list)
    subject_filter: list[str] = field(default_factory=list)
    num_questions: int = 0
    status: str = "pending"  # pending | running | completed | cancelled | error
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    results: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self):
        path = EVALS_DIR / f"{self.id}.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> EvalRun:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def load(cls, eval_id: str) -> EvalRun | None:
        path = EVALS_DIR / f"{eval_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def compute_summary(self):
        """Compute per-model accuracy and subject breakdown."""
        summary: dict[str, Any] = {}
        for model_cfg in self.models:
            name = model_cfg["model_name"]
            model_results = [r for r in self.results if r["model_name"] == name]
            correct = sum(1 for r in model_results if r["is_correct"])
            total = len(model_results)

            by_subject: dict[str, dict] = {}
            for r in model_results:
                subj = r.get("subject", "unknown")
                if subj not in by_subject:
                    by_subject[subj] = {"correct": 0, "total": 0}
                by_subject[subj]["total"] += 1
                if r["is_correct"]:
                    by_subject[subj]["correct"] += 1

            summary[name] = {
                "correct": correct,
                "total": total,
                "accuracy": round(correct / total, 4) if total else 0,
                "by_subject": by_subject,
            }
        self.summary = summary
