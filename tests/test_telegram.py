from pathlib import Path

import pytest

from restore import telegram
from restore.probe import MediaInfo


def _info(name: str, w: int, h: int, fps: float = 30.0, dur: float = 10.0) -> MediaInfo:
    return MediaInfo(Path(name), w, h, fps, dur, "h264", True)


def test_link_parsing():
    assert telegram.parse_link("https://t.me/somechan/1234") == ("somechan", 1234)
    assert telegram.parse_link("https://t.me/c/1823456789/42") == (-1001823456789, 42)
    assert telegram.parse_link("https://t.me/c/3780293595/650/654") == (-1003780293595, 654)


def test_rejects_non_links():
    with pytest.raises(ValueError):
        telegram.parse_link("clip.mp4")


def test_fingerprints_video_note():
    assert telegram.looks_like_telegram(_info("VID_20240101_x.mp4", 240, 240), 9000)


def test_plain_file_not_flagged():
    assert not telegram.looks_like_telegram(_info("cam.mp4", 1920, 1080), 40_000_000)


def test_video_note_detection():
    assert telegram.is_video_note(_info("x.mp4", 240, 240))
    assert not telegram.is_video_note(_info("y.mp4", 1920, 1080))


def test_sources_resolve_local_file(tmp_path: Path):
    from restore import sources

    local_file = tmp_path / "sample.mp4"
    local_file.write_bytes(b"data")
    resolved = sources.resolve(str(local_file), tmp_path)
    assert resolved == local_file

    with pytest.raises(FileNotFoundError):
        sources.resolve(str(tmp_path / "non_existent.mp4"), tmp_path)


def test_sources_resolve_telegram_link(tmp_path: Path):
    from unittest.mock import patch
    from restore import sources

    dest = tmp_path / "somechan_1234.mp4"
    with patch("restore.telegram.fetch_public", return_value=dest) as mock_fetch:
        res = sources.resolve("https://t.me/somechan/1234", tmp_path)
        assert res == dest
        mock_fetch.assert_called_once_with("somechan", 1234, dest)
