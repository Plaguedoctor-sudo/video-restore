from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from .probe import MediaInfo


@dataclass(frozen=True)
class SampleData:
    gray_frames: np.ndarray                          # (N, H, W) uint8
    rgb_frames: np.ndarray | None = None             # (N, H, W, 3) uint8 or None
    motion_deltas: tuple[tuple[float, float], ...] = ()
    audio_noise_floor_db: float | None = None


@dataclass(frozen=True)
class DefectProfile:
    shake: float
    noise: float
    blocking: float
    flicker: float
    dark: float
    washed: float
    cast: float
    soft: float
    hiss: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in asdict(self).items()}

    def summary(self) -> str:
        rows = sorted(self.as_dict().items(), key=lambda kv: -kv[1])
        return "\n".join(
            f"  {k:<9} {'#' * int(v * 30):<30} {v:.2f}" for k, v in rows if v > 0.02
        ) or "  (clean)"


def _laplacian_var(f: np.ndarray) -> float:
    """Measures high-frequency variance using a discrete Laplacian kernel."""
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], np.float32)
    h, w = f.shape
    if h < 3 or w < 3:
        return 0.0
    win = np.lib.stride_tricks.sliding_window_view(f.astype(np.float32), (3, 3))
    return float((win * k).sum(axis=(2, 3)).var())


def _blockiness(f: np.ndarray) -> float:
    """Ratio of gradient energy on 8px boundaries vs interior. ~1 clean, >1.3 blocked."""
    g = np.abs(np.diff(f.astype(np.float32), axis=1))
    if g.shape[1] <= 8:
        return 1.0
    cols = np.arange(g.shape[1])
    edge = g[:, (cols % 8) == 7].mean()
    inner = g[:, (cols % 8) != 7].mean()
    return float(edge / inner) if inner > 1e-6 else 1.0


def _calc_shake(motion_deltas: tuple[tuple[float, float], ...]) -> float:
    """Calculates shake score from motion displacement standard deviations."""
    if len(motion_deltas) < 4:
        return 0.0
    dx = [abs(d[0]) for d in motion_deltas]
    dy = [abs(d[1]) for d in motion_deltas]
    total_std = float(np.std(dx) + np.std(dy))
    return float(min(total_std, 12.0) / 12.0)


def _calc_color_cast(rgb_frames: np.ndarray | None, clipped_low: float) -> float:
    """D6: Colour cast detected via per-channel mean divergence across R, G, B."""
    if rgb_frames is not None and rgb_frames.size > 0 and rgb_frames.ndim == 4:
        r_mean = float(rgb_frames[..., 0].mean())
        g_mean = float(rgb_frames[..., 1].mean())
        b_mean = float(rgb_frames[..., 2].mean())
        total = (r_mean + g_mean + b_mean) / 3.0
        if total > 8.0:
            divergence = max(abs(r_mean - total), abs(g_mean - total), abs(b_mean - total)) / total
            # ~0.08 divergence is noticeable cast, >0.25 is heavy cast
            return float(np.clip(divergence * 3.5, 0.0, 1.0))
    # Fallback to dark/clipping heuristic if no RGB frames provided
    return float(np.clip(clipped_low * 2.0, 0.0, 1.0)) if clipped_low > 0.15 else 0.0


def _calc_audio_hiss(audio_noise_floor_db: float | None) -> float:
    """D8: Hiss / hum detected from audio noise floor."""
    if audio_noise_floor_db is None:
        return 0.0
    # Clean audio has floor <= -50 dB; severe hiss is > -25 dB
    return float(np.clip((audio_noise_floor_db + 50.0) / 25.0, 0.0, 1.0))


def analyze(sample_or_info: SampleData | MediaInfo) -> DefectProfile:
    """Pure analysis of video defect characteristics. No subprocess, no I/O."""
    if hasattr(sample_or_info, "path"):
        # Convenience bridge if MediaInfo passed directly: sample via pipeline
        from .pipeline import extract_samples
        samples: SampleData = extract_samples(sample_or_info)
    else:
        samples = sample_or_info

    frames = samples.gray_frames
    if frames.ndim == 2:
        frames = np.expand_dims(frames, axis=0)
    f32 = frames.astype(np.float32)

    luma_mean = float(f32.mean()) / 255.0
    clipped_low = float((f32 < 12).mean())
    clipped_high = float((f32 > 243).mean())

    # Temporal delta in the quietest decile approximates sensor noise floor
    if len(frames) > 1:
        deltas = np.abs(np.diff(f32, axis=0)).mean(axis=(1, 2))
        noise = float(min(np.percentile(deltas, 20), 14.0) / 14.0)
    else:
        noise = 0.0

    lap = np.array([_laplacian_var(f) for f in frames])
    sharp = float(min(lap.mean(), 400.0) / 400.0)

    block = float(np.clip((np.mean([_blockiness(f) for f in frames]) - 1.0) / 0.6, 0.0, 1.0))
    flicker = float(np.clip(np.std(frames.mean(axis=(1, 2))) / 12.0, 0.0, 1.0)) if len(frames) > 1 else 0.0

    dark = float(np.clip((90.0 - luma_mean * 255.0) / 90.0, 0.0, 1.0)) if (luma_mean * 255.0) < 90.0 else 0.0
    washed = float(np.clip((clipped_high - 0.08) * 4.0, 0.0, 1.0)) if (luma_mean * 255.0) > 150.0 else 0.0
    cast = _calc_color_cast(samples.rgb_frames, clipped_low)
    hiss = _calc_audio_hiss(samples.audio_noise_floor_db)

    return DefectProfile(
        shake=_calc_shake(samples.motion_deltas),
        noise=noise,
        blocking=block,
        flicker=flicker,
        dark=dark,
        washed=washed,
        cast=cast,
        soft=float(np.clip(1.0 - sharp * 2.2, 0.0, 1.0)),
        hiss=hiss,
    )
