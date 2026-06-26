"""Memory management system with session-based storage.

Each session stores:
  - metadata (id, title, created_at, updated_at)
  - short_term: recent conversation messages (raw)
  - long_term: periodic summaries of earlier conversation
  - research: accumulated research findings (facts + sources)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from config import SESSIONS_DIR, AgentConfig
from agent.llm import llm_client

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResearchNote:
    """A single research finding with source."""
    fact: str
    source_url: str
    source_title: str
    query: str  # the search query that found this

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Session:
    id: str
    title: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    short_term: list[dict] = field(default_factory=list)  # recent messages
    long_term: list[dict] = field(default_factory=list)  # summaries
    research: list[dict] = field(default_factory=list)  # ResearchNotes

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self):
        self.updated_at = time.time()
        path = SESSIONS_DIR / f"{self.id}.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def add_message(self, role: str, content: str):
        self.short_term.append(Message(role=role, content=content).to_dict())
        self.save()

    def add_research_notes(self, notes: list[ResearchNote]):
        for n in notes:
            self.research.append(n.to_dict())
        self.save()


class MemoryManager:
    """Manages sessions and memory consolidation."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()

    def create_session(self, title: str = "") -> Session:
        sid = uuid.uuid4().hex[:12]
        session = Session(id=sid, title=title or f"Session-{sid[:6]}")
        session.save()
        return session

    def get_session(self, session_id: str) -> Session | None:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Session(**data)

    def list_sessions(self) -> list[dict]:
        sessions = []
        for path in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "id": data["id"],
                    "title": data.get("title", ""),
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                    "message_count": len(data.get("short_term", [])),
                    "research_count": len(data.get("research", [])),
                })
            except Exception:
                continue
        return sessions

    def delete_session(self, session_id: str) -> bool:
        path = SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def add_message(self, session_id: str, role: str, content: str):
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        session.add_message(role, content)

        # Trigger summarization if short_term is too long
        if len(session.short_term) > self.config.summary_trigger + self.config.short_term_message_limit:
            self._consolidate(session)

    def add_research_notes(self, session_id: str, notes: list[ResearchNote]):
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        session.add_research_notes(notes)

    def _consolidate(self, session: Session):
        """Summarize older messages into long-term memory."""
        # Keep the most recent messages, summarize the rest
        cutoff = self.config.short_term_message_limit
        to_summarize = session.short_term[:-cutoff]
        to_keep = session.short_term[-cutoff:]

        if not to_summarize:
            return

        try:
            conv_text = "\n".join(
                f"[{m['role']}]: {m['content'][:500]}" for m in to_summarize
            )
            summary = llm_client.chat([
                {"role": "system", "content": "你是一个记忆管理助手。请将以下对话片段压缩为简洁的摘要，保留关键事实、用户意图和研究结论。用中文回答。"},
                {"role": "user", "content": f"请总结以下对话：\n\n{conv_text}"},
            ], temperature=0.1, max_tokens=512)

            session.long_term.append({
                "summary": summary,
                "timestamp": time.time(),
                "message_range": f"{len(to_summarize)} messages summarized",
            })
            session.short_term = to_keep
            session.save()
            logger.info(f"Consolidated {len(to_summarize)} messages into long-term memory")
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")

    def build_context_messages(self, session_id: str, current_query: str) -> list[dict]:
        """Build the message list for LLM, including memory context."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        messages: list[dict] = []

        # System prompt with research context
        system_parts = ["你是一个深度研究助手(Deep Research Agent)，能通过多引擎搜索（百度、Google、Google Scholar、arXiv）收集信息并进行综合分析总结。"]

        if session.long_term:
            summaries = "\n---\n".join(s["summary"] for s in session.long_term[-3:])
            system_parts.append(f"\n## 历史对话摘要\n{summaries}")

        if session.research:
            recent_research = session.research[-10:]
            research_text = "\n".join(
                f"- [{r['source_title']}] {r['fact']}" for r in recent_research
            )
            system_parts.append(f"\n## 已收集的研究资料\n{research_text}")

        messages.append({"role": "system", "content": "\n".join(system_parts)})

        # Add recent conversation history
        for m in session.short_term[-self.config.short_term_message_limit:]:
            messages.append({"role": m["role"], "content": m["content"]})

        return messages

    def set_session_title(self, session_id: str, title: str):
        session = self.get_session(session_id)
        if session:
            session.title = title
            session.save()


# Global instance
memory = MemoryManager()
