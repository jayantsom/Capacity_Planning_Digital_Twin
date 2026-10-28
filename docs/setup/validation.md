# Validation and Testing

Validation is contract-based; fixed row counts and performance numbers are not acceptance criteria.

## Test suites

```powershell
# Run every app-owned test suite.
uv run pytest -q

# Check Python source style.
uv run ruff check .
```

## Generator gates

- Stable keys and checksums for identical seed/configuration
- Valid actual, forecast, and plan as-of dates
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
- Failed candidate cannot change a promotion pointer
- Prior promoted run remains a valid rollback target
- `release_current.json` selects compatible source, pipeline, and ML runs

## ML gates

- No cross-series or future leakage
- Temporal train/validation/holdout separation
- Naive baseline comparison
- Stable business keys and unique output grains
- Fold-local resampling
- `not_evaluable` behavior for edge cases
- Model checksum, feature schema, versions, and evaluation windows

## UI and API gates

- Every enabled route works on one local server
- Home lists every enabled application in registry order
- Read-only query restrictions and identifier validation
- Degraded Ollama health without Explorer failure
- Sanitized output/errors, timeout, one-heavy-job concurrency, and restart tests
- Keyboard, responsive, and WCAG 2.2 AA checks
- Yukti receives validated context and uses server-owned permissions
- Data Architecture metadata resolves to a Data Explorer object
