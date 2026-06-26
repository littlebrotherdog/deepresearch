"""Deep Research Agent - Configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ModelConfig:
    """Configurable base model via IP/base_url + api_key."""

    base_url: str = os.environ.get("DR_MODEL_BASE_URL", "http://amu.dbh.baidu-int.com/v1")
    api_key: str = os.environ.get("DR_MODEL_API_KEY", "sk-oXC9rgXuXSKLuSA5JFZF0pE62adTWEipF5dHv9la2u6SFYQm")
    model_name: str = os.environ.get("DR_MODEL_NAME", "deepseek-v3.1")
    temperature: float = float(os.environ.get("DR_MODEL_TEMPERATURE", "0.3"))
    max_tokens: int = int(os.environ.get("DR_MODEL_MAX_TOKENS", "4096"))


@dataclass
class SearchConfig:
    """Search engine configuration."""

    max_results_per_query: int = 8
    max_queries: int = 4
    snippet_only: bool = False  # if True, don't fetch full page content
    fetch_timeout: int = 10
    max_content_length: int = 5000  # chars per page
    use_https: bool = False  # HTTP by default for better proxy compatibility
    proxy: str = os.environ.get("DR_SEARCH_PROXY", "http://amu_2026:amu_2026_test@10.61.124.44:8600")
    engines: list[str] = field(
        default_factory=lambda: os.environ.get(
            "DR_SEARCH_ENGINES", "baidu,google,scholar,arxiv"
        ).split(",")
    )


@dataclass
class AgentConfig:
    """Deep research agent configuration."""

    max_research_iterations: int = 3
    max_total_sources: int = 12
    short_term_message_limit: int = 20  # messages kept in short-term memory
    summary_trigger: int = 10  # summarize when messages exceed this count


@dataclass
class Settings:
    model: ModelConfig = field(default_factory=ModelConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server_host: str = os.environ.get("DR_HOST", "0.0.0.0")
    server_port: int = int(os.environ.get("DR_PORT", "7860"))


settings = Settings()
