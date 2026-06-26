"""Evaluation runner — orchestrates multi-model parallel benchmark execution."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.llm import LLMClient, ModelConfig
from config import settings
from eval.datasets import load_dataset
from eval.models import EvalRun, ModelAnswer
from eval.prompts import build_prompt, parse_answer, check_answer

logger = logging.getLogger(__name__)


def _create_model_client(model_cfg: dict) -> LLMClient:
    """Create an LLMClient for a specific model config."""
    from agent.llm import llm_client as global_client

    base_url = model_cfg.get("base_url") or global_client.config.base_url
    api_key = model_cfg.get("api_key") or global_client.config.api_key
    model_name = model_cfg["model_name"]

    config = ModelConfig(
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        temperature=0.0,   # deterministic for eval
        max_tokens=512,    # short answers suffice
    )
    return LLMClient(config)


class EvalRunner:
    """Runs a benchmark evaluation across multiple models in parallel."""

    def __init__(self, eval_run: EvalRun, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self.eval_run = eval_run
        self.loop = loop
        self.queue = queue
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _push(self, step: str, message: str, data: dict | None = None):
        """Push a progress event to the async queue."""
        self.loop.call_soon_threadsafe(
            self.queue.put_nowait,
            {"step": step, "message": message, "data": data or {}},
        )

    def run(self):
        """Main entry point — runs in a background thread."""
        try:
            self.eval_run.status = "running"
            self.eval_run.save()

            # Load questions
            questions = load_dataset(
                self.eval_run.dataset_name,
                subjects=self.eval_run.subject_filter or None,
                limit=self.eval_run.num_questions or None,
            )
            self.eval_run.num_questions = len(questions)

            if not questions:
                self.eval_run.status = "error"
                self.eval_run.save()
                self._push("error", "数据集为空或未找到", {})
                return

            self._push("init", "", {
                "total": len(questions),
                "models": [m["model_name"] for m in self.eval_run.models],
                "dataset": self.eval_run.dataset_name,
            })

            # Run each model in its own thread
            with ThreadPoolExecutor(max_workers=min(len(self.eval_run.models), settings.eval.max_concurrent_models) or 1) as pool:
                futures = {}
                for model_cfg in self.eval_run.models:
                    f = pool.submit(self._run_model, model_cfg, questions)
                    futures[f] = model_cfg["model_name"]

                for f in as_completed(futures):
                    model_name = futures[f]
                    try:
                        results = f.result()
                        self.eval_run.results.extend(results)
                        self.eval_run.save()
                        # Push model completion
                        correct = sum(1 for r in results if r["is_correct"])
                        self._push("model_done", f"{model_name} 完成", {
                            "model": model_name,
                            "correct": correct,
                            "total": len(results),
                            "accuracy": round(correct / len(results), 4) if results else 0,
                        })
                    except Exception as e:
                        logger.error(f"Model {model_name} failed: {e}")
                        self._push("model_error", str(e), {"model": model_name})

            # Check cancellation
            if self._cancelled:
                self.eval_run.status = "cancelled"
            else:
                self.eval_run.status = "completed"

            self.eval_run.completed_at = time.time()
            self.eval_run.compute_summary()
            self.eval_run.save()

            self._push("done", "", {
                "eval_id": self.eval_run.id,
                "summary": self.eval_run.summary,
            })

        except Exception as e:
            logger.error(f"EvalRunner error: {e}", exc_info=True)
            self.eval_run.status = "error"
            self.eval_run.save()
            self._push("error", str(e), {})

    def _run_model(self, model_cfg: dict, questions: list) -> list[dict]:
        """Run all questions for a single model. Returns list of result dicts."""
        client = _create_model_client(model_cfg)
        model_name = model_cfg["model_name"]
        results: list[dict] = []

        for i, q in enumerate(questions):
            if self._cancelled:
                break

            self._push("progress", "", {
                "model": model_name,
                "current": i + 1,
                "total": len(questions),
            })

            try:
                prompt = build_prompt(q)
                start = time.time()
                raw = client.chat([{"role": "user", "content": prompt}])
                latency = (time.time() - start) * 1000

                extracted = parse_answer(raw, q.answer_type)
                is_correct = check_answer(extracted, q.answer, q.answer_type)

                results.append(ModelAnswer(
                    model_name=model_name,
                    question_id=q.question_id,
                    subject=q.subject,
                    correct_answer=q.answer,
                    raw_response=raw,
                    extracted_answer=extracted,
                    is_correct=is_correct,
                    latency_ms=round(latency, 1),
                ).to_dict())

            except Exception as e:
                logger.debug(f"Question {q.question_id} failed for {model_name}: {e}")
                results.append(ModelAnswer(
                    model_name=model_name,
                    question_id=q.question_id,
                    subject=q.subject,
                    correct_answer=q.answer,
                    raw_response=f"ERROR: {e}",
                    extracted_answer="",
                    is_correct=False,
                    latency_ms=0,
                ).to_dict())

            # Rate limit protection
            if settings.eval.delay_between_questions > 0:
                time.sleep(settings.eval.delay_between_questions)

        return results
