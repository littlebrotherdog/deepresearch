"""FastAPI server - REST + WebSocket for the Deep Research Agent."""
from __future__ import annotations

import json
import logging
import asyncio
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.core import agent, ResearchStep, ResearchCancelledError
from agent.llm import llm_client
from agent.memory import memory
from config import settings, ModelConfig, EVALS_DIR
from eval.datasets import list_datasets, load_dataset
from eval.models import EvalRun
from eval.runner import EvalRunner

logger = logging.getLogger(__name__)

app = FastAPI(title="Deep Research Agent", version="1.0.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Serve static frontend files
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class CreateSessionRequest(BaseModel):
    title: str = ""


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ModelConfigRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class SetTitleRequest(BaseModel):
    title: str


class EvalModelConfig(BaseModel):
    model_name: str
    base_url: str = ""
    api_key: str = ""


class EvalStartRequest(BaseModel):
    dataset: str
    models: list[EvalModelConfig]
    subjects: list[str] = []
    limit: int | None = None


# ---------------------------------------------------------------------------
# Routes - Frontend
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Routes - Sessions
# ---------------------------------------------------------------------------
@app.get("/api/sessions")
async def list_sessions():
    return JSONResponse(memory.list_sessions())


@app.post("/api/sessions")
async def create_session(req: CreateSessionRequest):
    session = memory.create_session(req.title)
    return session.to_dict()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    session = memory.get_session(session_id)
    if session is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return session.to_dict()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = memory.delete_session(session_id)
    return {"deleted": ok}


@app.put("/api/sessions/{session_id}/title")
async def set_session_title(session_id: str, req: SetTitleRequest):
    memory.set_session_title(session_id, req.title)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Routes - Model config
# ---------------------------------------------------------------------------
@app.get("/api/model/config")
async def get_model_config():
    return {
        "base_url": llm_client.config.base_url,
        "api_key": llm_client.config.api_key[:8] + "***" if len(llm_client.config.api_key) > 8 else "***",
        "model_name": llm_client.config.model_name,
        "temperature": llm_client.config.temperature,
        "max_tokens": llm_client.config.max_tokens,
    }


@app.get("/api/model/list")
def list_models():
    """Return candidate model names for the dropdown.

    Combines server-reported models with a sensible fallback list so the
    dropdown is always populated even if the /models endpoint is unavailable.
    """
    reported = llm_client.list_models()
    fallback = [
        "deepseek-v3.1",
        "deepseek-r1",
        "ernie-4.5-turbo-128k",
        "ernie-4.5-8k",
        "qwen3-max",
        "qwen2.5-72b-instruct",
        "doubao-pro-32k",
        "gpt-4o-mini",
    ]
    models: list[str] = []
    seen: set[str] = set()
    for m in reported + fallback:
        if m and m not in seen:
            models.append(m)
            seen.add(m)
    return {"models": models, "current": llm_client.config.model_name}


@app.post("/api/model/config")
async def set_model_config(req: ModelConfigRequest):
    llm_client.reconfigure(
        base_url=req.base_url,
        api_key=req.api_key,
        model_name=req.model_name,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    return {
        "base_url": llm_client.config.base_url,
        "model_name": llm_client.config.model_name,
        "temperature": llm_client.config.temperature,
        "max_tokens": llm_client.config.max_tokens,
    }


# ---------------------------------------------------------------------------
# Routes - Evaluation / Benchmark
# ---------------------------------------------------------------------------
@app.get("/api/eval/datasets")
async def eval_list_datasets():
    """List available benchmark datasets with subjects and question counts."""
    return JSONResponse(list_datasets())


@app.get("/api/eval/runs")
async def eval_list_runs():
    """List past evaluation runs."""
    runs = []
    for path in sorted(EVALS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            runs.append({
                "id": data["id"],
                "dataset_name": data.get("dataset_name", ""),
                "status": data.get("status", ""),
                "created_at": data.get("created_at", 0),
                "completed_at": data.get("completed_at", 0),
                "num_questions": data.get("num_questions", 0),
                "models": [m.get("model_name", "") for m in data.get("models", [])],
                "summary": data.get("summary", {}),
            })
        except Exception:
            continue
    return JSONResponse(runs)


@app.get("/api/eval/runs/{eval_id}")
async def eval_get_run(eval_id: str):
    """Get a specific evaluation run with full results."""
    run = EvalRun.load(eval_id)
    if run is None:
        return JSONResponse({"error": "Eval run not found"}, status_code=404)
    return JSONResponse(run.to_dict())


@app.get("/api/eval/runs/{eval_id}/cases")
async def eval_get_cases(eval_id: str, subject: str = "", model: str = "", offset: int = 0, limit: int = 50):
    """Get question-level detail for case analysis."""
    run = EvalRun.load(eval_id)
    if run is None:
        return JSONResponse({"error": "Eval run not found"}, status_code=404)

    results = run.results
    if subject:
        results = [r for r in results if r.get("subject") == subject]
    if model:
        results = [r for r in results if r.get("model_name") == model]

    # Group by question_id
    by_question: dict[str, list] = {}
    for r in results:
        qid = r.get("question_id", "")
        if qid not in by_question:
            by_question[qid] = []
        by_question[qid].append(r)

    # Load question text from dataset
    question_texts: dict[str, str] = {}
    try:
        questions = load_dataset(run.dataset_name, subjects=[subject] if subject else None)
        question_texts = {q.question_id: q.question for q in questions}
    except Exception:
        pass

    cases = []
    for qid, answers in sorted(by_question.items()):
        cases.append({
            "question_id": qid,
            "question": question_texts.get(qid, ""),
            "subject": answers[0].get("subject", "") if answers else "",
            "correct_answer": answers[0].get("correct_answer", "") if answers else "",
            "answers": answers,
        })

    total = len(cases)
    cases = cases[offset:offset + limit]

    return JSONResponse({"total": total, "cases": cases})


@app.delete("/api/eval/runs/{eval_id}")
async def eval_delete_run(eval_id: str):
    """Delete an evaluation run."""
    path = EVALS_DIR / f"{eval_id}.json"
    if path.exists():
        path.unlink()
        return {"deleted": True}
    return {"deleted": False}


# Global eval runner reference for cancellation
_current_eval_runner: EvalRunner | None = None


@app.websocket("/ws/eval")
async def ws_eval(ws: WebSocket):
    """WebSocket endpoint for running benchmark evaluations with progress streaming."""
    global _current_eval_runner
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            # Handle cancel
            if data.get("action") == "cancel":
                if _current_eval_runner:
                    _current_eval_runner.cancel()
                continue

            # Handle start
            if data.get("action") != "start":
                continue

            dataset_name = data.get("dataset", "")
            models = data.get("models", [])
            subjects = data.get("subjects", [])
            limit = data.get("limit")

            if not dataset_name or not models:
                await ws.send_text(json.dumps({"step": "error", "message": "缺少数据集或模型参数"}, ensure_ascii=False))
                continue

            # Create eval run
            eval_run = EvalRun(
                dataset_name=dataset_name,
                models=[m if isinstance(m, dict) else m.model_dump() for m in models],
                subject_filter=subjects,
                num_questions=limit or 0,
                status="pending",
            )
            eval_run.save()

            # Run in background thread
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue = asyncio.Queue()

            runner = EvalRunner(eval_run, loop, queue)
            _current_eval_runner = runner

            worker = threading.Thread(target=runner.run, daemon=True)
            worker.start()

            try:
                while True:
                    item = await queue.get()
                    await ws.send_text(json.dumps(item, ensure_ascii=False))
                    if item.get("step") in ("done", "error", "cancelled"):
                        break
            finally:
                _current_eval_runner = None

    except WebSocketDisconnect:
        logger.info("Eval WebSocket disconnected")
    except Exception as e:
        logger.error(f"Eval WebSocket error: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# WebSocket - Streaming chat + research
# ---------------------------------------------------------------------------
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    """WebSocket endpoint that streams research steps and saves to memory."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            # Handle cancel message
            if data.get("action") == "cancel":
                agent.cancel()
                continue

            session_id = data.get("session_id", "")
            message = data.get("message", "")
            mode = data.get("mode", "auto")  # "auto" | "research" | "chat"

            session = memory.get_session(session_id)
            if session is None:
                session = memory.create_session()
                session_id = session.id
                await ws.send_text(json.dumps({
                    "step": "session",
                    "message": "",
                    "data": {"session_id": session_id},
                }, ensure_ascii=False))

            # Save user message
            memory.add_message(session_id, "user", message)

            # Auto-generate title from first message
            if not session.title or session.title.startswith("Session-"):
                title = message[:30] + ("..." if len(message) > 30 else "")
                memory.set_session_title(session_id, title)

            # Run agent in a background thread; stream steps back via an asyncio.Queue
            # so the event loop stays free and each chunk flushes to the client at once.
            full_response = ""
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def _run_agent():
                try:
                    for step in agent.chat(message, session_id, mode=mode):
                        loop.call_soon_threadsafe(queue.put_nowait, step)
                except ResearchCancelledError:
                    loop.call_soon_threadsafe(queue.put_nowait, "cancelled")
                except Exception as e:  # noqa: BLE001
                    loop.call_soon_threadsafe(queue.put_nowait, e)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

            worker = threading.Thread(target=_run_agent, daemon=True)
            worker.start()

            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, str) and item == "cancelled":
                        await ws.send_text(json.dumps({
                            "step": "cancelled",
                            "message": "研究已取消",
                        }, ensure_ascii=False))
                        break
                    if isinstance(item, Exception):
                        logger.error(f"Agent error: {item}", exc_info=item)
                        await ws.send_text(json.dumps({
                            "step": "error",
                            "message": f"Agent error: {str(item)}",
                        }, ensure_ascii=False))
                        break

                    step = item
                    await ws.send_text(json.dumps({
                        "step": step.step,
                        "message": step.message,
                        "data": step.data,
                    }, ensure_ascii=False))

                    if step.step == "done" and step.message:
                        full_response = step.message
                    elif step.step == "synthesizing" and step.data and step.data.get("streaming"):
                        full_response += step.message

                # Save assistant response to memory
                if full_response:
                    memory.add_message(session_id, "assistant", full_response)

                await ws.send_text(json.dumps({
                    "step": "complete",
                    "message": "",
                    "data": {"session_id": session_id},
                }, ensure_ascii=False))

            except Exception as e:
                logger.error(f"Agent error: {e}", exc_info=True)
                await ws.send_text(json.dumps({
                    "step": "error",
                    "message": f"Agent error: {str(e)}",
                }, ensure_ascii=False))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    logger.info(f"Starting Deep Research Agent on http://{settings.server_host}:{settings.server_port}")
    uvicorn.run(app, host=settings.server_host, port=settings.server_port, log_level="info")
