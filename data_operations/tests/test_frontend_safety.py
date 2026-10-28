"""Static safety checks for the Data Operations frontend."""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_frontend_has_three_tabs_and_no_remote_assets() -> None:
    """Keep all Data Operations workspaces local."""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert html.count('role="tab"') == 3
    assert "Data Generator" in html
    assert "Data Pipeline" in html
    assert "Data Architecture" in html
    assert 'data-title="Data Operations"' in html
    assert 'class="service-status status-checking"' in html
    assert "data-shared-shell" in html
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


def test_summary_band_matches_decision_intelligence_format() -> None:
    stylesheet = (FRONTEND / "data-operations.css").read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in stylesheet
    assert "min-height: 66px" in stylesheet
    assert "font: 700 18px var(--mono)" in stylesheet


def test_architecture_legend_uses_display_labels() -> None:
    script = (FRONTEND / "data-operations.js").read_text(encoding="utf-8")
    assert "function architectureLayerLabel(layer)" in script
    assert "return layer === 'ml' ? 'ML' : sentenceCase(layer)" in script
    assert "category: architectureLayerLabel(layer)" in script
    assert "name: architectureLayerLabel(layer)" in script
