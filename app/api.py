from fastapi import APIRouter, Request

from app.modules.m7_batches.pipeline import run_pipeline
from app.sources import read_sources

router = APIRouter(prefix="/api")


def view(request, stage, sample, run_id):
    if run_id is not None:
        manifest, results = request.app.state.store.read(run_id)
        return {"run_id": run_id, "sample": manifest["sample"], "data": results[stage]}
    roles = None if stage == "reconcile" else {"triggers", "certificates", "passes"}
    if stage == "intake":
        roles = {"triggers"}
    sources = read_sources(request.app.state.settings.source_dir, sample, roles)
    results = run_pipeline(sources, until=stage)
    return {"run_id": None, "sample": sample, "data": results[stage]}


@router.get("/intake", tags=["采样验收"])
def intake(request: Request, sample: str = "dirty", run_id: str | None = None):
    return view(request, "intake", sample, run_id)


@router.get("/calibration", tags=["传感器标定"])
def calibration(request: Request, sample: str = "dirty", run_id: str | None = None):
    return view(request, "calibration", sample, run_id)


@router.get("/debounce", tags=["脉冲去抖"])
def debounce(request: Request, sample: str = "dirty", run_id: str | None = None):
    return view(request, "debounce", sample, run_id)


@router.get("/axles", tags=["轴组重建"])
def axles(request: Request, sample: str = "dirty", run_id: str | None = None):
    return view(request, "axles", sample, run_id)


@router.get("/balance", tags=["偏载判级"])
def balance(request: Request, sample: str = "dirty", run_id: str | None = None):
    return view(request, "balance", sample, run_id)


@router.get("/reconcile", tags=["整车磅单勾稽"])
def reconcile(request: Request, sample: str = "dirty", run_id: str | None = None):
    return view(request, "reconcile", sample, run_id)


@router.get("/workbench", tags=["工作台"])
def dashboard(request: Request, sample: str = "dirty", run_id: str | None = None):
    if run_id is not None:
        manifest, results = request.app.state.store.read(run_id)
        return {"manifest": manifest, "data": results}
    sources = read_sources(request.app.state.settings.source_dir, sample)
    return {"manifest": None, "data": run_pipeline(sources)}
