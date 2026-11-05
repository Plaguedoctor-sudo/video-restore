from __future__ import annotations

import functools
import subprocess


class MissingCapability(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def available_filters() -> frozenset[str]:
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise MissingCapability("ffmpeg not found on PATH")
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[0].startswith("-"):
            names.add(parts[1])
    return frozenset(names)


@functools.lru_cache(maxsize=1)
def available_encoders() -> frozenset[str]:
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return frozenset()
    encoders = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return frozenset(encoders)


@functools.lru_cache(maxsize=1)
def has_qsv() -> bool:
    if "hevc_qsv" not in available_encoders():
        return False
    try:
        res = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=128x128:d=0.04",
             "-c:v", "hevc_qsv", "-f", "null", "-"],
            capture_output=True, text=True, timeout=3,
        )
        return res.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return False



@functools.lru_cache(maxsize=1)
def has_vidstab() -> bool:
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-h", "filter=vidstabdetect"],
            capture_output=True, text=True,
        )
        return "vidstabdetect" in (out.stdout + out.stderr)
    except FileNotFoundError:
        return False


def require(*names: str) -> None:
    have = available_filters()
    missing = [n for n in names if n not in have]
    if missing:
        raise MissingCapability(
            "ffmpeg is missing filters: " + ", ".join(missing) +
            "\nRebuild with --enable-libvidstab --enable-libfftw3 as needed."
        )
