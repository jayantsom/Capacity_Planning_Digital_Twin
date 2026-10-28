"""Static regression checks for safe shared Yukti output rendering."""

from pathlib import Path


def test_model_output_uses_text_only_rendering():
    script = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "capacity_twin_core"
        / "frontend"
        / "yukti.js"
    ).read_text(encoding="utf-8")
    assert ".textContent" in script
    assert "innerHTML" not in script
    assert "eval(" not in script
    assert "/shared/api/yukti/chat/stream" in script
    assert "pageContext(application)" in script
