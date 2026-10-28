"""Phase 4A shared application and dashboard foundation contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

import capacity_twin_core
from capacity_home.main import COMPOSED_ROUTE_KEYS, COMPOSED_ROUTE_PATHS, app
from capacity_twin_core.analytics import FilterContract, TimeGrain
from capacity_twin_core.applications import APPLICATIONS, validate_registry

client = TestClient(app)
CORE_FRONTEND = Path(capacity_twin_core.__file__).resolve().parent / "frontend"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_registry_and_composed_routes_are_unique() -> None:
    """Reject duplicate public application and FastAPI paths."""
    validate_registry()
    route_paths = list(COMPOSED_ROUTE_PATHS)
    assert len(route_paths) == len(set(route_paths))
    assert len(COMPOSED_ROUTE_KEYS) == len(set(COMPOSED_ROUTE_KEYS))
    for application in APPLICATIONS:
        if application.enabled:
            assert application.route in route_paths


def test_shared_static_and_api_namespaces_do_not_overlap() -> None:
    """Keep executable services out of the shared asset namespace."""
    paths = set(COMPOSED_ROUTE_PATHS)
    assert "/shared/static" in paths
    assert "/shared/api/applications" in paths
    assert "/shared/api/health" in paths
    assert all(
        not path.startswith("/shared/static/") or "/api/" not in path
        for path in paths
    )
    assert client.get("/shared/static/dashboard.js").status_code == 200
    assert client.get("/shared/api/applications").headers["content-type"].startswith(
        "application/json"
    )


def test_every_current_page_loads_the_shared_shell() -> None:
    """Ensure current pages do not own another copy of primary navigation."""
    for route in (
        "/",
        "/explorer/",
        "/capacity-analysis/",
        "/decision-intelligence/",
        "/scenario-planning/",
        "/demand-supply-planning/",
        "/npi-ramp-planning/",
        "/operations-flow/",
        "/data-operations/",
    ):
        html = client.get(route).text
        assert 'data-shared-shell' in html
        assert '/shared/static/shell.css' in html
        assert '/shared/static/shell.js' in html
        assert "product-nav" not in html


def test_planning_menu_declares_keyboard_menu_semantics() -> None:
    """Keep the shared Planning menu operable without a pointer."""
    script = (CORE_FRONTEND / "shell.js").read_text(encoding="utf-8")
    for token in (
        "aria-haspopup",
        "aria-expanded",
        'role="menuitem"',
        "ArrowDown",
        "ArrowUp",
        "Escape",
        "Home",
        "End",
    ):
        assert token in script


def test_chart_contract_covers_governance_and_accessibility() -> None:
    """Keep the governed wrapper complete before applications adopt it."""
    script = (CORE_FRONTEND / "chart.js").read_text(encoding="utf-8")
    for field in (
        "title",
        "metric",
        "unit",
        "grain",
        "aggregation",
        "source",
        "axes",
        "legend",
        "tooltip",
        "thresholds",
        "dataZoom",
        "accessibility",
        "pointLimit",
        "ResizeObserver",
        "prefers-reduced-motion",
        "escapeCsvCell",
        "imageMetadata",
    ):
        assert field in script
    assert "/shared/static/vendor/echarts/echarts.min.js" in script
    assert "http://" not in script and "https://" not in script


def test_server_filter_contract_rejects_unsupported_values() -> None:
    """Require datasets to opt in to filters and time grains."""
    contract = FilterContract(
        "monthly-plan",
        frozenset({"site", "grain"}),
        (TimeGrain.MONTH,),
    )
    assert contract.validate({"site": "SITE-01", "grain": "MONTH"})["site"] == "SITE-01"
    try:
        contract.validate({"machine": "M-01"})
    except ValueError as error:
        assert "machine" in str(error)
    else:
        raise AssertionError("Unsupported filter was accepted")
    try:
        contract.validate({"grain": "WEEK"})
    except ValueError as error:
        assert "WEEK" in str(error)
    else:
        raise AssertionError("Unsupported grain was accepted")


def test_pinned_echarts_asset_matches_metadata() -> None:
    """Detect accidental library replacement or CDN fallback."""
    metadata = json.loads(
        (CORE_FRONTEND / "vendor" / "echarts" / "asset-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    asset = CORE_FRONTEND / "vendor" / "echarts" / metadata["asset"]
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    assert metadata["version"] == "5.6.0"
    assert metadata["license"] == "Apache-2.0"
    assert metadata["runtime_network_required"] is False
    assert digest == metadata["sha256"]
    assert (asset.parent / metadata["license_file"]).is_file()
    assert client.get(metadata["served_path"]).status_code == 200
