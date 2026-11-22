from __future__ import annotations

import json
import os
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
from .pipeline import ProgressInfo, render
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
    frames_done: int
    total_frames: int
    total_time: float
    elapsed_time: float
    eta: float
    fps: float
    stage: str
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
    frames_done: int = 0
    total_frames: int = 0
    total_time: float = 0.0
    elapsed_time: float = 0.0
    eta: float = 0.0
    fps: float = 0.0
    stage: str = ""
    error: str | None = None
    report: str | None = None


JOBS: dict[str, JobInfo] = {}


def _storage_root() -> Path:
    env_dir = os.environ.get("VR_STORAGE_DIR")
    if env_dir:
        base = Path(env_dir)
    else:
        base = Path.home() / ".cache" / "video-restore" / "web_jobs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _save_job_state(job_id: str, job: JobInfo) -> None:
    JOBS[job_id] = job
    state_file = _storage_root() / f"job_{job_id}" / "state.json"
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "src": str(job.src),
            "out": str(job.out) if job.out else None,
            "status": job.status,
            "progress": job.progress,
            "frames_done": job.frames_done,
            "total_frames": job.total_frames,
            "total_time": job.total_time,
            "elapsed_time": job.elapsed_time,
            "eta": job.eta,
            "fps": job.fps,
            "stage": job.stage,
            "error": job.error,
            "report": job.report,
        }
        state_file.write_text(json.dumps(data))
    except Exception:
        pass


def _get_job(job_id: str) -> JobInfo | None:
    if job_id in JOBS:
        return JOBS[job_id]
    state_file = _storage_root() / f"job_{job_id}" / "state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            job = JobInfo(
                src=Path(data["src"]),
                out=Path(data["out"]) if data.get("out") else None,
                status=data.get("status", "uploaded"),
                progress=float(data.get("progress", 0.0)),
                frames_done=int(data.get("frames_done", 0)),
                total_frames=int(data.get("total_frames", 0)),
                total_time=float(data.get("total_time", 0.0)),
                elapsed_time=float(data.get("elapsed_time", 0.0)),
                eta=float(data.get("eta", 0.0)),
                fps=float(data.get("fps", 0.0)),
                stage=data.get("stage", ""),
                error=data.get("error"),
                report=data.get("report"),
            )
            JOBS[job_id] = job
            return job
        except Exception:
            return None
    return None


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent.parent / "static" / "index.html").read_text()


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    job_id = uuid.uuid4().hex[:8]
    d = _storage_root() / f"job_{job_id}"
    d.mkdir(parents=True, exist_ok=True)
    src = d / (file.filename or "in.mp4")
    with src.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    try:
        info = probe(src)
        prof = analyze(info)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to probe/analyze video: {exc}")

    out = src.with_name("restored" + src.suffix)
    total_frames = info.frame_count or max(1, int(round(info.duration * info.fps)))
    job = JobInfo(
        src=src,
        out=out,
        profile=prof,
        status="analyzed",
        total_frames=total_frames,
    )
    _save_job_state(job_id, job)

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


def _run_render_job(
    job_id: str,
    preset_name: str,
    screen_mode: bool = False,
    audio_denoise: bool | None = None,
) -> None:
    job = _get_job(job_id)
    if not job or not job.out or not job.profile:
        return
    job.status = "rendering"
    job.progress = 0.0
    job.frames_done = 0
    job.stage = "Initializing pipeline..."
    _save_job_state(job_id, job)

    def on_progress(p: ProgressInfo | float) -> None:
        if isinstance(p, ProgressInfo):
            job.progress = round(float(p), 1)
            job.frames_done = p.frames_done
            job.total_frames = p.total_frames or job.total_frames
            job.total_time = round(p.total_time, 1)
            job.elapsed_time = round(p.elapsed_time, 1)
            job.eta = round(p.eta, 1)
            job.fps = round(p.fps, 1)
            job.stage = p.stage
        else:
            job.progress = round(float(p), 1)
        _save_job_state(job_id, job)

    try:
        info = probe(job.src)
        geom = crop = None
        moire = bands = 0.0
        if screen_mode:
            from . import screen as scr
            q = scr.detect(info)
            if q is not None:
                geom = q.as_filter()
            moire = scr.moire_score(info)
            bands = scr.band_score(info)

        effective_audio = audio_denoise if audio_denoise is not None else (job.profile.hiss > 0.25)
        plan = build_plan(
            job.profile,
            preset_name,
            geometry=geom,
            crop=crop,
            moire=moire,
            bands=bands,
            audio_denoise=effective_audio,
        )
        cfg = Config(
            source=job.src,
            output=job.out,
            preset=Preset(preset_name),
            force=True,
            screen_mode=screen_mode,
            audio_denoise=effective_audio,
            work_dir=job.src.parent / "staging",
        )
        render(cfg, plan, info, progress_callback=on_progress)
        job.status = "done"
        job.progress = 100.0
        job.frames_done = job.total_frames
        job.eta = 0.0
        job.stage = "Completed"
        job.report = compare(job.src, job.out)
        _save_job_state(job_id, job)
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        _save_job_state(job_id, job)


@app.post("/render")
def do_render(
    background_tasks: BackgroundTasks,
    job: str = Form(...),
    preset: str = Form("standard"),
    screen_mode: bool = Form(False),
    audio_denoise: bool = Form(False),
) -> RenderResponse:
    if not _get_job(job):
        raise HTTPException(status_code=404, detail="Job not found")
    background_tasks.add_task(
        _run_render_job, job, preset, screen_mode=screen_mode, audio_denoise=audio_denoise
    )
    return {"status": "started", "job": job}


@app.get("/status/{job}")
def get_status(job: str) -> StatusResponse:
    j = _get_job(job)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job": job,
        "status": j.status,
        "progress": j.progress,
        "frames_done": j.frames_done,
        "total_frames": j.total_frames,
        "total_time": j.total_time,
        "elapsed_time": j.elapsed_time,
        "eta": j.eta,
        "fps": j.fps,
        "stage": j.stage,
        "error": j.error,
        "report": j.report,
    }


@app.get("/source/{job}")
def get_source(job: str) -> FileResponse:
    j = _get_job(job)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return FileResponse(j.src, media_type="video/mp4")


@app.get("/download/{job}")
def download(job: str) -> FileResponse:
    j = _get_job(job)
    if not j or not j.out or not j.out.exists():
        raise HTTPException(status_code=404, detail="Restored video not ready")
    return FileResponse(j.out, filename=j.out.name, media_type="video/mp4")
