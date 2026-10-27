"""Read-only HTTP API for globally configured comparison windows."""

from fastapi import APIRouter, HTTPException

from capacity_twin_core.comparison.windows import list_comparison_windows

router = APIRouter(prefix="/shared/api", tags=["comparison-windows"])


@router.get("/comparison-windows")
def comparison_windows() -> dict:
    """List available analytical windows without storing user selection."""
    try:
        windows = [window.as_dict() for window in list_comparison_windows()]
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"windows": windows, "default_window": "total"}
