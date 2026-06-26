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
from config import settings, ModelConfig

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
