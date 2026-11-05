from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from .probe import MediaInfo

LINK_RE = re.compile(
    r"^(?:https?://)?t\.me/(?:s/)?(?:c/(?P<private_id>\d+)|(?P<channel>[A-Za-z0-9_]{4,}))(?:/(?P<topic>\d+))?/(?P<msg>\d+)/?$"
)
NAME_RE = re.compile(
    r"(telegram-cloud|^VID_\d{8}_|^video\.mp4$|-video\.mp4$|^tgvideo)", re.I
)
# Telegram's resolution ladder, plus video notes
LADDER = {
    (240, 240), (320, 240), (320, 568), (384, 384), (480, 270), (480, 854),
    (640, 360), (720, 404), (854, 480), (960, 540), (1280, 720),
}


def parse_link(url: str) -> tuple[str | int, int]:
    m = LINK_RE.match(url.strip())
    if not m:
        raise ValueError(f"not a t.me post link: {url}")
    if m.group("private_id"):
        return int(f"-100{m.group('private_id')}"), int(m.group("msg"))
    return m.group("channel"), int(m.group("msg"))


def is_link(ref: str) -> bool:
    return bool(LINK_RE.match(ref.strip()))


def fetch_public(channel: str | int, msg_id: int, dest: Path) -> Path:
    """Resolve a public post's CDN mp4 without auth. Raises on private posts."""
    if isinstance(channel, int):
        raise RuntimeError("private channel links require authentication")
    url = f"https://t.me/{channel}/{msg_id}?embed=1&mode=tme"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")

    if "tgme_widget_message_video" not in html:
        raise RuntimeError(
            "no video in that post (private channel, photo, or not a video)"
        )
    m = re.search(r'<video[^>]+src="(https://[^"]+?\.mp4[^"]*)"', html)
    if not m:
        raise RuntimeError("video element present but no direct mp4 source")

    dest.parent.mkdir(parents=True, exist_ok=True)
    req2 = urllib.request.Request(m.group(1), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req2, timeout=120) as r, dest.open("wb") as fh:
        while chunk := r.read(1 << 16):
            fh.write(chunk)
    return dest


def fetch_authed(link: str, dest: Path, api_id: int, api_hash: str,
                 session: str) -> Path:
    """Private-channel download via Telethon. Optional dependency."""
    try:
        from telethon.sync import TelegramClient
    except ImportError as exc:
        raise RuntimeError("pip install telethon") from exc

    channel, msg_id = parse_link(link)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TelegramClient(session, api_id, api_hash) as client:
        msg = client.get_messages(channel, ids=msg_id)
        if msg is None or (msg.video is None and msg.document is None and msg.media is None):
            raise RuntimeError("no video in that message")
        downloaded = client.download_media(msg, file=str(dest))
        if not downloaded:
            raise RuntimeError("failed to download media from message")
    return dest


def bits_per_pixel(info: MediaInfo, size_bytes: int) -> float:
    pixels = info.width * info.height * max(info.fps, 1) * max(info.duration, 0.1)
    return (size_bytes * 8) / pixels


def looks_like_telegram(info: MediaInfo, size_bytes: int) -> bool:
    """Fingerprint a re-encoded Telegram video. Needs 2 of 3 signals."""
    score = 0
    if NAME_RE.search(info.path.name):
        score += 1
    if (info.width, info.height) in LADDER:
        score += 1
    if bits_per_pixel(info, size_bytes) < 0.05:
        score += 1
    return score >= 2


def is_video_note(info: MediaInfo) -> bool:
    return info.width == info.height and info.width <= 384
