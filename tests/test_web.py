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
