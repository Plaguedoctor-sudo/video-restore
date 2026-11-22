from pathlib import Path
import subprocess

from restore.analyze import DefectProfile, analyze
from restore.config import Config, Encoder, Preset
from restore.pipeline import JobManifest, render
from restore.plan import build_plan
from restore.probe import probe


def test_chunked_rendering_end_to_end(tmp_path: Path):
    src = tmp_path / "long_clip.mp4"
    out = tmp_path / "restored.mp4"

    # Generate an 8-second clip with 1-second GOP keyframes
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=8:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-c:v", "libx264", "-g", "25", "-c:a", "aac", str(src)
    ], check=True)

    info = probe(src)
    assert info.duration >= 7.9
    assert info.width == 320
    assert info.height == 240

    profile = DefectProfile(0.0, 0.2, 0.1, 0.0, 0.0, 0.0, 0.0, 0.3)
    plan = build_plan(profile, "fast")

    # Set chunk_duration to 2.5 seconds so an 8-second video is split into ~3 chunks
    cfg = Config(
        source=src,
        output=out,
        preset=Preset.FAST,
        encoder=Encoder.X264,
        chunk_duration=2.5,
        threads=2,
        force=True,
    )

    rendered_path = render(cfg, plan, info)
    assert rendered_path == out
    assert out.exists()

    out_info = probe(out)
    # Rule 1 check: dimensions strictly preserved
    assert out_info.width == info.width
    assert out_info.height == info.height
    # Duration preserved within GOP tolerance
    assert abs(out_info.duration - info.duration) < 0.5
    assert out_info.has_audio is True


def test_chunked_resume_capability(tmp_path: Path):
    src = tmp_path / "resume_clip.mp4"
    out = tmp_path / "resume_restored.mp4"
    staging_dir = tmp_path / "custom_staging"

    # Generate 6-second video
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=6:size=160x120:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-g", "25", "-c:a", "aac", str(src)
    ], check=True)

    info = probe(src)
    profile = DefectProfile(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    plan = build_plan(profile, "fast")

    # Pre-populate staging with manifest and fake chunk 0 as done
    staging_dir.mkdir(parents=True, exist_ok=True)
    chunk0_out = staging_dir / "rendered_0000.mp4"
    # Copy a 2-second valid video as rendered_0000.mp4
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-c:a", "aac", str(chunk0_out)
    ], check=True)

    # Split remaining chunks
    chunk1_src = staging_dir / "chunk_0001.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-ss", "2.0", "-i", str(src),
        "-c", "copy", str(chunk1_src)
    ], check=True)

    manifest = JobManifest(
        source=str(src),
        output=str(out),
        total_chunks=2,
        chunk_duration=3.0,
        chunks=[
            {"index": 0, "source": str(staging_dir / "chunk_0000.mp4"), "output": str(chunk0_out), "status": "done", "duration": 2.0},
            {"index": 1, "source": str(chunk1_src), "output": str(staging_dir / "rendered_0001.mp4"), "status": "pending", "duration": 4.0},
        ],
    )
    manifest.save(staging_dir / "manifest.json")

    # Run with resume=True and keep_chunks=True to inspect
    cfg = Config(
        source=src,
        output=out,
        preset=Preset.FAST,
        encoder=Encoder.X264,
        chunk_duration=3.0,
        resume=True,
        keep_chunks=True,
        work_dir=staging_dir,
        threads=2,
        force=True,
    )

    rendered_path = render(cfg, plan, info)
    assert rendered_path == out
    assert out.exists()

    # Verify manifest was updated to done for chunk 1
    updated_manifest = JobManifest.load(staging_dir / "manifest.json")
    assert updated_manifest is not None
    assert updated_manifest.chunks[1]["status"] == "done"
