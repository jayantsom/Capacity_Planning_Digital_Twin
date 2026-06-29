# Tech Stack

> Every technology listed here is actively used in the implemented codebase. Nothing is aspirational or planned.

---

## Full Stack Table

| Category | Technology | Version | Role | Why This Choice |
|---|---|---|---|---|
| **Language** | Python | 3.12.12 | Entire codebase | Modern Python with full type annotation support, best ML ecosystem |
| **Package Manager** | uv | Latest | Dependency management, virtual env, script runner | Significantly faster than pip; single tool replaces pip + venv + pip-tools |
| **Raw Storage** | SQLite | Built-in | 10 source databases | Zero-config, file-based, ideal for isolated domain tables |
| **Analytics DB** | DuckDB | Latest | All Bronze/Silver/Gold layers | Columnar, in-process, handles 10M+ rows without a server; native Parquet/Arrow support |
| **Transform Engine** | PySpark | 4.1.2 | Silver layer transforms | Demonstrates distributed processing capability; handles complex joins at scale |
| **Java** | Temurin JDK 17 | 17 | Required by PySpark | PySpark requires a JVM |
| **Data Manipulation** | pandas | Latest | ML pipeline data handling | Standard DataFrame API; used post-Spark for ML feature prep |
| **Forecasting** | Prophet | 1.1.x | Priority 1 demand forecast | Handles seasonality, holidays, and trend changes; interpretable |
| **Gradient Boosting** | XGBoost | 2.1.x | Yield prediction, maintenance | Native tool-calling support in tree models; SHAP-compatible |
| **Gradient Boosting** | LightGBM | 4.4.x | Demand forecast ensemble | Faster training than XGBoost for large datasets; good for lag features |
| **Explainability** | SHAP | 0.46.x | Yield prediction drivers | TreeExplainer gives exact Shapley values for tree models; production-grade |
| **Imbalanced Learning** | imbalanced-learn | 0.12.x | SMOTE for maintenance model | Standard library for class imbalance; SMOTE is well-understood |
| **Anomaly Detection** | scikit-learn | 1.5.x | Isolation Forest for OEE | Contains Isolation Forest; also provides StandardScaler, TimeSeriesSplit |
| **Statistical** | scipy | 1.13.x | Beta distribution fitting (Monte Carlo) | Method-of-moments fitting for uncertainty distributions |
| **Agent Framework** | LangGraph | Latest | Multi-agent orchestration | State machine model ideal for router → agent → END flow; built on LangChain |
| **LLM Integration** | LangChain | Latest | LLM abstraction layer | ChatOllama wrapper; tool-calling interface |
| **Local LLM** | Ollama | Latest | LLM runtime | Runs quantised models locally; no API cost; offline-capable |
| **LLM Model** | llama3.1:8b | 8B params | All agent LLM calls | Only model in the local set with native tool/function calling support |
| **API Framework** | FastAPI | Latest | Chat backend + Data Explorer | Async, SSE streaming, Pydantic validation; production-grade |
| **ASGI Server** | uvicorn | Latest | FastAPI server | Standard ASGI runner for FastAPI |
| **Schema Validation** | Pydantic | v2 | Request/response models | Tight integration with FastAPI; v2 is faster |
| **Logging** | loguru | Latest | All pipeline logging | Single `logger` object; coloured output; file rotation built-in |
| **Config** | PyYAML | Latest | settings.yaml parsing | Standard YAML parser; used in agentic config loader |
| **Frontend** | Vanilla HTML/CSS/JS | — | Chat UI | No build step; UnoCSS CDN + IBM Plex fonts |
| **Explorer Frontend** | Vanilla HTML/CSS/JS | — | Data Explorer UI | No build step; Inter + JetBrains Mono fonts |
| **Charts** | Chart.js | 4.4.0 | Data Explorer visualisations | No build step required; comprehensive chart types |
| **Fonts** | IBM Plex Sans/Mono/Serif | — | Chat UI typography | IBM's open-source type system; designed for data applications |
| **Fonts** | Inter + JetBrains Mono | — | Explorer typography | Inter for UI labels; JetBrains Mono for data values |

---

## Architecture Decision Records

### Why DuckDB instead of PostgreSQL?

DuckDB is an **in-process analytical database** — it runs inside the Python process with no server to manage. For a local portfolio project processing ~10M rows across joined tables, DuckDB outperforms PostgreSQL at this scale without the operational overhead. Its columnar storage and vectorised execution make analytical aggregations 10–100x faster than row-store databases for the types of queries the capacity engine runs.

### Why PySpark for Silver transforms?

PySpark is used in the Silver layer to demonstrate that the architecture can scale to distributed processing. The same transforms run on a Spark cluster without code changes — only the SparkSession configuration changes from `local[*]` to a cluster URL. This is intentional for demonstrating enterprise-grade engineering.

### Why llama3.1:8b and not the other local models?

| Model | Tool Calling | 4GB VRAM | Notes |
|---|---|---|---|
| `gemma3:4b` | Limited | ✅ | Insufficient for reliable JSON tool call generation |
| `qwen3.5:4b` | Good | ✅ | No native function calling schema support |
| `llama3.1:8b` | **Native** | ✅ (Q4) | Built-in function/tool calling; reliable JSON output |
| `deepseek-r1:8b` | Good | ⚠️ | Chain-of-thought adds latency; better for reasoning than tool dispatch |

`llama3.1:8b` is the only model in this set with native tool calling — it was trained on function-calling data and reliably produces structured JSON tool call responses.

### Why LangGraph instead of raw LangChain?

LangGraph models the agent system as a **directed state graph** — each node (router, agent) transforms a shared `AgentState` TypedDict and passes it to the next node. This makes the flow auditable, testable node-by-node, and extensible (adding a new agent = adding one node and one conditional edge). Raw LangChain agent executors are less transparent and harder to customise for multi-domain routing.

### Why MCP (Model Context Protocol)?

The MCP server architecture separates **tool implementation** (what data to query) from **agent logic** (when and how to query it). This means:
1. Tools can be tested independently of agents (see `test_server.py`)
2. The same tools are reusable by any MCP-compatible client (including Claude Desktop)
3. The read-only connection guarantee is enforced at the tool layer, not the agent layer

### Why uv instead of pip?

`uv` resolves and installs dependencies 10–100x faster than pip, handles virtual environments natively, and provides a single `uv run` command that manages the Python path. For a project with ~20 dependencies including compiled packages (XGBoost, LightGBM, PySpark), this meaningfully improves the development experience.
