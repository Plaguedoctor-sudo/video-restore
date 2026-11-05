from pathlib import Path
from unittest.mock import patch

from restore.config import Config, Encoder, Preset
from restore.plan import Plan
from restore.probe import MediaInfo
from restore.pipeline import _audio_args, _base, _encoder_args, compute_metric


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
