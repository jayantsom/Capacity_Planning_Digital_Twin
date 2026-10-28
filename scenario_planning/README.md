# Scenario & What-If Planning

Browser-session scenarios compare governed baseline demand and capacity with bounded assumptions for demand, yield, OEE, shifts, equipment, retest, allocation, and overtime.

- Data: compatible release-pinned `serving.duckdb` only
- Route: `/scenario-planning/`
- API: filters, readiness, and bounded baseline data
- State: `sessionStorage`; no server save, approval, or promotion
- Exchange: versioned JSON and CSV with spreadsheet-formula escaping
- Tests: `pytest scenario_planning`

Cost and service trade-offs are intentionally omitted until governed facts exist.
