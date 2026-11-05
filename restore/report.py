from __future__ import annotations

from pathlib import Path

from .pipeline import compute_metric


def _score(src: Path, out: Path, filt: str) -> float | None:
    return compute_metric(src, out, filt)


def compare(src: Path, out: Path) -> str:
    ssim = _score(src, out, "ssim")
    vmaf = _score(src, out, "libvmaf")
    lines = []
    if ssim is not None:
        lines.append(f"SSIM: {ssim:.4f}")
    if vmaf is not None:
        lines.append(f"VMAF: {vmaf:.2f}")
    if not lines:
        lines.append("No metrics available (needs libvmaf / ssim support).")
    else:
        verdict = "PASS" if (ssim or 0) >= 0.90 else "REVIEW"
        lines.append(f"Verdict: {verdict} — inspect 100% crops before shipping.")
    return "\n".join(lines)
