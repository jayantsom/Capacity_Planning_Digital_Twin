# Operations Flow

Production Control, Industrial Engineering, and Test Operations views show WIP, queue age, cycle-time percentiles, throughput, rework, route adherence, schedule attainment, and dynamic bottlenecks.

- Data: compatible release-pinned `serving.duckdb` only
- Route: `/operations-flow/`
- Grain: daily where event-derived Serving facts support it
- Filter applicability: declared per dataset
- Sankey: withheld until a self-contained route-event Serving fact exposes from/to operations
- Tests: `pytest operations_flow`
