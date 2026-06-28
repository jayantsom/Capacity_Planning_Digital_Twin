"""
Shared config and LLM factory for all agents.
Reads agentic settings from config/settings.yaml.
"""

from pathlib import Path
import yaml

from langchain_ollama import ChatOllama

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH  = _PROJECT_ROOT / "config" / "settings.yaml"


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_llm(streaming: bool = True) -> ChatOllama:
    """Return a ChatOllama instance configured from settings.yaml."""
    cfg = load_config().get("agentic", {})
    return ChatOllama(
        model=cfg.get("default_model", "llama3.1:8b"),
        base_url=cfg.get("ollama_base_url", "http://localhost:11434"),
        temperature=cfg.get("temperature", 0.1),
        num_predict=cfg.get("max_tokens", 4096),
        streaming=streaming,
    )


def get_router_llm() -> ChatOllama:
    """Router uses the same model but non-streaming (needs full JSON response)."""
    cfg = load_config().get("agentic", {})
    return ChatOllama(
        model=cfg.get("router_model", cfg.get("default_model", "llama3.1:8b")),
        base_url=cfg.get("ollama_base_url", "http://localhost:11434"),
        temperature=0.0,   # deterministic routing
        num_predict=64,    # only needs a short classification response
        streaming=False,
    )
