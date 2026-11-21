"""归档工作台 HTTP 入口，全部动作落在 M8 服务层。"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from app.modules.m8_archive import service


def _key(request: Request) -> bytes | None:
    secret = request.app.state.archive_hmac_key
    return secret.encode("utf-8") if secret else None


router = APIRouter(prefix="/api/archive", tags=["冷存归档"])


class HoldInput(BaseModel):
    run_id: str
    subject: str
    reason: str
    expires_at: str | None = None


class RunInput(BaseModel):
    run_id: str


@router.get("/ledger")
def ledger(request: Request):
    rows = [dict(row) for row in request.app.state.archive.list()]
    return {"batches": rows, "count": len(rows)}


@router.get("/eligibility/{run_id}")
def eligibility(run_id: str, request: Request):
    return service.eligibility(request.app.state.store, request.app.state.archive, run_id)


@router.get("/plan")
def plan(request: Request, need_bytes: Annotated[int, Query(ge=1, le=2**63 - 1)]):
    return service.plan(request.app.state.store, request.app.state.archive, need_bytes)


@router.post("/freeze", status_code=201)
def freeze(payload: RunInput, request: Request, response: Response):
    record, reused = service.freeze(request.app.state.store, request.app.state.archive,
                                    request.app.state.settings.cold_root, payload.run_id, hmac_key=_key(request))
    if reused:
        response.status_code = 200
    return {"batch": record, "reused": reused}


@router.post("/purge")
def purge(payload: RunInput, request: Request):
    record = service.purge(request.app.state.store, request.app.state.archive,
                           request.app.state.settings.cold_root, payload.run_id, hmac_key=_key(request))
    return {"batch": record}


@router.post("/restore")
def restore(payload: RunInput, request: Request, dry_run: bool = False):
    report = service.restore(request.app.state.store, request.app.state.archive,
                             request.app.state.settings.cold_root, payload.run_id,
                             hmac_key=_key(request), dry_run=dry_run)
    return {"report": report}


@router.get("/readback/{run_id}")
def readback(run_id: str, request: Request, pass_id: str | None = None):
    return service.readback(request.app.state.store, request.app.state.archive,
                            request.app.state.settings.cold_root, run_id, pass_id, hmac_key=_key(request))


@router.get("/holds")
def holds(request: Request, run_id: str | None = None, include_released: bool = False):
    return {"holds": [dict(row) for row in request.app.state.archive.holds(run_id, include_released=include_released)]}


@router.post("/holds", status_code=201)
def place_hold(payload: HoldInput, request: Request):
    hold = service.place_hold(request.app.state.archive, payload.run_id, payload.subject,
                              payload.reason, expires_at=payload.expires_at)
    return {"hold": hold}


@router.post("/holds/{hold_id}/release")
def release_hold(hold_id: str, request: Request):
    return {"hold": service.release_hold(request.app.state.archive, hold_id)}


@router.get("/events")
def events(request: Request, run_id: str | None = None,
           after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
           limit: Annotated[int, Query(ge=1, le=250)] = 100):
    rows = request.app.state.archive.events(run_id, after, limit)
    return {"events": [dict(row) for row in rows], "cursor": rows[-1]["seq"] if rows else after}


@router.get("/seal/{run_id}")
def seal(run_id: str, request: Request):
    from app.modules.m8_archive import cold

    return {"seal": cold.verify_package(request.app.state.settings.cold_root, run_id, hmac_key=_key(request))}
