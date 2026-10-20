# Decision Intelligence

Owns five capacity-planning workflows and their dashboard:

1. Demand forecasting with recursive multi-month tree features.
2. Measured production-yield prediction and keyed SHAP explanations.
3. OEE degradation risk (not equipment-failure prediction).
4. Historical-fit OEE anomaly scoring with fixed severity thresholds.
5. CapEx Monte Carlo simulation with demand, yield, and OEE uncertainty.

Run all workflows with `uv run capacity-ml`. The run reads the validated
analytics database from `CAPACITY_TWIN_HOME`, stages all outputs, and changes
`ml_current.json` only after every requested workflow succeeds. Model files
carry a checksum, Python/library versions, training windows, and feature schema.

The `/decision-intelligence/` workspace provides five tabs, safe filters, KPIs,
mixed charts, rankings, dense tables, CSV export, and progress for full or
selected workflow jobs. A selected run can publish only by preserving a complete,
compatible prior publication.

Fast synthetic tests do not train production models:

```powershell
# Run only the Decision Intelligence tests.
uv run pytest decision_intelligence/tests -q
```

Workflows return `NOT_EVALUABLE` and preserve the prior publication when
required tables, time history, measured labels, or class variation are missing.
