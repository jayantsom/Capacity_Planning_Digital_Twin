# Data Operations

Data Operations combines two related modules behind one local interface:

- **Generator** creates validated, noisy synthetic source databases.
- **Pipeline** builds and promotes Bronze, Silver, Gold, and Serving databases.

The modules keep separate configuration, numbered steps, validations, and tests.
The web application provides Small/Medium/Full profiles, date and snapshot overrides,
always-on Low/Realistic/Stress Raw noise, bounded safety caps, progress, history,
rebuild, and rollback.
