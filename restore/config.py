from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path


class Preset(str, Enum):
    PREVIEW = "preview"
    FAST = "fast"
    STANDARD = "standard"
    MAX = "max"
    TELEGRAM = "telegram"


class Encoder(str, Enum):
    QSV = "qsv"
    X265 = "x265"
    X264 = "x264"


@dataclass(frozen=True)
class Config:
    source: Path
    output: Path
    preset: Preset = Preset.STANDARD
    encoder: Encoder = Encoder.QSV
    stabilize: bool | None = None      # None = decide from analysis
    denoise_strength: float = 1.0      # multiplier on preset defaults
    sharpen: float = 1.0
    tonal: bool = True
    audio_denoise: bool = False
    crf: int = 19
    qsv_quality: int = 18
    threads: int = 2
    force: bool = False
    sample_start: float | None = None
    sample_duration: float | None = None
    extra_filters: tuple[str, ...] = field(default_factory=tuple)
    source_kind: str = "auto"     # auto | local | telegram
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    screen_mode: bool = False
    quad: str | None = None
    crop: str | None = None
    moire: float | None = None
    scale_height: int | None = None
    chunk_duration: float | None = 180.0
    resume: bool = False
    keep_chunks: bool = False
    work_dir: Path | None = None

    def with_(self, **kw) -> "Config":
        return replace(self, **kw)
