"""Fast static checks for the Data Explorer frontend."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]


class ExplorerStaticTests(unittest.TestCase):
    def test_page_is_offline_safe_and_has_no_inline_handlers(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertNotRegex(html, r"https?://")
        self.assertIsNone(re.search(r"\son[a-z]+=", html, re.IGNORECASE))
        self.assertNotIn("Chart.js", html)

    def test_api_rows_are_rendered_with_dom_construction(self):
        script = (FRONTEND / "explorer-modern.js").read_text(encoding="utf-8")

        self.assertNotIn("innerHTML", script)
        self.assertIn("textContent", script)
        self.assertIn("createDocumentFragment", script)
        self.assertIn("layer === 'ml' ? 'ML'", script)

    def test_dense_workspace_states_are_present(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        for required_id in ("kpiStrip", "activeFilters", "tableState", "pagination", "sqlPanel"):
            self.assertIn(f'id="{required_id}"', html)
        self.assertIn("data-shared-page-header", html)
        self.assertIn('data-title="Data Explorer"', html)
        self.assertIn('data-title-id="pageTitle"', html)
        self.assertIn("<span>CHECKING</span>", html)
        self.assertLess(html.index("data-shared-page-header"), html.index('class="explorer-body"'))
        self.assertIn('class="filter-controls-row"', html)
        self.assertIn('class="sidebar closed"', html)
        self.assertIn('id="sourceToggle"', html)
        self.assertIn('aria-label="Expand data catalog"', html)
        self.assertNotIn('id="breadcrumbLayer"', html)
        page_heading = html.split("<section data-shared-page-header", 1)[1].split(
            "</section>", 1
        )[0]
        self.assertIn('id="sourceStatus"', page_heading)
        self.assertNotIn('id="sourceToggle"', page_heading)
        self.assertNotIn('id="filterToggle"', page_heading)
        workspace_header = html.split('<section class="workspace-header"', 1)[1].split(
            "</section>", 1
        )[0]
        self.assertIn('id="filterToggle"', workspace_header)
        self.assertIn('aria-expanded="false">Filters</button>', workspace_header)
        self.assertIn('class="filter-panel closed"', html)
        self.assertNotIn("QUERY CONTROLS", html)
        self.assertNotIn('id="filterClose"', html)

    def test_catalog_and_horizontal_filters_are_collapsible(self):
        """Keep both dense controls available in compact collapsible panels."""
        script = (FRONTEND / "explorer-modern.js").read_text(encoding="utf-8")

        self.assertIn("function toggleSourcePanel()", script)
        self.assertIn("function updateSourceToggle(expanded)", script)
        self.assertIn("function toggleFilterPanel()", script)
        self.assertIn(".slice(0, 6)", script)
        for label in ("READY", "NO SOURCES", "OFFLINE"):
            self.assertIn(f"'{label}'", script)

    def test_summary_band_matches_decision_intelligence_format(self):
        css = (FRONTEND / "explorer-modern.css").read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(130px, 1fr))", css)
        self.assertIn("min-height: 66px", css)
        self.assertIn("font: 700 18px var(--mono)", css)


if __name__ == "__main__":
    unittest.main()
