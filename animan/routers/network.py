"""Local browser verification and safe transport diagnostics."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from animan.services.browser_verification import browser_verification
from animan.services.download_manager import download_manager

router = APIRouter(prefix="/api/network")


class StartVerification(BaseModel):
    domain: str = Field(pattern=r"^[A-Za-z0-9.-]+$", max_length=253)
    browser: str | None = None
    mode: str = "browser"


def local_only(request):
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "La vérification dans le navigateur doit être ouverte depuis cette machine")


@router.get("/sessions")
async def sessions(request: Request):
    await browser_verification.expire()
    return browser_verification.options()


@router.post("/verification")
async def start(body: StartVerification, request: Request):
    local_only(request)
    try:
        return await browser_verification.start(body.domain, body.browser, body.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/verification/{job_id}/complete")
async def complete(job_id: str, request: Request):
    local_only(request)
    try:
        result = await browser_verification.complete(job_id)
        result["resumed"] = download_manager.resume_verified_domain(result["domain"])
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/verification/{job_id}")
async def cancel(job_id: str, request: Request):
    local_only(request)
    await browser_verification.cancel(job_id)
    return {"success": True}
