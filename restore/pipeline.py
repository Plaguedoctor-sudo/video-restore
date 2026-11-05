from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np

from .analyze import SampleData
from .capabilities import MissingCapability, has_qsv, has_vidstab, require
from .config import Config, Encoder, Preset
from .plan import Plan
from .probe import MediaInfo


class FFmpegError(RuntimeError):
    pass


def extract_samples(info: MediaInfo, count: int = 12, width: int = 320) -> SampleData:
    """Extracts frame samples, motion vectors, and audio characteristics via ffmpeg."""
    step = max(info.duration / (count + 1), 0.04)
    gray_list: list[np.ndarray] = []
    rgb_list: list[np.ndarray] = []

    for i in range(count):
        ss = step * (i + 1)
        try:
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-i", str(info.path),
                 "-frames:v", "1", "-vf", f"scale={width}:-2,format=rgb24",
                 "-f", "rawvideo", "-"],
                capture_output=True, check=True,
            ).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        if not raw:
            continue
        # Each RGB pixel is 3 bytes
        frame_bytes = len(raw)
        h = frame_bytes // (width * 3)
        if h < 2:
            continue
        rgb = np.frombuffer(raw[: width * h * 3], np.uint8).reshape((h, width, 3))
        gray = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.uint8)
        rgb_list.append(rgb)
        gray_list.append(gray)

    if gray_list:
        gray_frames = np.stack(gray_list)
        rgb_frames = np.stack(rgb_list)
    else:
        gray_frames = np.zeros((1, 64, width), np.uint8)
        rgb_frames = np.zeros((1, 64, width, 3), np.uint8)

    motion_deltas = _extract_motion_vectors(info)
    audio_floor = _extract_audio_noise_floor(info) if info.has_audio else None

    return SampleData(
        gray_frames=gray_frames,
        rgb_frames=rgb_frames,
        motion_deltas=motion_deltas,
        audio_noise_floor_db=audio_floor,
    )


def _extract_motion_vectors(info: MediaInfo) -> tuple[tuple[float, float], ...]:
    if not has_vidstab():
        return ()
    trf: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".trf", delete=False) as tmp:
            trf = Path(tmp.name)
        probe_dur = str(min(info.duration, 4.0)) if info.duration > 0 else "4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-t", probe_dur, "-i", str(info.path),
             "-vf", f"vidstabdetect=shakiness=8:result={trf}", "-f", "null", "-"],
            capture_output=True,
        )
        if not trf.exists():
            return ()
        deltas: list[tuple[float, float]] = []
        for line in trf.read_text().splitlines():
            if "LM" in line:
                nums = line.split("LM")[1].split()
                if len(nums) >= 2:
                    try:
                        deltas.append((float(nums[0]), float(nums[1])))
                    except ValueError:
                        continue
        return tuple(deltas)
    except Exception:
        return ()
    finally:
        if trf:
            trf.unlink(missing_ok=True)


