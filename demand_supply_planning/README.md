# S&OP Planning

Executive, Demand Planner, and Capacity Planner views show reconciled demand, constrained production, receipts, shipments, inventory, separate backlog, coverage, allocation, service risk, and exceptions.

- Data: compatible release-pinned `serving.duckdb` only
- Route: `/demand-supply-planning/`
- Reconciliation: beginning inventory + production + receipts - shipments = ending inventory
- Action register: browser-session only with versioned import/export
- Tests: `pytest demand_supply_planning`

Fill rate is shown only as a declared target. The app does not infer an actual service rate.
