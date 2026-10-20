# Capacity Twin Core

Contains small shared contracts used by more than one app, including runtime
paths, dates, logging, local job state, safe dashboard helpers, domain constants,
and trusted capacity formulas.

It does not own app-specific business workflows. Settings are in `config.yaml`;
shared contract tests are kept in this package's `tests` folder. Application-specific
business logic and configuration must remain in the owning app.
