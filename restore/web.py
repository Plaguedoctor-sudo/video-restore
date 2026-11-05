from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .analyze import DefectProfile, analyze
from .config import Config, Preset
from .pipeline import render
from .plan import build_plan
from .probe import probe
from .report import compare


class VideoMeta(TypedDict):
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


class UploadResponse(TypedDict):
    job: str
    profile: dict[str, float]
    summary: str
    info: VideoMeta


class RenderResponse(TypedDict):
    status: str
    job: str


class StatusResponse(TypedDict):
    job: str
    status: str
    progress: float
    error: str | None
    report: str | None


app = FastAPI(title="video-restore")


@dataclass
class JobInfo:
    src: Path
    out: Path | None = None
    profile: DefectProfile | None = None
    status: str = "uploaded"  # uploaded, rendering, done, failed
    progress: float = 0.0
    error: str | None = None
    report: str | None = None


JOBS: dict[str, JobInfo] = {}


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent.parent / "static" / "index.html").read_text()


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    job_id = uuid.uuid4().hex[:8]
    d = Path(tempfile.mkdtemp(prefix="vr_"))
    src = d / (file.filename or "in.mp4")
    with src.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    try:
        info = probe(src)
        prof = analyze(info)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to probe/analyze video: {exc}")

    out = src.with_name("restored" + src.suffix)
    JOBS[job_id] = JobInfo(src=src, out=out, profile=prof, status="analyzed")

    return {
        "job": job_id,
        "profile": prof.as_dict(),
        "summary": prof.summary(),
        "info": {
            "width": info.width,
            "height": info.height,
            "fps": round(info.fps, 2),
            "duration": round(info.duration, 2),
            "has_audio": info.has_audio,
        },
    }


def _run_render_job(job_id: str, preset_name: str) -> None:
    job = JOBS.get(job_id)
    if not job or not job.out or not job.profile:
        return
    job.status = "rendering"
    job.progress = 0.0

    def on_progress(pct: float) -> None:
        job.progress = round(pct, 1)

    try:
        info = probe(job.src)
        plan = build_plan(job.profile, preset_name)
        cfg = Config(source=job.src, output=job.out, preset=Preset(preset_name), force=True)
        render(cfg, plan, info, progress_callback=on_progress)
        job.status = "done"
        job.progress = 100.0
        job.report = compare(job.src, job.out)
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)


@app.post("/render")
def do_render(
    background_tasks: BackgroundTasks,
    job: str = Form(...),
    preset: str = Form("standard"),
) -> RenderResponse:
    if job not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    background_tasks.add_task(_run_render_job, job, preset)
    return {"status": "started", "job": job}


@app.get("/status/{job}")
def get_status(job: str) -> StatusResponse:
    if job not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    j = JOBS[job]
    return {
        "job": job,
        "status": j.status,
        "progress": j.progress,
        "error": j.error,
        "report": j.report,
    }


@app.get("/source/{job}")
def get_source(job: str) -> FileResponse:
    if job not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return FileResponse(JOBS[job].src, media_type="video/mp4")


@app.get("/download/{job}")
def download(job: str) -> FileResponse:
    if job not in JOBS or not JOBS[job].out or not JOBS[job].out.exists():
        raise HTTPException(status_code=404, detail="Restored video not ready")
    return FileResponse(JOBS[job].out, filename=JOBS[job].out.name, media_type="video/mp4")
