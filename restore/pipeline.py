from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .analyze import SampleData
from .capabilities import MissingCapability, has_qsv, has_vidstab, require
from .config import Config, Encoder, Preset
from .plan import Plan
from .probe import MediaInfo, probe


class FFmpegError(RuntimeError):
    pass


@dataclass
class JobManifest:
    source: str
    output: str
    total_chunks: int
    chunk_duration: float
    chunks: list[dict[str, Any]]

    def save(self, path: Path) -> None:
        data = {
            "source": self.source,
            "output": self.output,
            "total_chunks": self.total_chunks,
            "chunk_duration": self.chunk_duration,
            "chunks": self.chunks,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> JobManifest | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return cls(
                source=data["source"],
                output=data["output"],
                total_chunks=data["total_chunks"],
                chunk_duration=data["chunk_duration"],
                chunks=data["chunks"],
            )
        except Exception:
            return None


def extract_samples(info: MediaInfo, count: int = 12, width: int = 320) -> SampleData:
    """Extracts frame samples, motion vectors, and audio characteristics via ffmpeg."""
    eff_count = min(max(count, int(info.duration // 20)), 36) if count == 12 else count
    step = max(info.duration / (eff_count + 1), 0.04)
    gray_list: list[np.ndarray] = []
    rgb_list: list[np.ndarray] = []

    for i in range(eff_count):
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

        dur = info.duration
        if dur <= 30.0:
            windows = [(0.0, min(dur, 4.0))]
        else:
            windows = [(dur * 0.2, 3.0), (dur * 0.5, 3.0), (dur * 0.8, 3.0)]

        all_deltas: list[tuple[float, float]] = []
        for ss, w_dur in windows:
            probe_dur = str(w_dur)
            cmd = ["ffmpeg", "-v", "error", "-ss", f"{ss:.2f}", "-t", probe_dur, "-i", str(info.path),
                   "-vf", f"vidstabdetect=shakiness=8:result={trf}", "-f", "null", "-"]
            subprocess.run(cmd, capture_output=True)
            if trf.exists():
                for line in trf.read_text().splitlines():
                    if "LM" in line:
                        nums = line.split("LM")[1].split()
                        if len(nums) >= 2:
                            try:
                                all_deltas.append((float(nums[0]), float(nums[1])))
                            except ValueError:
                                continue
                trf.unlink(missing_ok=True)
        return tuple(all_deltas)
    except Exception:
        return ()
    finally:
        if trf:
            trf.unlink(missing_ok=True)


def _extract_audio_noise_floor(info: MediaInfo) -> float | None:
    if not info.has_audio:
        return None
    try:
        dur = info.duration
        if dur <= 20.0:
            windows = [0.0]
        else:
            windows = [dur * 0.15, dur * 0.50, dur * 0.85]

        floors: list[float] = []
        for ss in windows:
            probe_dur = str(min(dur - ss, 4.0)) if dur > ss else "4"
            res = subprocess.run(
                ["ffmpeg", "-v", "info", "-ss", f"{ss:.2f}", "-t", probe_dur, "-i", str(info.path),
                 "-vn", "-af", "astats", "-f", "null", "-"],
                capture_output=True, text=True,
            )
            m = re.search(r"RMS trough dB:\s*(-?[0-9.]+|-[iI]nf)", res.stderr)
            if m:
                val = m.group(1)
                floors.append(-90.0 if "inf" in val.lower() else float(val))
            else:
                m2 = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", res.stderr)
                if m2:
                    floors.append(float(m2.group(1)))
        return min(floors) if floors else None
    except Exception:
        pass
    return None


def _base(cfg: Config) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-y", "-nostdin"]
    if cfg.sample_start is not None:
        cmd += ["-ss", str(cfg.sample_start)]
    if cfg.sample_duration is not None:
        cmd += ["-t", str(cfg.sample_duration)]
    cmd += ["-i", str(cfg.source)]
    cmd += ["-filter_threads", str(cfg.threads), "-threads", str(cfg.threads)]
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


def _audio_args(cfg: Config, info: MediaInfo, plan: Plan | None = None) -> list[str]:
    if not info.has_audio:
        return []
    needs_denoise = cfg.audio_denoise or (plan is not None and plan.audio_denoise)
    if needs_denoise:
        return ["-c:a", "aac", "-b:a", "192k", "-af", "afftdn=nr=12:nf=-25"]
    return ["-c:a", "copy"]


def stabilize_pass(
    info: MediaInfo,
    trf: Path,
    duration: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> None:
    if not has_vidstab():
        raise MissingCapability("libvidstab not available; rebuild ffmpeg")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin"]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += [
        "-i", str(info.path),
        "-vf", f"vidstabdetect=shakiness=8:accuracy=15:result={trf}",
    ]
    if progress_callback:
        cmd += ["-progress", "pipe:1", "-nostats", "-f", "null", "-"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        eff_dur = duration or max(info.duration, 0.01)
        for line in proc.stdout:
            if line.startswith("out_time_us="):
                us = line.strip().split("=")[1]
                if us.isdigit():
                    pct = min(100.0, int(us) / 1e6 / eff_dur * 100)
                    progress_callback(pct)
        proc.wait()
        if proc.returncode != 0:
            err = proc.stderr.read() if proc.stderr else ""
            raise FFmpegError(err.strip().splitlines()[-1] if err else "vidstabdetect failed")
    else:
        cmd += ["-f", "null", "-"]
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


def split_chunks(source: Path, staging_dir: Path, segment_time: float = 180.0) -> list[Path]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(staging_dir / "chunk_%04d.mp4")
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source),
        "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", str(segment_time), "-reset_timestamps", "1",
        "-break_non_keyframes", "0", pattern,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    chunks = sorted(staging_dir.glob("chunk_*.mp4"))
    if res.returncode != 0 or not chunks:
        single_chunk = staging_dir / "chunk_0000.mp4"
        shutil.copyfile(source, single_chunk)
        return [single_chunk]
    return chunks


def concat_chunks(chunk_outputs: list[Path], final_output: Path) -> None:
    if not chunk_outputs:
        raise FFmpegError("No chunks to concatenate")
    if len(chunk_outputs) == 1:
        tmp_final = final_output.with_suffix(".part" + final_output.suffix)
        shutil.copyfile(chunk_outputs[0], tmp_final)
        tmp_final.replace(final_output)
        return

    work_dir = chunk_outputs[0].parent
    concat_list = work_dir / "concat_list.txt"
    lines = [f"file '{p.resolve().as_posix()}'" for p in chunk_outputs]
    concat_list.write_text("\n".join(lines))

    tmp_final = final_output.with_suffix(".part" + final_output.suffix)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(tmp_final),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        tmp_final.unlink(missing_ok=True)
        err = res.stderr.strip().splitlines()[-1] if res.stderr else "Concat failed"
        raise FFmpegError(f"Concat failed: {err}")
    tmp_final.replace(final_output)


def _render_single_unit(
    cfg: Config,
    plan: Plan,
    info: MediaInfo,
    out_target: Path,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    require("atadenoise", "nlmeans", "deblock", "normalize", "cas", "unsharp")

    tmp_out = out_target.with_suffix(".part" + out_target.suffix)
    trf: Path | None = None

    if cfg.sample_duration is not None:
        effective_duration = cfg.sample_duration
    elif cfg.sample_start is not None:
        effective_duration = max(info.duration - cfg.sample_start, 0.01)
    else:
        effective_duration = max(info.duration, 0.01)

    try:
        cmd = _base(cfg)
        vf_parts: list[str] = []
        if cfg.scale_height is not None and cfg.scale_height < info.height:
            vf_parts.append(f"scale=-2:{cfg.scale_height}")

        graph_str = plan.graph().replace("filter=strongest", "filter=strong:alpha=0.25:beta=0.18")
        if plan.stabilize:
            fd, name = tempfile.mkstemp(suffix=".trf")
            os.close(fd)
            trf = Path(name)

            def on_stab_prog(p: float) -> None:
                if progress_callback:
                    progress_callback(p * 0.25)

            stabilize_pass(info, trf, duration=cfg.sample_duration, progress_callback=on_stab_prog)
            trans_filt = f"vidstabtransform=input={trf}:smoothing=25:optzoom=2:interpol=bicubic"
            vf_parts.insert(0, trans_filt)

        vf_parts.append(graph_str)
        vf_str = ",".join(p.strip(",") for p in vf_parts if p and p.strip(","))
        cmd += ["-vf", vf_str]

        cmd += _encoder_args(cfg)
        cmd += _audio_args(cfg, info, plan)
        cmd += ["-progress", "pipe:1", "-nostats", str(tmp_out)]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith("out_time_us="):
                us = line.strip().split("=")[1]
                if us.isdigit():
                    render_pct = min(100.0, int(us) / 1e6 / effective_duration * 100)
                    unit_p = (25.0 + render_pct * 0.75) if plan.stabilize else render_pct
                    if progress_callback:
                        progress_callback(unit_p)
                    else:
                        print(f"\r  {unit_p:5.1f}%", end="", flush=True)
        proc.wait()
        if not progress_callback:
            print()
        if proc.returncode != 0:
            err = proc.stderr.read() if proc.stderr else ""
            tmp_out.unlink(missing_ok=True)
            raise FFmpegError(err.strip().splitlines()[-1] if err else "ffmpeg failed")
        tmp_out.replace(out_target)
        return out_target
    finally:
        if trf:
            trf.unlink(missing_ok=True)


def render(
    cfg: Config,
    plan: Plan,
    info: MediaInfo,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    chunk_sec = cfg.chunk_duration if cfg.chunk_duration is not None else 180.0
    should_chunk = (
        cfg.chunk_duration is not None
        and cfg.chunk_duration > 0
        and info.duration > (chunk_sec * 1.25)
        and cfg.sample_duration is None
        and cfg.sample_start is None
    )

    if not should_chunk:
        return _render_single_unit(cfg, plan, info, cfg.output, progress_callback=progress_callback)

    staging_dir = cfg.work_dir or (cfg.output.parent / f".vr_{cfg.output.stem}_staging")
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = staging_dir / "manifest.json"

    manifest = None
    if cfg.resume and manifest_path.exists():
        manifest = JobManifest.load(manifest_path)

    if manifest is None:
        raw_chunks = split_chunks(cfg.source, staging_dir, segment_time=chunk_sec)
        chunk_items = []
        for i, c_path in enumerate(raw_chunks):
            out_name = f"rendered_{c_path.stem.replace('chunk_', '')}.mp4"
            try:
                c_info = probe(c_path)
                dur = c_info.duration
            except Exception:
                dur = chunk_sec
            chunk_items.append({
                "index": i,
                "source": str(c_path),
                "output": str(staging_dir / out_name),
                "status": "pending",
                "duration": dur,
            })
        manifest = JobManifest(
            source=str(cfg.source),
            output=str(cfg.output),
            total_chunks=len(chunk_items),
            chunk_duration=chunk_sec,
            chunks=chunk_items,
        )
        manifest.save(manifest_path)

    total_chunks = len(manifest.chunks)
    rendered_outputs: list[Path] = []

    for item in manifest.chunks:
        idx = item["index"]
        c_src = Path(item["source"])
        c_out = Path(item["output"])

        if item.get("status") == "done" and c_out.exists() and c_out.stat().st_size > 0:
            rendered_outputs.append(c_out)
            continue

        c_info = probe(c_src)
        c_cfg = cfg.with_(source=c_src, output=c_out, sample_start=None, sample_duration=None)

        def on_chunk_prog(p: float) -> None:
            overall = ((idx + p / 100.0) / total_chunks) * 100.0
            if progress_callback:
                progress_callback(min(99.0, overall))
            else:
                print(f"\r  Chunk {idx+1}/{total_chunks} ({p:5.1f}%) -> Total: {overall:5.1f}%", end="", flush=True)

        _render_single_unit(c_cfg, plan, c_info, c_out, progress_callback=on_chunk_prog)
        item["status"] = "done"
        manifest.save(manifest_path)
        rendered_outputs.append(c_out)

    if not progress_callback:
        print("\r  Stitching chunks...                                      ", end="", flush=True)

    concat_chunks(rendered_outputs, cfg.output)

    if not cfg.keep_chunks:
        shutil.rmtree(staging_dir, ignore_errors=True)

    if not progress_callback:
        print("\r  100.0% [Complete]                                        ")
    return cfg.output
