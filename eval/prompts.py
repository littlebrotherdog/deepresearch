"""Prompt templates and answer parsing for evaluation."""
from __future__ import annotations

import re

from eval.models import EvalQuestion


def build_prompt(question: EvalQuestion) -> str:
    """Build an LLM prompt for a benchmark question."""
    if question.answer_type == "mc" and question.choices:
        choices_text = "\n".join(question.choices)
        return (
            "请回答以下选择题，只输出选项字母(A/B/C/D)，不要输出其他内容。\n\n"
            f"{question.question}\n{choices_text}"
        )
    else:
        return (
            "请解答以下数学题，只输出最终数字答案，不要输出其他内容。\n\n"
            f"{question.question}"
        )


def parse_answer(raw: str, answer_type: str) -> str:
    """Extract the answer from a raw LLM response.

    Returns:
        For MC: "A", "B", "C", or "D" (uppercase)
        For numeric: the extracted number as a string
        Empty string if parsing fails.
    """
    raw = raw.strip()

    if answer_type == "mc":
        # Try to find a standalone A/B/C/D letter
        # Common patterns: "A", "答案是A", "选A", "A)", "(A)", "正确答案是 A"
        match = re.search(r'(?:答案[是为选]?|选|选择|正确选项[是为]?|answer\s*(?:is)?)\s*[：:]*\s*([A-D])', raw, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # Try to find the first standalone A-D
        match = re.search(r'\b([A-D])\b', raw)
        if match:
            return match.group(1).upper()

        # Fallback: first capital letter A-D anywhere
        for ch in raw:
            if ch.upper() in "ABCD":
                return ch.upper()

        return ""

    else:  # numeric
        # Try to find the last number in the response
        numbers = re.findall(r'-?\d+\.?\d*', raw)
        if numbers:
            return numbers[-1]
        return ""


def check_answer(extracted: str, correct: str, answer_type: str) -> bool:
    """Check if the extracted answer matches the correct answer."""
    if not extracted or not correct:
        return False

    if answer_type == "mc":
        return extracted.upper() == correct.upper()
    else:  # numeric
        # Normalize: remove leading zeros, trailing .0
        try:
            return abs(float(extracted) - float(correct)) < 1e-6
        except (ValueError, TypeError):
            return extracted.strip() == correct.strip()
