"""Static contracts for the Decision Intelligence frontend."""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_frontend_has_five_tabs_and_local_assets() -> None:
    """Keep the five workflow dashboards inside the local application."""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert html.count('role="tab"') == 5
    assert "Run all workflows" in html
    assert "Export CSV" in html
    assert 'data-title="Decision Intelligence"' in html
    assert 'class="service-status status-checking"' in html
    assert "data-shared-shell" in html
    assert 'id="workflowCharts"' in html
    assert "/shared/static/planning.css" in html
    assert not re.search(r"https?://", html)
    assert not re.search(r"\son[a-z]+=", html, re.IGNORECASE)

    styles = (FRONTEND / "decision-intelligence.css").read_text(encoding="utf-8")
    assert ".filter-band { display: flex; flex-wrap: nowrap;" in styles


def test_frontend_uses_safe_dom_rendering() -> None:
    """Render data as text and avoid executable HTML insertion."""
    script = (FRONTEND / "decision-intelligence.js").read_text(encoding="utf-8")
    assert ".textContent =" in script
    assert "setHealthStatus('offline', 'OFFLINE')" in script
    assert ".innerHTML" not in script
    assert "eval(" not in script
