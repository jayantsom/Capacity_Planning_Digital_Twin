# Data Generator

Creates deterministic, configurable telecom manufacturing data. Raw output is
intentionally noisy so the medallion pipeline can demonstrate data cleaning.

Run with `uv run capacity-generate`. Settings are in `config.yaml`; tests are
kept in this app's `tests` folder.

The default `local_16gb` profile is capped before any database is written. It
uses 30 sites, 48 products, 24 route-driven test types, sparse site/product
sources, and configurable `low`, `medium`, or `high` fact density. All profiles
keep the same contractual actual and forecast boundaries.

Generation order is visible in `steps/1_...py` through `steps/7_...py`.
Reusable rules, catalogs, services, and blocking validations live in their
named folders. A run is built under `CAPACITY_TWIN_HOME/artifacts`, validated,
and only then atomically published to the Raw folder. Its manifest records
checksums, row counts, projections, validations, and declared noise rules.

The catalog is synthetic educational data. Erivon is fictional. Real
manufacturer and EMS names are reference data only; generated capabilities,
products, volumes, routes, and performance imply no affiliation or factual
claim about those companies.

Run focused tests with:

`uv run pytest data_operations/generator/tests -q`
