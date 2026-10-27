"""Operations Assistant configuration and local Ollama model factory."""

from langchain_ollama import ChatOllama

from capacity_twin_core.runtime.database_paths import load_app_config


def load_config() -> dict:
    """Load settings owned by Operations Assistant."""
    return load_app_config("operations_assistant")


def get_llm(streaming: bool = True) -> ChatOllama:
    """Return a timeout-bounded ChatOllama client."""
    cfg = load_config().get("agentic", {})
    timeout = float(cfg.get("timeout_seconds", 120))
    return ChatOllama(
        model=cfg.get("default_model", "llama3.1:8b"),
        base_url=cfg.get("ollama_base_url", "http://localhost:11434"),
        temperature=cfg.get("temperature", 0.1),
        num_predict=cfg.get("max_tokens", 4096),
        streaming=streaming,
        sync_client_kwargs={"timeout": timeout},
        async_client_kwargs={"timeout": timeout},
    )


def get_router_llm() -> ChatOllama:
    """Router uses the same model but non-streaming (needs full JSON response)."""
    cfg = load_config().get("agentic", {})
    timeout = float(cfg.get("timeout_seconds", 120))
    return ChatOllama(
        model=cfg.get("router_model", cfg.get("default_model", "llama3.1:8b")),
        base_url=cfg.get("ollama_base_url", "http://localhost:11434"),
        temperature=0.0,   # deterministic routing
        num_predict=64,    # only needs a short classification response
        streaming=False,
        sync_client_kwargs={"timeout": timeout},
        async_client_kwargs={"timeout": timeout},
    )
