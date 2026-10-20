# Validation and Testing

Validation is contract-based; fixed row counts and performance numbers are not acceptance criteria.

## Test suites

```powershell
# Run every app-owned test suite.
uv run pytest -q

# Check Python source style.
uv run ruff check capacity_home capacity_assistant data_explorer data_operations decision_intelligence src
```

## Generator gates

- Stable keys and checksums for identical seed/configuration
- Valid actual, forecast, snapshot, and NPI dates
- Acyclic BOMs and conserved child demand
- Valid routes, sourcing, resource pools, and qualifications
- Physical tester/fixture/handler/licence constraints
- Declared noise only, with truth-manifest outcomes
- Projected rows, bytes, memory, time, and free-disk preflight

## Pipeline gates

- Separate candidate layer files
- Upstream files opened read-only
- Required schemas and business keys
- Stable deduplication and explicit quarantine
- Join-cardinality assertions
- Demand, execution, test-parameter, log, OEE, and capacity reconciliation
- Valid Serving views and read-only smoke queries
- Failed candidate cannot change `current.json`
- Prior promoted run remains a valid rollback target

## ML gates

- No cross-series or future leakage
- Temporal train/validation/holdout separation
- Naive baseline comparison
- Stable business keys and unique output grains
- Fold-local resampling
- `not_evaluable` behavior for edge cases
- Model checksum, feature schema, versions, and evaluation windows

## UI/API gates

- `/`, `/capacity-assistant/`, `/chat/`, `/explorer/`,
  `/decision-intelligence/`, and `/data-operations/` on one server
- Exactly four Home cards in the approved order
- Read-only query restrictions and identifier validation
- Degraded Ollama health without Explorer failure
- Sanitized output/errors, timeout, one-heavy-job concurrency, and restart tests
- Keyboard, responsive, and WCAG 2.2 AA checks

The current repository has app-owned tests, but a complete promoted-run smoke result was not verified during this documentation update.
