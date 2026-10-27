# Glossary

| Term | Meaning |
|---|---|
| Actual cutoff | Last permitted actual/execution date: 2026-10-31 |
| BOM-dependent demand | Child requirement exploded from parent demand |
| Bronze | Typed, validated representation of Raw records and defects |
| CapEx simulation | Monte Carlo equipment-need scenarios; not optimization |
| Capacity behavior | One of seven explicit ways a route step consumes a resource |
| Candidate run | Unpromoted artifact set being built and validated |
| Snapshot window | Browser-scoped inclusive date range: TOTAL, SNAPSHOT 1, or SNAPSHOT 2; it does not create a Raw-data copy |
| Control catalog | Application-owned mappings, rules, qualifications, and windows stored outside Raw |
| DuckDB | In-process analytical database used for processed layers |
| Erivon | Fictional telecom/networking brand used by the synthetic catalog |
| Forecast horizon | 2026-11-01 through 2027-12-31 in the approved dataset |
| Gold | Reconciled capacity and analytical outputs |
| Manifest | Machine-readable run provenance, checksums, counts, validation, and promotion state |
| MCP | Model Context Protocol used for Operations Assistant’s structured data tools |
| Multi-DUT | Parallel test configuration constrained by physical/licensed resources and measured throughput |
| Noise truth manifest | Private record of intentionally injected Raw defects and expected outcomes |
| OEE | Availability × performance × quality |
| OEE degradation risk | Synthetic classifier target; not a verified equipment-failure prediction |
| Platform Core | Shared contracts, paths, dates, logging, and trusted equations |
| Promoted run | Validated run selected by `current.json` |
| Raw | Ten independent synthetic SQLite source databases |
| Serving | Stable read-only views consumed by Operations Assistant and Data Explorer |
| Silver | Conformed, deduplicated, reconciled data with explicit quarantine |
| Planning version | As-of planning view that cannot know future actuals |
| ISO week | Monday-to-Sunday operational period identified as `YYYY-Www` |
| Temporal evaluation | Training and evaluation split in chronological order |
| Operations Assistant | Local operations-analysis assistant using Ollama and read-only tools |
