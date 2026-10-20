# Known Limitations

- PySpark on Windows emits a non-blocking `winutils.exe` warning when Hadoop
  helpers are not installed.
- Full production-sized generation, medallion, ML, and Ollama workloads should
  not run concurrently on the 16 GB local profile.
- OEE degradation labels are synthetic proxies, not verified equipment failures.
- CapEx output is a synthetic Monte Carlo scenario, not an investment recommendation.
- Real EMS locations and equipment-vendor/model status require source verification immediately before catalog activation.
- No authentication is provided; the approved delivery is local-only on loopback.

Do not infer production readiness, dataset scale, runtime, forecast quality, or model accuracy from this project.
