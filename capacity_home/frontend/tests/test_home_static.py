"""Fast static checks for the compact application launcher."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]


class HomeStaticTests(unittest.TestCase):
    def test_landing_page_has_registry_owned_card_mount(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="applicationCards"', html)
        self.assertNotIn("Operations Assistant</strong>", html)
        script = (FRONTEND / "home.js").read_text(encoding="utf-8")
        self.assertIn("'/shared/api/applications'", script)
        self.assertIn("application.show_on_home", script)

    def test_page_has_no_remote_assets_or_inline_handlers(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertNotRegex(html, r"https?://")
        self.assertIsNone(re.search(r"\son[a-z]+=", html, re.IGNORECASE))

    def test_home_uses_compact_brand_and_project_heading(self):
        """Keep the CP icon as Home and show the full product name below."""
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        css = (FRONTEND / "home.css").read_text(encoding="utf-8")

        self.assertIn('data-title="Test Equipment Capacity Planning Digital Twin"', html)
        self.assertIn('data-mark="CP"', html)
        self.assertIn("data-shared-page-header", html)
        self.assertIn("width: min(1440px, calc(100% - 28px))", css)
        self.assertIn("width: min(70%, 651px)", css)
        self.assertIn("margin-bottom: 16px", css)

    def test_status_checks_cover_all_application_apis(self):
        script = (FRONTEND / "home.js").read_text(encoding="utf-8")
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertIn("application.health_route", script)
        for label in ("CHECKING", "READY", "degraded", "OFFLINE"):
            self.assertIn(label, script)
        self.assertIn('id="refresh-status"', html)


if __name__ == "__main__":
    unittest.main()
