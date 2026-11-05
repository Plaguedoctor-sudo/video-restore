from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    width: int
    height: int
    fps: float
    duration: float
    video_codec: str
    has_audio: bool

    @property
    def frame_count(self) -> int:
        return int(self.duration * self.fps)


def probe(path: Path) -> MediaInfo:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    num, den = (int(x) for x in Fraction(v["r_frame_rate"]).as_integer_ratio())
    return MediaInfo(
        path=path,
        width=int(v["width"]),
        height=int(v["height"]),
        fps=num / den,
        duration=float(data["format"].get("duration", 0.0)),
        video_codec=v.get("codec_name", "unknown"),
        has_audio=any(s["codec_type"] == "audio" for s in data["streams"]),
    )
