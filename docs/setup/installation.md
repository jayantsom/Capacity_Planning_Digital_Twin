# Installation

---

## Prerequisites

| Tool | Version | Purpose | Install |
|---|---|---|---|
| Python | 3.12.12 | Runtime | [python.org](https://python.org) or pyenv |
| uv | Latest | Package manager | `pip install uv` |
| Java (Temurin JDK) | 17 | PySpark requires JVM | [adoptium.net](https://adoptium.net) |
| Git | Any | Source control | [git-scm.com](https://git-scm.com) |
| Ollama | Latest | Local LLM runtime | [ollama.com](https://ollama.com) |

**Hardware minimum**: 8GB RAM, 4-core CPU, 10GB free disk.
**Recommended**: 16GB RAM, NVIDIA GPU with 4GB+ VRAM for llama3.1:8b inference speed.

---

## Setup

```bash
# 1. Clone
git clone <repo-url>
cd capacity_planning_digital_twin

# 2. Create virtual environment and install all dependencies
uv sync

# 3. Pull the LLM model (one-time, ~4.7GB download)
ollama pull llama3.1:8b

# 4. Verify Java is on PATH (required for PySpark)
java -version   # should print: openjdk version "17..."
```

---

## Dependencies (pyproject.toml)

### Pipeline
`duckdb`, `pandas`, `pyspark==4.1.2`, `pyyaml`, `loguru`

### ML
`scikit-learn>=1.5`, `xgboost>=2.1`, `lightgbm>=4.4`, `prophet>=1.1`, `shap>=0.46`, `imbalanced-learn>=0.12`, `scipy>=1.13`

### Agentic
`langgraph`, `langchain`, `langchain-ollama`, `langchain-core`, `fastapi`, `uvicorn`, `pydantic>=2`

> **Prophet note**: First run downloads and compiles CmdStan (~2 min). Subsequent runs use the cached binary. Set `CMDSTAN_PATH` env var to control the cache location.

---

## Verify installation

```bash
uv run python -c "
import duckdb, pyspark, xgboost, prophet, shap, langgraph, fastapi
print('All imports OK')
"
```

```bash
ollama list   # should show llama3.1:8b
```
