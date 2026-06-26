"""Deep Research Agent - core orchestration logic.

Flow:
  1. Analyze user query -> generate search queries
  2. Execute multi-engine searches -> collect sources
  3. Synthesize findings -> produce research report
  4. Optionally iterate for deeper research
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterator

from agent.llm import llm_client
from agent.memory import memory, ResearchNote
from agent.search import search_and_fetch, SearchResult
from config import settings

logger = logging.getLogger(__name__)

ENGINE_LABELS = {
    "baidu": "百度",
    "google": "Google",
    "scholar": "Scholar",
    "arxiv": "arXiv",
}


def _engine_label(engine: str) -> str:
    return ENGINE_LABELS.get(engine, engine)


@dataclass
class ResearchStep:
    """A single step in the research process, for streaming to frontend."""
    step: str       # "planning" | "searching" | "reading" | "synthesizing" | "done"
    message: str
    data: dict | None = None


class DeepResearchAgent:
    """Orchestrates multi-step deep research with multi-engine search + LLM."""

    def __init__(self):
        self.search_config = settings.search
        self.agent_config = settings.agent

    def research(
        self,
        query: str,
        session_id: str,
        *,
        max_iterations: int | None = None,
    ) -> Iterator[ResearchStep]:
        """Execute deep research, yielding steps for progress display."""
        max_iter = max_iterations or self.agent_config.max_research_iterations
        all_notes: list[ResearchNote] = []
        all_sources: list[dict] = []
        seen_urls: set[str] = set()

        # --- Step 1: Planning - generate search queries ---
        yield ResearchStep("planning", "正在分析问题并生成搜索策略...")

        context_msgs = memory.build_context_messages(session_id, query)
        plan = llm_client.chat_json(
            context_msgs + [{
                "role": "user",
                "content": (
                    f"用户问题: {query}\n\n"
                    "请分析这个问题，生成2-4个最有效的搜索关键词（支持百度、Google、Google Scholar、arXiv等搜索引擎），用于全面收集相关信息。\n"
                    "返回JSON: {\"queries\": [\"搜索词1\", \"搜索词2\", ...], "
                    "\"reasoning\": \"简要说明搜索策略\"}"
                ),
            }],
            temperature=0.2,
        )

        queries = plan.get("queries", [query])[: self.search_config.max_queries]
        reasoning = plan.get("reasoning", "")

        yield ResearchStep("planning", f"搜索策略: {reasoning}", {"queries": queries})

        # --- Step 2: Searching & Reading ---
        for qi, sq in enumerate(queries):
            if len(all_sources) >= self.agent_config.max_total_sources:
                break

            yield ResearchStep(
                "searching",
                f"[{qi+1}/{len(queries)}] 正在搜索: {sq}",
            )

            results = search_and_fetch(sq, self.search_config)

            # Group results by engine for display
            engine_counts: dict[str, int] = {}
            for r in results:
                e = r.engine or "unknown"
                engine_counts[e] = engine_counts.get(e, 0) + 1

            engine_summary = "、".join(f"{_engine_label(e)} {c}条" for e, c in engine_counts.items())
            yield ResearchStep(
                "searching",
                f"找到 {len(results)} 条结果（{engine_summary}）",
                {"query": sq, "results": [{"title": r.title, "url": r.url, "engine": r.engine} for r in results]},
            )

            # Extract key facts from results
            for r in results:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                all_sources.append({"title": r.title, "url": r.url, "query": sq})

                # Extract facts from page content
                if r.content:
                    facts = self._extract_facts(query, sq, r)
                    for fact in facts:
                        note = ResearchNote(
                            fact=fact,
                            source_url=r.url,
                            source_title=r.title,
                            query=sq,
                        )
                        all_notes.append(note)

                    yield ResearchStep(
                        "reading",
                        f"已阅读: {r.title[:50]}",
                        {"url": r.url, "facts_count": len(facts)},
                    )

        # Save research notes to session memory
        if all_notes:
            memory.add_research_notes(session_id, all_notes)

        # --- Step 3: Synthesizing ---
        yield ResearchStep("synthesizing", "正在综合分析所有资料，生成研究报告...")

        # Build research context for synthesis
        research_context = self._build_research_context(all_notes, all_sources)

        context_msgs = memory.build_context_messages(session_id, query)
        synthesis_messages = context_msgs + [{
            "role": "user",
            "content": (
                f"用户问题: {query}\n\n"
                f"## 搜索收集到的资料\n{research_context}\n\n"
                "请基于以上资料，撰写一份结构化的深度研究报告。要求:\n"
                "1. 直接回答用户问题\n"
                "2. 综合多个来源的信息，标注来源编号 [1] [2] 等\n"
                "3. 如果信息有矛盾或不足，请指出\n"
                "4. 使用 Markdown 格式，包含: 概述、关键发现、详细分析、总结\n"
                "5. 末尾列出参考来源列表"
            ),
        }]

        # Stream the final report
        report_chunks: list[str] = []
        for chunk in llm_client.stream(synthesis_messages, temperature=0.4):
            report_chunks.append(chunk)
            yield ResearchStep("synthesizing", chunk, {"streaming": True})

        final_report = "".join(report_chunks)

        # --- Done ---
        yield ResearchStep("done", final_report, {
            "sources": all_sources,
            "notes_count": len(all_notes),
            "queries_used": queries,
        })

    def _extract_facts(self, original_query: str, search_query: str, result: SearchResult) -> list[str]:
        """Extract key facts from a single search result page."""
        content = result.content or result.snippet
        if not content or len(content) < 50:
            return []

        try:
            data = llm_client.chat_json([
                {"role": "system", "content": "你是一个信息提取助手。从网页内容中提取与用户问题相关的关键事实。返回JSON。"},
                {"role": "user", "content": (
                    f"用户问题: {original_query}\n"
                    f"搜索词: {search_query}\n"
                    f"网页标题: {result.title}\n"
                    f"网页内容(节选):\n{content[:3000]}\n\n"
                    "请提取2-5条与问题相关的关键事实。\n"
                    "返回JSON: {\"facts\": [\"事实1\", \"事实2\", ...]}"
                )},
            ], temperature=0.1)
            return data.get("facts", [])
        except Exception as e:
            logger.debug(f"Fact extraction failed for {result.url}: {e}")
            return [content[:500]] if content else []

    def _build_research_context(self, notes: list[ResearchNote], sources: list[dict]) -> str:
        """Build a text context from research notes and sources."""
        lines: list[str] = []

        # Group notes by source
        for i, src in enumerate(sources, 1):
            src_notes = [n for n in notes if n.source_url == src["url"]]
            lines.append(f"\n### 来源 [{i}]: {src['title']}")
            lines.append(f"URL: {src['url']}")
            lines.append(f"搜索词: {src['query']}")
            if src_notes:
                for n in src_notes:
                    lines.append(f"- {n.fact}")
            lines.append("")

        return "\n".join(lines)

    def chat(self, query: str, session_id: str) -> Iterator[ResearchStep]:
        """Decide whether to do deep research or simple chat, then respond."""
        # Heuristic: if the query asks for research/info/search, do deep research
        research_keywords = [
            "搜索", "查找", "调研", "研究", "了解", "分析", "总结",
            "最新", "什么是", "怎么样", "如何", "为什么", "有哪些",
            "search", "research", "find", "analyze",
        ]

        needs_research = any(kw in query.lower() for kw in research_keywords) or len(query) > 20

        if needs_research:
            yield from self.research(query, session_id)
        else:
            # Simple chat using memory context
            context_msgs = memory.build_context_messages(session_id, query)
            context_msgs.append({"role": "user", "content": query})

            yield ResearchStep("synthesizing", "")
            for chunk in llm_client.stream(context_msgs):
                yield ResearchStep("synthesizing", chunk, {"streaming": True})
            yield ResearchStep("done", "", {"simple_chat": True})


# Global instance
agent = DeepResearchAgent()
