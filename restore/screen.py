from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .probe import MediaInfo


@dataclass(frozen=True)
class Quad:
    """Screen corners in source pixels, ordered TL, TR, BR, BL."""
    pts: tuple[tuple[int, int], ...]

    def as_filter(self) -> str:
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = self.pts
        return (
            f"perspective=x0={x0}:y0={y0}:x1={x1}:y1={y1}"
            f":x2={x2}:y2={y2}:x3={x3}:y3={y3}:sense=source:eval=init"
        )

    def bbox(self) -> tuple[int, int, int, int]:
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        x, y = min(xs), min(ys)
        return x, y, max(xs) - x, max(ys) - y


def _frame_at(info: MediaInfo, seconds: float) -> np.ndarray | None:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{seconds:.2f}", "-i", str(info.path),
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True,
    ).stdout
    if not raw:
        return None
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def _largest_quad(img: np.ndarray) -> tuple[tuple[int, int], ...] | None:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.25 * w * h:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        if area > best_area:
            best, best_area = approx, area
    if best is None:
        return None

    pts = best.reshape(4, 2).astype(float)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    ordered = np.array([
        pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]
    ])
    return tuple((int(x), int(y)) for x, y in ordered)


def detect(info: MediaInfo, samples: int = 5) -> Quad | None:
    """Median of several keyframe detections. None if detection fails."""
    if info.duration < 1.0:
        return None
    found: list[np.ndarray] = []
    for i in range(samples):
        t = info.duration * (i + 1) / (samples + 1)
        frame = _frame_at(info, t)
        if frame is None:
            continue
        quad = _largest_quad(frame)
        if quad:
            found.append(np.array(quad, float))
    if len(found) < 2:
        return None
    med = np.median(np.stack(found), axis=0)
    return Quad(tuple((int(x), int(y)) for x, y in med))


def parse_quad(spec: str) -> Quad:
    pts = [tuple(int(v) for v in p.split(":")) for p in spec.split(",")]
    if len(pts) != 4:
        raise ValueError("--quad wants x0:y0,x1:y1,x2:y2,x3:y3")
    return Quad(tuple(pts))


def parse_crop(spec: str) -> str:
    parts = [int(v) for v in spec.split(",")]
    if len(parts) != 4:
        raise ValueError("--crop wants x,y,w,h")
    x, y, w, h = parts
    return f"crop={w}:{h}:{x}:{y}"


def band_score(info: MediaInfo, samples: int = 24) -> float:
    """Variance of per-row luma over time. Rolling bands score high."""
    frames = [f for i in range(samples)
              if (f := _frame_at(info, info.duration * (i + 1) / (samples + 1))) is not None]
    if len(frames) < 4:
        return 0.0
    rows = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).mean(axis=1) for f in frames])
    return float(np.clip(rows.std(axis=0).mean() / 6.0, 0.0, 1.0))


def moire_score(info: MediaInfo) -> float:
    """High-frequency band energy in a mid clip frame."""
    frame = _frame_at(info, info.duration * 0.5)
    if frame is None:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    f = np.fft.fftshift(np.abs(np.fft.fft2(gray)))
    h, w = f.shape
    cy, cx, r = h // 2, w // 2, min(h, w) // 2
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / r
    hi = f[(dist > 0.35) & (dist < 0.95)].mean()
    mid = f[(dist > 0.05) & (dist < 0.35)].mean()
    return float(np.clip((hi / (mid + 1e-6)) * 1.4, 0.0, 1.0))
