"""Fast static checks for the Capacity Assistant frontend."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]


class CapacityAssistantStaticTests(unittest.TestCase):
    def test_page_uses_local_assets_and_named_events(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertNotRegex(html, r"https?://")
        self.assertIsNone(re.search(r"\son[a-z]+=", html, re.IGNORECASE))
        self.assertIn("<h1>Yukti - AI Capacity Assistant</h1>", html)
        self.assertIn("Ask Yukti - the AI Capacity Assistant", html)
        self.assertIn('<span id="statusText">CHECKING</span>', html)
        header = html.split('<header class="product-header">', 1)[1].split("</header>", 1)[0]
        self.assertNotIn('id="serviceStatus"', header)
        self.assertNotIn('id="inspectorToggle"', header)
        page_heading = html.split('<div class="conversation-head">', 1)[1].split(
            "</div>\n\n      <section", 1
        )[0]
        self.assertNotIn('id="inspectorToggle"', page_heading)
        self.assertNotIn('id="clearChat"', page_heading)
        composer = html.split('<form class="composer"', 1)[1].split("</form>", 1)[0]
        self.assertIn('id="clearChat" type="button">New chat</button>', composer)
        self.assertIn('class="title-actions"', html)
        self.assertIn('class="page-disclaimer"', html)

    def test_api_content_is_built_with_dom_nodes(self):
        script = (FRONTEND / "capacity-assistant.js").read_text(encoding="utf-8")

        self.assertNotIn("innerHTML", script)
        self.assertIn("textContent", script)
        self.assertIn("renderSafeMarkdown", script)
        self.assertIn("Yukti is thinking", script)
        for label in ("READY", "DEGRADED", "OFFLINE"):
            self.assertIn(f"'{label}'", script)

    def test_accessible_landmarks_and_controls_are_present(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertIn('class="skip-link"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('aria-controls="inspector"', html)
        self.assertIn('class="inspector"', html)
        self.assertNotIn('id="inspectorClose"', html)
        self.assertIn('class="page-heading-mark" aria-hidden="true">Y</span>', html)
        self.assertIn('<span class="brand-mark" aria-hidden="true">CP</span>', html)
        self.assertIn('href="/">Home</a>', html)

    def test_suggestions_use_a_compact_expandable_grid(self):
        """Keep five prompts in two rows while leaving most space for chat."""
        stylesheet = (FRONTEND / "capacity-assistant.css").read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: repeat(3", stylesheet)
        self.assertIn("flex: 1 1 70%", stylesheet)
        self.assertIn(".inspector { order: -1; width: 42px", stylesheet)


if __name__ == "__main__":
    unittest.main()
