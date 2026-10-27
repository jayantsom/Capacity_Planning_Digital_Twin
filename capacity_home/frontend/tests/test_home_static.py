"""Fast static checks for the compact application launcher."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]


class HomeStaticTests(unittest.TestCase):
    def test_landing_page_has_four_cards_in_the_approved_order(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertEqual(html.count("data-app="), 4)
        labels = [
            "Data Explorer",
            "Decision Intelligence",
            "Operations Assistant",
            "Data Operations",
        ]
        positions = [html.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_page_has_no_remote_assets_or_inline_handlers(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertNotRegex(html, r"https?://")
        self.assertIsNone(re.search(r"\son[a-z]+=", html, re.IGNORECASE))

    def test_home_uses_compact_brand_and_project_heading(self):
        """Keep the CP icon as Home and show the full product name below."""
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertIn(">Test Equipment Capacity Planning Digital Twin</h1>", html)
        self.assertIn('class="page-heading-mark" aria-hidden="true">CP</span>', html)
        self.assertIn('aria-current="page" href="/">Home</a>', html)

    def test_status_checks_cover_all_application_apis(self):
        script = (FRONTEND / "home.js").read_text(encoding="utf-8")
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertIn("'/operations-assistant/api/health'", script)
        self.assertIn("'/explorer/api/sources'", script)
        self.assertIn("'/decision-intelligence/api/health'", script)
        self.assertIn("'/data-operations/api/health'", script)
        for label in ("CHECKING", "READY", "DEGRADED", "STALE", "NO SOURCES", "OFFLINE"):
            self.assertIn(f"'{label}'", script)
        self.assertIn('id="generator-home-status"', html)
        self.assertIn('id="pipeline-home-status"', html)
        self.assertIn('id="operations-assistant-status"', html)
        self.assertIn('id="operations-assistant-detail"', html)
        self.assertIn("health.generator?.status", script)
        self.assertIn("health.pipeline?.status", script)


if __name__ == "__main__":
    unittest.main()
