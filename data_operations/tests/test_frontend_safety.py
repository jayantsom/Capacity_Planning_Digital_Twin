"""Static safety checks for the Data Operations frontend."""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_frontend_has_two_tabs_and_no_remote_assets() -> None:
    """Keep Generator and Pipeline local and available from one workspace."""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert html.count('role="tab"') == 2
    assert "Data Generator" in html
    assert "Data Pipeline" in html
    assert "<h1>Data Operations</h1>" in html
    assert 'class="service-status status-checking"' in html
    assert '<span class="brand-mark" aria-hidden="true">CP</span>' in html
    assert 'href="/">Home</a>' in html
    assert 'id="generateButton"' in html
    assert 'id="pipelineButton"' in html
    assert "Rebuild all" not in html
    assert 'id="generatorStatus"' in html
    assert 'id="pipelineStatus"' in html
    assert 'id="clearRawButton"' in html
    assert 'id="clearAllButton"' in html
    assert not re.search(r"https?://", html)
    assert not re.search(r"\son[a-z]+=", html, re.IGNORECASE)


def test_frontend_renders_api_values_with_text_content() -> None:
    """Do not place API-controlled data into executable HTML."""
    script = (FRONTEND / "data-operations.js").read_text(encoding="utf-8")
    assert ".textContent =" in script
    assert "setHealthStatus('offline')" in script
    assert "sentenceCase(job.kind)" in script
    assert "jobs/rebuild" not in script
    assert "'/data-operations/api/data/clear-raw'" in script
    assert "'/data-operations/api/data/clear-all'" in script
    assert ".innerHTML" not in script
    assert "eval(" not in script
