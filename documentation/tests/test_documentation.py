"""Documentation catalog, API, and safe frontend contracts."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from documentation.backend.main import PROJECT_ROOT, _catalog, router

documentation_app = FastAPI()
documentation_app.include_router(router)
client = TestClient(documentation_app)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_catalog_has_one_owner_per_slug_and_path() -> None:
    groups, pages = _catalog()
    listed = [page for group in groups for page in group["pages"]]
    assert len(listed) == len(pages)
    assert len({page["path"] for page in listed}) == len(listed)
    assert all((PROJECT_ROOT / page["path"]).is_file() for page in listed)


def test_page_api_reads_the_markdown_source() -> None:
    response = client.get("/documentation/api/pages/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["markdown"] == (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def test_frontend_uses_safe_dom_rendering() -> None:
    script = (FRONTEND / "documentation.js").read_text(encoding="utf-8")
    assert ".textContent" in script
    assert "innerHTML" not in script
    assert "eval(" not in script
    assert "normalizedHeading(heading[2]) === normalizedHeading(pageTitle)" in script
    assert "renderMarkdown(payload.markdown, payload.title)" in script


def test_owned_docs_use_ml_casing_and_no_em_dash() -> None:
    _, pages = _catalog()
    for item in pages.values():
        text = (PROJECT_ROOT / item["path"]).read_text(encoding="utf-8")
        assert "\u2014" not in text, item["path"]
        assert "Ml " not in text, item["path"]
