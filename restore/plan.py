from __future__ import annotations

from dataclasses import dataclass

from .analyze import DefectProfile
from .presets import PRESETS, PresetValues


@dataclass(frozen=True)
class Plan:
    filters: tuple[str, ...]
    stabilize: bool
    notes: tuple[str, ...]

    def graph(self) -> str:
        return ",".join(self.filters) + ",format=yuv420p,setsar=1"


def build_plan(
    profile: DefectProfile,
    preset: str,
    denoise_mult: float = 1.0,
    sharpen_mult: float = 1.0,
    tonal: bool = True,
    extra: tuple[str, ...] = (),
    *,
    telegram: bool = False,
    video_note: bool = False,
    audio_denoise: bool = False,
    geometry: str | None = None,      # perspective filter, screen mode only
    crop: str | None = None,          # crop filter, screen mode only
    moire: float = 0.0,
    bands: float = 0.0,
) -> Plan:
    pv: PresetValues = PRESETS[preset]
    f: list[str] = []
    notes: list[str] = []

    # S1 geometry first, always
    if geometry:
        f.append(geometry)
        notes.append("perspective correct")
    if crop:
        f.append(crop)
        notes.append("crop to screen")

    # S2 moire suppression before anything sharpens
    if moire > 0.25:
        f.append("smartblur=lr=1.6:ls=-0.4:lt=8")
        notes.append(f"moire smartblur @ {moire:.2f}")

    # S3 rolling bands
    if bands > 0.3:
        f.append("deflicker=mode=am:size=10")
        f.append("tmix=frames=3")
        notes.append("band removal")

    if video_note:
        notes.append("video note (1:1, low-res)")
        profile = DefectProfile(
            profile.shake * 0.5, max(profile.noise, 0.35), profile.blocking,
            profile.flicker, profile.dark, profile.washed, profile.cast,
            max(profile.soft, 0.4),
        )

    if profile.noise > 0.15:
        t = 0.02 * pv.atadenoise_scale * denoise_mult
        c = t * 2.0
        f.append(
            f"atadenoise=0a={t:.3f}:0b={t*2:.3f}:1a={c:.3f}:1b={c*2:.3f}"
            f":2a={c:.3f}:2b={c*2:.3f}"
        )
        notes.append(f"temporal denoise @ {t:.3f}")

    if profile.noise > 0.30:
        s = max(3, round(pv.nlmeans_s * denoise_mult))
        f.append(f"nlmeans=s={s}:p=5:r={pv.nlmeans_r}")
        notes.append(f"nlmeans s={s}")
        if pv.use_fftdnoiz:
            f.append(f"fftdnoiz=sigma={max(4, s)}:amount=0.8")

    if profile.blocking > 0.20:
        f.append(f"deblock=filter={pv.deblock_filter}:block=8:alpha=0.1:beta=0.08")
        notes.append(f"deblock {pv.deblock_filter}")

    if pv.deband or profile.flicker > 0.5:
        f.append("deband=1thr=0.02:2thr=0.02:3thr=0.02:4thr=0.02:blur=1:range=16")
        notes.append("deband")

    if profile.flicker > 0.35 and bands <= 0.3:
        f.append("deflicker=mode=am:size=10")
        notes.append("deflicker")

    if tonal:
        if profile.dark > 0.2 or profile.washed > 0.2 or profile.cast > 0.2:
            f.append("normalize=blackpt=black:whitept=white:independence=0:smoothing=50")
            notes.append("auto levels")
        if profile.dark > 0.2:
            f.append("curves=preset=lighter")
            f.append("eq=brightness=0.03:gamma=0.97")
        if profile.washed > 0.2:
            f.append("eq=contrast=1.12:saturation=1.10")
        if profile.cast > 0.2:
            f.append("colorbalance=gs=-0.03:gm=-0.02")

    if profile.soft > 0.25:
        cap = 0.4 if geometry else 0.6
        strength = round(min(pv.cas_strength * sharpen_mult, cap), 2)
        f.append(f"cas=strength={strength}")
        f.append(
            f"unsharp=5:5:{pv.unsharp_amount * sharpen_mult:.2f}"
            f":5:5:{pv.chroma_unsharp:.2f}"
        )
        notes.append(f"sharpen cas {strength}")

    f.extend(extra)
    return Plan(tuple(f), stabilize=profile.shake > 0.12 and not video_note,
                notes=tuple(notes))
