from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetValues:
    nlmeans_s: int
    nlmeans_r: int
    atadenoise_scale: float
    cas_strength: float
    unsharp_amount: float
    chroma_unsharp: float
    use_fftdnoiz: bool
    deblock_filter: str
    deband: bool


PRESETS: dict[str, PresetValues] = {
    "preview":  PresetValues(5, 7,  0.7, 0.35, 0.35, 0.0, False, "weak",      False),
    "fast":     PresetValues(4, 5,  0.8, 0.35, 0.40, 0.0, False, "weak",      False),
    "standard": PresetValues(7, 15, 1.0, 0.45, 0.50, 0.0, False, "strong",    False),
    "max":      PresetValues(11, 21, 1.3, 0.55, 0.60, 0.0, True,  "strongest", False),
    # Telegram: low nlmeans (surfaces already smooth), hardest deblock,
    # chroma sharpening to rebuild what 4:2:0 destroyed, mandatory deband.
    "telegram": PresetValues(6, 11, 1.0, 0.35, 0.55, 0.40, False, "strongest", True),
}
