"""Static regression checks for safe Capacity Assistant model-output rendering."""

from pathlib import Path


def test_model_output_is_escaped_before_markdown_rendering():
    script = (
        Path(__file__).resolve().parents[2] / "frontend" / "capacity-assistant.js"
    ).read_text(encoding="utf-8")
    formatter = script.split(
        "function renderSafeMarkdown(container, source)", 1
    )[1].split(
        "function startAssistantMessage", 1
    )[0]
    assert "innerHTML" not in formatter
    assert "createTextNode" in formatter
