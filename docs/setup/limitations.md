# Known Limitations

---

| Area | Limitation | Workaround |
|---|---|---|
| **LLM speed** | llama3.1:8b takes 40–80s per query (2 LLM calls per agent) | Use `qwen3.5:4b` for faster but less reliable tool calling |
| **Token truncation** | Answers with many data points may be cut at `num_predict=4096` | Increase `max_tokens` in `settings.yaml`; reduce `limit` arg in tool calls |
| **Token streaming** | Tokens are word-split from final answer string, not true Ollama streaming | Acceptable for demo; true streaming requires async Ollama client integration |
| **Forecast future features** | XGBoost/LGB lag features for future months use last-known values, not recursive predictions | Acceptable for 18-month horizon; longer horizons need recursive forecasting |
| **Silver → DuckDB write** | PySpark DataFrames are collected to pandas before DuckDB write (no native connector) | For production scale: write to Parquet, then `COPY INTO` DuckDB |
| **No incremental pipeline** | Every layer uses drop-and-recreate; full pipeline re-runs take ~17 min total | Acceptable for synthetic data; production would need CDC / incremental logic |
| **Single DuckDB writer** | Only one process can write to DuckDB at a time | Run pipeline steps sequentially (enforced by `run_*.py` entry points) |
| **SHAP on 383K rows** | SHAP computation takes ~7 min; must run on full dataset | Sample to 50K rows if speed is critical: `fs_feat.sample(50_000)` |
| **No auth on APIs** | FastAPI endpoints have no authentication | Intentional for local portfolio use; add OAuth2 / API key before any network exposure |
| **Plotly warning** | Prophet dependency prints `"Importing plotly failed"` at startup | Harmless; suppress with `uv add plotly` or ignore |
| **No Airflow orchestration** | Pipeline steps are run manually in sequence | Airflow DAG is planned (see Future Scope) |
