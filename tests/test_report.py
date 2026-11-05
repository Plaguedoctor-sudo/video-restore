from unittest.mock import patch
from pathlib import Path
from restore.report import compare, _score


def test_compare_formatting():
    with patch("restore.report._score") as mock_score:
        mock_score.side_effect = lambda src, out, filt: 0.95 if filt == "ssim" else 92.5
        rep = compare(Path("in.mp4"), Path("out.mp4"))
        assert "SSIM: 0.9500" in rep
        assert "VMAF: 92.50" in rep
        assert "Verdict: PASS" in rep


def test_compare_review_when_low():
    with patch("restore.report._score") as mock_score:
        mock_score.side_effect = lambda src, out, filt: 0.85 if filt == "ssim" else 70.0
        rep = compare(Path("in.mp4"), Path("out.mp4"))
        assert "Verdict: REVIEW" in rep
