"""Static, accessibility, and governed chart adoption checks."""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
CORE_CHART = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "capacity_twin_core"
    / "frontend"
    / "chart.js"
)


def test_page_uses_shared_shell_and_governed_chart_wrapper() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "capacity-analysis.js").read_text(encoding="utf-8")
    assert "data-shared-shell" in html
    assert "/shared/static/shell.css" in html
    assert "/shared/static/shell.js" in html
    assert "renderGovernedChart" in script
    assert "echarts.init" not in script
    assert "http://" not in html and "https://" not in html


def test_two_tabs_and_required_sections_are_accessible() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    for token in (
        'role="tablist"',
        'role="tab"',
        'role="tabpanel"',
        'aria-selected="true"',
        "Tactical Capacity",
        "Bottleneck Analysis",
        "Demand and supply trend",
        "Capacity-loss waterfall",
        "Site-test gap heatmap",
        "Constrained-resource ranking",
        "Equipment requirement",
        "Governed alternative resources",
        "Resource-hour constraints",
        "Bottleneck movement over time",
        "Investment need",
    ):
        assert token in html


def test_visible_capacity_terms_do_not_call_output_capacity() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "capacity-analysis.js").read_text(encoding="utf-8")
    assert "Actual Output" in html + script
    assert "Demonstrated Capacity" in html + script
    assert "Actual Capacity" not in html + script
    assert "actual capacity" not in (html + script).lower()


def test_filter_and_keyboard_contracts_are_present() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "capacity-analysis.js").read_text(encoding="utf-8")
    for name in (
        "site",
        "product",
        "test_type",
        "capacity_mode",
        "retest",
        "planning_version",
        "month_from",
        "month_to",
    ):
        assert f'name="{name}"' in html
    for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
        assert key in script
    assert "format: number" not in script


def test_chart_contract_supports_heatmap_and_accessible_rows() -> None:
    wrapper = CORE_CHART.read_text(encoding="utf-8")
    for token in (
        "visualMap",
        "accessibility.rows",
        "accessibility.columns",
        "spec.axes.y.values",
        "dataZoom",
        "exportCsv",
    ):
        assert token in wrapper
    assert "top: 52" in wrapper
    assert "top: spec.legend.show !== false ? 104 : 78" in wrapper
    assert "text: spec.metric" in wrapper
    assert "left: 'center'" in wrapper
    assert "fontSize: 13" in wrapper
    assert "every series requires a name" in wrapper
    assert "series names must be unique" in wrapper


def test_capacity_summary_values_use_compact_type() -> None:
    stylesheet = (FRONTEND / "capacity-analysis.css").read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(auto-fit, minmax(130px, 1fr))" in stylesheet
    assert "min-height: 66px" in stylesheet
    assert "font: 700 clamp(13px, 1.2vw, 18px) var(--ct-mono)" in stylesheet
    assert ".ct-kpi-value" in stylesheet
    assert "display: flex" in stylesheet
    assert "white-space: nowrap" in stylesheet
    assert "font-size: 10px" in stylesheet
