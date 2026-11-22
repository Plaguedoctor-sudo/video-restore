from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient

from restore.analyze import DefectProfile
from restore.probe import MediaInfo
from restore.web import JOBS, JobInfo, app

client = TestClient(app)


def test_index_page():
    res = client.get("/")
    assert res.status_code == 200
    assert "video-restore" in res.text


def test_upload_and_status():
    dummy_info = MediaInfo(
        path=Path("dummy.mp4"),
        width=640,
        height=360,
        fps=30.0,
        duration=5.0,
        video_codec="h264",
        has_audio=False,
    )
    dummy_prof = DefectProfile(0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 0.0, 0.4)

    with patch("restore.web.probe", return_value=dummy_info), \
         patch("restore.web.analyze", return_value=dummy_prof):
        files = {"file": ("test.mp4", b"fake video bytes", "video/mp4")}
        res = client.post("/upload", files=files)
        assert res.status_code == 200
        data = res.json()
        assert "job" in data
        job_id = data["job"]

        status_res = client.get(f"/status/{job_id}")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "analyzed"


def test_render_and_download_flow():
    job_id = "testjob1"
    src = Path("/tmp/dummy_src.mp4")
    out = Path("/tmp/dummy_restored.mp4")
    src.write_bytes(b"dummy source")
    out.write_bytes(b"dummy restored")

    try:
        dummy_prof = DefectProfile(0, 0, 0, 0, 0, 0, 0, 0)
        JOBS[job_id] = JobInfo(src=src, out=out, profile=dummy_prof, status="done", progress=100.0)

        # Download restored
        dl_res = client.get(f"/download/{job_id}")
        assert dl_res.status_code == 200
        assert dl_res.content == b"dummy restored"

        # Download source
        src_res = client.get(f"/source/{job_id}")
        assert src_res.status_code == 200
        assert src_res.content == b"dummy source"
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        JOBS.pop(job_id, None)


def test_status_includes_frames_and_time():
    job_id = "testjob_progress"
    src = Path("/tmp/dummy_progress_src.mp4")
    out = Path("/tmp/dummy_progress_out.mp4")
    src.write_bytes(b"dummy source")
    try:
        prof = DefectProfile(0, 0, 0, 0, 0, 0, 0, 0)
        job = JobInfo(
            src=src,
            out=out,
            profile=prof,
            status="rendering",
            progress=45.5,
            frames_done=455,
            total_frames=1000,
            total_time=120.0,
            elapsed_time=54.6,
            eta=65.4,
            fps=8.3,
            stage="Restoration & encoding (Pass 2/2)",
        )
        JOBS[job_id] = job

        status_res = client.get(f"/status/{job_id}")
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["job"] == job_id
        assert data["status"] == "rendering"
        assert data["progress"] == 45.5
        assert data["frames_done"] == 455
        assert data["total_frames"] == 1000
        assert data["total_time"] == 120.0
        assert data["elapsed_time"] == 54.6
        assert data["eta"] == 65.4
        assert data["fps"] == 8.3
        assert "Pass 2/2" in data["stage"]
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        JOBS.pop(job_id, None)


def test_job_persistence_across_process_simulation():
    from restore.pipeline import ProgressInfo
    from restore.web import _save_job_state, _get_job

    job_id = "testjob_persist"
    src = Path("/tmp/dummy_persist_src.mp4")
    out = Path("/tmp/dummy_persist_out.mp4")
    src.write_bytes(b"dummy")
    try:
        prof = DefectProfile(0, 0, 0, 0, 0, 0, 0, 0)
        job = JobInfo(
            src=src,
            out=out,
            profile=prof,
            status="rendering",
            progress=60.0,
            frames_done=300,
            total_frames=500,
            total_time=50.0,
            elapsed_time=30.0,
            eta=20.0,
            fps=10.0,
            stage="Restoration & encoding",
        )
        _save_job_state(job_id, job)

        # Simulate another forked worker where in-memory JOBS is empty
        JOBS.pop(job_id, None)

        loaded = _get_job(job_id)
        assert loaded is not None
        assert loaded.frames_done == 300
        assert loaded.total_frames == 500
        assert loaded.total_time == 50.0
        assert loaded.eta == 20.0

        status_res = client.get(f"/status/{job_id}")
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["frames_done"] == 300
        assert data["total_frames"] == 500
        assert data["total_time"] == 50.0
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        JOBS.pop(job_id, None)


def test_progress_info_compatibility():
    from restore.pipeline import ProgressInfo, _call_progress

    p = ProgressInfo(
        pct=50.0,
        frames_done=150,
        total_frames=300,
        fps=15.0,
        elapsed_time=10.0,
        total_time=20.0,
        eta=10.0,
        stage="Analyzing",
    )
    # Check float compatibility
    assert float(p) == 50.0
    assert p + 5.0 == 55.0
    assert p.frames_done == 150
    assert p.total_frames == 300
    assert p.total_time == 20.0
    assert p.eta == 10.0

    # Test callback accepting float vs ProgressInfo
    received_float = []
    def legacy_cb(val: float):
        received_float.append(val)

    _call_progress(legacy_cb, p)
    assert len(received_float) == 1
    assert received_float[0] == 50.0

