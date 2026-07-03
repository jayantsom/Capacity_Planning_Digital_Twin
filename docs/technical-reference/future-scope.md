# Future Scope

> Planned improvements not yet implemented.

---

| Area | Planned Enhancement |
|---|---|
| **Orchestration** | Airflow DAG wrapping all 5 pipeline steps with dependency management and alerting |
| **Incremental pipeline** | Change-data-capture for Bronze; partition-aware Silver/Gold refreshes |
| **True LLM streaming** | Replace word-split token emission with native Ollama async streaming client |
| **Power BI dashboard** | Connect via DuckDB ODBC driver or Parquet export; 6 pages across 6 serving views |
| **Recursive forecasting** | Update lag features recursively for multi-step ahead XGBoost/LGB predictions |
| **Multi-turn conversation** | Persist `AgentState.messages` across sessions (Redis or SQLite session store) |
| **Agent memory** | Summarise prior tool results so agents can reference earlier answers in conversation |
| **Claude Desktop integration** | Register MCP server in `claude_desktop_config.json` for direct Claude Desktop queries |
| **Yield feedback loop v2** | Run ML pipeline after Gold on every pipeline refresh; keep `gold_cap_ml_adjusted` always current |
| **UI improvements** | Chat UI: typing indicator, copy button, conversation history, message timestamps |
| **Model retraining triggers** | Auto-retrain ML models when new actuals arrive (drift detection via PSI/KS test) |
| **Confidence intervals** | Expose Prophet prediction intervals in `gold_demand_forecast` |
