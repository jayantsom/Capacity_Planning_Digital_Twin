# Installation

## Prerequisites

- Windows target with approximately 16 GB RAM
- Git
- uv
- Python 3.12, managed by uv
- Java 17 for PySpark
- Optional Ollama for Capacity Assistant

GPU acceleration is optional. Do not run PySpark, full-data ML, and Ollama concurrently on the one-machine profile.

## Install

```powershell
# Clone the project and install its locked environment.
git clone <repo-url>
cd Capacity_Planning_Digital_Twin
uv sync --extra dev --locked

# Confirm the core runtimes.
uv run python --version
java -version
```

`uv.lock` is the reproducibility source. Dependency versions should not be copied into documentation unless they are verified against the lock.

### Windows PySpark path fallback

PySpark is built from its source distribution. If Windows reports that a deeply
nested PySpark example file cannot be created, use short temporary and cache paths:

```powershell
# Short paths avoid the Windows source-build path limit.
$env:UV_CACHE_DIR = "D:\uv-cache"
$env:TEMP = "D:\uv-temp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
uv sync --extra dev --locked
```

## Runtime directory

Generated data and models must stay outside the repository:

```powershell
# Choose an external runtime location for this shell.
$env:CAPACITY_TWIN_HOME = "$env:LOCALAPPDATA\CapacityPlanningDigitalTwin"
```

If unset, Capacity Twin Core uses that same Windows location by default.

## Optional Capacity Assistant model

```powershell
# Install the current local baseline model.
ollama pull llama3.1:8b
ollama serve
```

Ollama is not required for Data Explorer or non-AI data workloads. Future model alternatives are not installation prerequisites.
