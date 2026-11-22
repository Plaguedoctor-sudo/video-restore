from pathlib import Path
from unittest.mock import patch

from restore.config import Config, Encoder, Preset
from restore.plan import Plan
from restore.probe import MediaInfo
from restore.pipeline import (
    JobManifest,
    _audio_args,
    _base,
    _encoder_args,
    compute_metric,
    concat_chunks,
    split_chunks,
)


def test_base_command_construction():
    cfg = Config(
        source=Path("in.mp4"),
        output=Path("out.mp4"),
        threads=4,
        sample_start=2.5,
        sample_duration=5.0,
    )
    cmd = _base(cfg)
    assert "-ss" in cmd and "2.5" in cmd
    assert "-t" in cmd and "5.0" in cmd
    assert "-threads" in cmd and "4" in cmd
    assert str(cfg.source) in cmd


def test_encoder_args_qsv_fallback():
    cfg = Config(source=Path("in.mp4"), output=Path("out.mp4"), encoder=Encoder.QSV)
    # When QSV is not supported on platform, it should fall back to libx265
    with patch("restore.pipeline.has_qsv", return_value=False):
        args = _encoder_args(cfg)
        assert "-c:v" in args
        assert "libx265" in args

    # When QSV is supported
    with patch("restore.pipeline.has_qsv", return_value=True):
        args = _encoder_args(cfg)
        assert "-c:v" in args
        assert "hevc_qsv" in args


def test_encoder_args_x264():
    cfg = Config(source=Path("in.mp4"), output=Path("out.mp4"), encoder=Encoder.X264, preset=Preset.FAST)
    args = _encoder_args(cfg)
    assert "-c:v" in args
    assert "libx264" in args
    assert "veryfast" in args


def test_audio_args_handling():
    cfg = Config(source=Path("in.mp4"), output=Path("out.mp4"), audio_denoise=False)
    cfg_denoise = Config(source=Path("in.mp4"), output=Path("out.mp4"), audio_denoise=True)

    info_no_audio = MediaInfo(
        path=Path("in.mp4"),
        width=1280,
        height=720,
        fps=30.0,
        duration=10.0,
        video_codec="h264",
        has_audio=False,
    )
    assert _audio_args(cfg, info_no_audio) == []

    info_with_audio = MediaInfo(
        path=Path("in.mp4"),
        width=1280,
        height=720,
        fps=30.0,
        duration=10.0,
        video_codec="h264",
        has_audio=True,
    )
    # Copy audio when no denoise is needed
    assert _audio_args(cfg, info_with_audio) == ["-c:a", "copy"]

    # Apply afftdn when audio denoise is enabled
    audio_args = _audio_args(cfg_denoise, info_with_audio)
    assert "-af" in audio_args
    assert any("afftdn" in a for a in audio_args)


def test_compute_metric_ssim_parsing():
    mock_stderr = (
        "[Parsed_ssim_0 @ 0x79e628001d40] SSIM Y:0.998751 (29.035325) "
        "U:0.998787 (29.159648) V:0.998878 (29.501312) All:0.998778 (29.130428)\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = mock_stderr
        val = compute_metric(Path("src.mp4"), Path("out.mp4"), "ssim")
        assert val is not None
        assert abs(val - 0.998778) < 1e-6


def test_compute_metric_vmaf_parsing():
    mock_stderr = "[Parsed_libvmaf_0 @ 0x798c8c001d40] VMAF score: 97.487287\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = mock_stderr
        val = compute_metric(Path("src.mp4"), Path("out.mp4"), "libvmaf")
        assert val is not None
        assert abs(val - 97.487287) < 1e-6


def test_compute_metric_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "error"
        assert compute_metric(Path("src.mp4"), Path("out.mp4"), "ssim") is None


def test_job_manifest_save_and_load(tmp_path: Path):
    m_file = tmp_path / "manifest.json"
    manifest = JobManifest(
        source="in.mp4",
        output="out.mp4",
        total_chunks=2,
        chunk_duration=180.0,
        chunks=[
            {"index": 0, "source": "chunk_0000.mp4", "output": "rendered_0000.mp4", "status": "done"},
            {"index": 1, "source": "chunk_0001.mp4", "output": "rendered_0001.mp4", "status": "pending"},
        ],
    )
    manifest.save(m_file)
    assert m_file.exists()

    loaded = JobManifest.load(m_file)
    assert loaded is not None
    assert loaded.total_chunks == 2
    assert loaded.chunks[0]["status"] == "done"
    assert loaded.chunks[1]["status"] == "pending"


def test_plan_triggers_audio_denoise_in_pipeline():
    cfg = Config(source=Path("in.mp4"), output=Path("out.mp4"), audio_denoise=False)
    info_with_audio = MediaInfo(
        path=Path("in.mp4"),
        width=1280,
        height=720,
        fps=30.0,
        duration=10.0,
        video_codec="h264",
        has_audio=True,
    )
    plan_with_audio = Plan(filters=(), stabilize=False, notes=(), audio_denoise=True)
    audio_args = _audio_args(cfg, info_with_audio, plan=plan_with_audio)
    assert "-af" in audio_args
    assert any("afftdn" in a for a in audio_args)


def test_split_and_concat_chunks_roundtrip(tmp_path: Path):
    import subprocess
    from restore.probe import probe

    src = tmp_path / "test_synth.mp4"
    # Create 6-second synthetic test video with GOP=15 (0.5s keyframes)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=6:size=160x120:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-g", "15", "-c:a", "aac", str(src)
    ], check=True)

    staging = tmp_path / "staging"
    chunks = split_chunks(src, staging, segment_time=2.0)
    assert len(chunks) >= 2

    # Verify each chunk is valid
    for c in chunks:
        c_info = probe(c)
        assert c_info.width == 160
        assert c_info.height == 120
        assert c_info.duration > 0.5

    out = tmp_path / "stitched.mp4"
    concat_chunks(chunks, out)
    assert out.exists()

    out_info = probe(out)
    assert out_info.width == 160
    assert out_info.height == 120
    assert abs(out_info.duration - 6.0) < 0.5
