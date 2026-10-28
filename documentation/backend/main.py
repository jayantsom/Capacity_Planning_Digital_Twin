"""Read-only API for repository-owned Markdown documentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from capacity_twin_core.runtime.database_paths import PROJECT_ROOT, load_app_config

APP_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = APP_ROOT / "frontend"
CONFIG = load_app_config("documentation")
router = APIRouter()


def _catalog() -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    groups = CONFIG.get("groups", [])
    pages: dict[str, dict[str, str]] = {}
    paths: set[str] = set()
    safe_groups: list[dict[str, Any]] = []
    for group in groups:
        safe_pages = []
        for item in group.get("pages", []):
            slug = str(item["slug"])
            relative = str(item["path"]).replace("\\", "/")
            path = (PROJECT_ROOT / relative).resolve()
            if PROJECT_ROOT.resolve() not in path.parents or not path.is_file():
                raise ValueError(f"Documentation page is missing or unsafe: {relative}")
            if slug in pages:
                raise ValueError(f"Duplicate documentation slug: {slug}")
            if relative in paths:
                raise ValueError(f"Duplicate documentation owner: {relative}")
            pages[slug] = {
                "slug": slug,
                "title": str(item["title"]),
                "path": relative,
            }
            paths.add(relative)
            safe_pages.append(pages[slug])
        safe_groups.append({"title": str(group["title"]), "pages": safe_pages})
    return safe_groups, pages


@router.get("/documentation/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the documentation workspace."""
    return FileResponse(FRONTEND_ROOT / "index.html")


@router.get("/documentation/api/health")
async def health() -> dict[str, Any]:
    """Validate catalog ownership and every tracked Markdown file."""
    try:
        groups, pages = _catalog()
        for item in pages.values():
            text = (PROJECT_ROOT / item["path"]).read_text(encoding="utf-8")
            if "\u2014" in text:
                raise ValueError(f"Em dash found in {item['path']}")
        return {
            "status": "ready",
            "group_count": len(groups),
            "page_count": len(pages),
        }
    except (OSError, KeyError, TypeError, ValueError) as error:
        return {"status": "degraded", "reason": str(error)}


@router.get("/documentation/api/catalog")
async def catalog() -> dict[str, Any]:
    """Return the single-owner navigation tree."""
    try:
        groups, pages = _catalog()
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return {"groups": groups, "page_count": len(pages)}


@router.get("/documentation/api/pages/{slug}")
async def page(slug: str) -> dict[str, str]:
    """Return the current Markdown file without creating a second content copy."""
    try:
        _, pages = _catalog()
        item = pages[slug]
        markdown = (PROJECT_ROOT / item["path"]).read_text(encoding="utf-8")
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Documentation page not found") from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="Documentation page is unavailable") from error
    return {**item, "markdown": markdown}


app = router
