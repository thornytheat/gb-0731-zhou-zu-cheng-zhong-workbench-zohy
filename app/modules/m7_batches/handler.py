from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from app.modules.m7_batches.export import export_bundle
from app.modules.m7_batches.service import commit_sample, replay_sample

router = APIRouter(prefix="/api/batches", tags=["称重批次"])


class RunInput(BaseModel):
    sample: str = "dirty"


@router.get("")
def list_batches(request: Request):
    return {"batches": request.app.state.store.history()}


@router.get("/events")
def logs(request: Request, after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
         limit: Annotated[int, Query(ge=1, le=250)] = 100):
    rows = request.app.state.store.events(after, limit)
    return {"events": rows, "cursor": rows[-1]["seq"] if rows else after}


@router.post("", status_code=201)
def create_batch(payload: RunInput, request: Request, response: Response):
    manifest, reused = commit_sample(request.app.state.store, request.app.state.settings.source_dir, payload.sample)
    if reused:
        response.status_code = 200
    return {"manifest": manifest, "reused": reused}


@router.get("/{run_id}")
def show_batch(run_id: str, request: Request):
    manifest, _ = request.app.state.store.read(run_id)
    return {"manifest": manifest}


@router.post("/{run_id}/rerun")
def rerun_batch(run_id: str, request: Request):
    manifest = replay_sample(request.app.state.store, request.app.state.settings.source_dir, run_id)
    return {"manifest": manifest, "reused": True, "replayed": True}


@router.get("/{run_id}/export")
def download(run_id: str, request: Request):
    manifest, results = request.app.state.store.read(run_id)
    return Response(
        content=export_bundle(manifest, results),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="axle-{run_id[:12]}.zip"'},
    )
