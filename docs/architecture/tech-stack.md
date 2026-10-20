# Technology Stack

The essential project uses only free and open-source technologies.

| Area | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.12 | Application and workload code |
| Environment | uv | Locking, installation, and script execution |
| Raw storage | SQLite | Ten independent synthetic source databases |
| Analytical storage | DuckDB | Separate Bronze, Silver, Gold, ML, and Serving files |
| Data processing | pandas, Polars, PyArrow, PySpark 4.1.2 | Local transforms and Silver processing |
| ML | scikit-learn, XGBoost, LightGBM, Prophet, SHAP, imbalanced-learn | Five existing workflows |
| Assistant | LangGraph, LangChain, MCP | Routing and guarded read-only tools |
| Local model | Ollama with `llama3.1:8b` | Capacity Assistant baseline |
| API | FastAPI, Uvicorn, Pydantic | Local server and typed APIs |
| UI | HTML, CSS, JavaScript, local SVG/DOM charts | Offline-capable application dashboards |
| Quality | pytest, coverage, Ruff | App-owned tests and static checks |

Version truth comes from `pyproject.toml` and `uv.lock`; documentation does not assert unpinned “latest” behavior.

## Design choices

- SQLite and DuckDB keep the project serverless and suitable for one local workstation.
- Separate database files create clear ownership and read-only boundaries.
- PySpark remains for the existing Silver workflow; it is not a claim that distributed infrastructure is required.
- Plain browser assets avoid a frontend build tool and keep every dashboard offline-capable.
- Ollama keeps inference local. Data Explorer does not depend on a model being available.
- CapEx uses Monte Carlo simulation; no optimization solver is claimed.

## Future alternatives

Future Capacity Assistant evaluations may benchmark verified, licensed Ollama tags for Qwen 3.5 4B-class, Granite 4.2 8B-class, and Qwen 3.5 9B-class models. Selection must use project-specific numerical, tool-call, latency, and memory tests. `llama.cpp` is the preferred lightweight runtime alternative; LocalAI is conditional, and vLLM is deferred to a Linux GPU environment.

PostgreSQL, Kafka, cloud services, containers, Kubernetes, dbt, Dagster, MLflow, and a feature-store platform are not part of the essential delivery.
