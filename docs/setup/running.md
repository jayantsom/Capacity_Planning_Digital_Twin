# Running the Project

> All commands run from the project root. Always run steps in order — each layer depends on the previous.

---

## Full pipeline execution

```bash
# Step 1 — Generate raw data (~2 min)
uv run python -m src.generators.run_all_generators

# Step 2 — Bronze ingestion (~30s)
uv run python -m src.pipeline.bronze.ingest

# Step 3 — Silver transforms (~135s)
uv run python -m src.pipeline.silver.run_silver

# Step 4 — Gold capacity math (~60s)
uv run python -m src.pipeline.gold.run_gold

# Step 5 — ML pipeline (~15 min)
uv run python -m src.ml.run_ml
```

---

## Expected outputs per step

| Step | Key log lines to confirm success |
|---|---|
| Generators | `Generated X rows → data/sites.db` × 10 |
| Bronze | `Ingested brnz_* — 0 invalid rows` × 12 |
| Silver | `slvr_demand_planning: 850,xxx rows written` |
| Gold | `gold_ml_feature_store: 383,128 rows` |
| ML | `ML PIPELINE COMPLETE — 5/5 succeeded` |

---

## Starting the backends

```bash
# Terminal 1 — start Ollama
ollama serve

# Terminal 2 — AI chat backend (port 8000)
uv run python -m backend.main

# Terminal 3 — Data Explorer backend (port 8001)
uv run uvicorn backend.explorer.main:app --host 0.0.0.0 --port 8001 --reload
```

| URL | Interface |
|---|---|
| `http://localhost:8000` | AI Analyst chat UI |
| `http://localhost:8000/docs` | FastAPI auto-docs |
| `http://localhost:8001/explorer/` | Data Explorer |

---

## Running individual ML priorities

```bash
# Run specific priorities only (e.g. re-run yield after schema change)
uv run python -c "
from src.ml.run_ml import run_ml_pipeline
run_ml_pipeline(priorities=[2, 3])
"
```

---

## Running smoke tests

```bash
# MCP server (19 tests)
uv run python agentic/mcp_server/test_server.py

# Agent orchestrator (10 tests — requires ollama serve)
uv run python agentic/agents/test_agents.py
```

---

## Re-running from a specific layer

If only Gold data changed (e.g. capacity math fix), skip generators and Bronze/Silver:

```bash
uv run python -m src.pipeline.gold.run_gold
uv run python -m src.ml.run_ml
# then restart backends
```

Gold uses `DROP TABLE IF EXISTS` before recreating — safe to re-run any number of times.