def _extract_audio_noise_floor(info: MediaInfo) -> float | None:
    try:
        probe_dur = str(min(info.duration, 6.0)) if info.duration > 0 else "6"
        res = subprocess.run(
            ["ffmpeg", "-v", "info", "-t", probe_dur, "-i", str(info.path),
             "-vn", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        # volumedetect prints mean_volume: -XX.X dB
        m = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", res.stderr)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def _base(cfg: Config) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-y", "-nostdin", "-threads", str(cfg.threads)]
    if cfg.sample_start is not None:
        cmd += ["-ss", str(cfg.sample_start)]
    if cfg.sample_duration is not None:
        cmd += ["-t", str(cfg.sample_duration)]
    cmd += ["-i", str(cfg.source)]
    return cmd


def _encoder_args(cfg: Config) -> list[str]:
    if cfg.encoder is Encoder.X264:
        preset = "veryfast" if cfg.preset in (Preset.PREVIEW, Preset.FAST) else "fast"
        return [
            "-c:v", "libx264",
            "-crf", "20",
            "-preset", preset,
        ]

    if cfg.encoder is Encoder.QSV:
        if has_qsv():
            return [
                "-c:v", "hevc_qsv",
                "-global_quality", str(cfg.qsv_quality),
                "-preset", "slow",
            ]
        # Auto-fallback to libx265 when QSV hardware is unavailable
        sys.stderr.write("[restore] Intel QSV not available on this platform; using libx265 fallback.\n")

    x265_preset = "fast" if cfg.preset in (Preset.PREVIEW, Preset.FAST) else "medium"
    return [
        "-c:v", "libx265",
        "-crf", str(cfg.crf),
        "-preset", x265_preset,
        "-x265-params", "log-level=error",
    ]


def _audio_args(cfg: Config, info: MediaInfo) -> list[str]:
    if not info.has_audio:
        return []
    if cfg.audio_denoise:
        return ["-c:a", "aac", "-b:a", "192k", "-af", "afftdn=nr=12:nf=-25"]
    return ["-c:a", "copy"]


def stabilize_pass(info: MediaInfo, trf: Path, duration: float | None = None) -> None:
    if not has_vidstab():
        raise MissingCapability("libvidstab not available; rebuild ffmpeg")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin"]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += [
        "-i", str(info.path),
        "-vf", f"vidstabdetect=shakiness=8:accuracy=15:result={trf}",
        "-f", "null", "-",
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def compute_metric(src: Path, out: Path, filt: str) -> float | None:
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(out), "-i", str(src),
             "-lavfi", f"[0:v][1:v]{filt}", "-f", "null", "-"],
            capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    if r.returncode != 0:
        return None

    if "ssim" in filt:
        m = re.search(r"All:\s*([0-9.]+)", r.stderr)
        if not m:
            m = re.search(r"SSIM\s+Y:\s*([0-9.]+)", r.stderr)
        return float(m.group(1)) if m else None
    if "vmaf" in filt:
        m = re.search(r"VMAF score:\s*([0-9.]+)", r.stderr)
        return float(m.group(1)) if m else None

    m = re.search(r"([0-9]+\.[0-9]+)", r.stderr)
    return float(m.group(1)) if m else None


def render(
    cfg: Config,
    plan: Plan,
    info: MediaInfo,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    require("atadenoise", "nlmeans", "deblock", "normalize", "cas", "unsharp")

    tmp_out = cfg.output.with_suffix(".part" + cfg.output.suffix)
    trf: Path | None = None

    effective_duration = cfg.sample_duration or info.duration

    try:
        cmd = _base(cfg)
        vf_parts: list[str] = []
        if cfg.scale_height is not None and cfg.scale_height < info.height:
            vf_parts.append(f"scale=-2:{cfg.scale_height}")

        graph_str = plan.graph().replace("filter=strongest", "filter=strong")
        if plan.stabilize:
            fd, name = tempfile.mkstemp(suffix=".trf")
            os.close(fd)
            trf = Path(name)
            stabilize_pass(info, trf, duration=cfg.sample_duration)
            trans_filt = f"vidstabtransform=input={trf}:smoothing=25:optzoom=2:interpol=bicubic"
            vf_parts.insert(0, trans_filt)

        vf_parts.append(graph_str)
        cmd += ["-vf", ",".join(vf_parts)]

        cmd += _encoder_args(cfg)
        cmd += _audio_args(cfg, info)
        cmd += ["-progress", "pipe:1", "-nostats", str(tmp_out)]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith("out_time_us="):
                us = line.strip().split("=")[1]
                if us.isdigit():
                    pct = min(100.0, int(us) / 1e6 / max(effective_duration, 0.01) * 100)
                    if progress_callback:
                        progress_callback(pct)
                    else:
                        print(f"\r  {pct:5.1f}%", end="", flush=True)
        proc.wait()
        if not progress_callback:
            print()
        if proc.returncode != 0:
            err = proc.stderr.read() if proc.stderr else ""
            tmp_out.unlink(missing_ok=True)
            raise FFmpegError(err.strip().splitlines()[-1] if err else "ffmpeg failed")
        tmp_out.replace(cfg.output)
        return cfg.output
    finally:
        if trf:
            trf.unlink(missing_ok=True)
