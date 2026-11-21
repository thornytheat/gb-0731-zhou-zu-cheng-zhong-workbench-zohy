from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import ROOT, RULE_VERSION
from app.sources import SAMPLES

router = APIRouter()
templates = Jinja2Templates(directory=ROOT / "app/templates")

MODULES = (
    ("intake", "采样验收"), ("calibration", "传感器标定"), ("debounce", "脉冲去抖"),
    ("axles", "轴组重建"), ("balance", "偏载判级"), ("reconcile", "整车磅单勾稽"), ("batches", "称重批次"),
)


@router.get("/", response_class=HTMLResponse)
def workbench(request: Request):
    return templates.TemplateResponse(request, "workbench.html", {
        "samples": SAMPLES, "modules": MODULES, "version": RULE_VERSION,
    })


@router.get("/api/health", tags=["服务"])
def health():
    return {"status": "ready", "rules": RULE_VERSION}
