"""Admin endpoints — maintenance trigger + status."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse


router = APIRouter()


@router.get("/admin/maintain", name="maintain_status")
def maintain_status(request: Request) -> JSONResponse:
    scheduler = getattr(request.app.state, "maintenance", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="maintenance scheduler is not configured")
    return JSONResponse(scheduler.status())


@router.post("/admin/maintain", name="maintain_run")
async def maintain_run(request: Request):
    scheduler = getattr(request.app.state, "maintenance", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="maintenance scheduler is not configured")
    if scheduler.state.running:
        # Already running — return current status; don't queue another.
        return JSONResponse(scheduler.status(), status_code=202)

    result = await scheduler.run_once(triggered_by="manual")

    # If the request came from a browser form (Accept: text/html), redirect
    # back to the dashboard so the user lands on a refreshed page. Otherwise
    # return JSON for curl / scripts.
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept and "application/json" not in accept:
        return RedirectResponse(url="/", status_code=303)

    status_code = 200 if result["status"] == "ok" else 500
    return JSONResponse(result, status_code=status_code)
