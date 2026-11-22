import cv2
import numpy as np

from restore.analyze import DefectProfile
from restore.plan import build_plan
from restore.screen import Quad, _largest_quad, parse_crop, parse_quad


def test_quad_filter_shape():
    q = Quad(((10, 20), (300, 20), (300, 200), (10, 200)))
    f = q.as_filter()
    assert f.startswith("perspective=") and "sense=source" in f
    # ffmpeg perspective requires x2,y2 to be BL and x3,y3 to be BR
    assert "x2=10:y2=200" in f
    assert "x3=300:y3=200" in f


def test_bbox():
    q = Quad(((10, 20), (300, 20), (300, 200), (10, 200)))
    assert q.bbox() == (10, 20, 290, 180)


def test_parse_quad_roundtrip():
    q = parse_quad("0:0,100:0,100:50,0:50")
    assert q.pts[2] == (100, 50)


def test_parse_crop():
    assert parse_crop("4,8,640,360") == "crop=640:360:4:8"


def test_screen_plan_geometry_and_filters():
    p = DefectProfile(0, 0.2, 0.1, 0, 0, 0, 0, 0.8)
    geom = "perspective=x0=10:y0=20:x1=300:y1=20:x2=300:y2=200:x3=10:y3=200:sense=source:eval=init"
    crop = "crop=290:180:10:20"
    plan = build_plan(p, "standard", geometry=geom, crop=crop, moire=0.35, bands=0.45)

    # Geometry first
    assert plan.filters[0] == geom
    assert plan.filters[1] == crop

    # Moire suppression
    assert any("smartblur" in f for f in plan.filters)

    # Rolling bands removal
    assert any("tmix" in f for f in plan.filters)

    # Cas capped at 0.4 in screen mode
    cas = next(f for f in plan.filters if f.startswith("cas"))
    strength = float(cas.split("=")[-1])
    assert strength <= 0.40


def test_largest_quad_detection():
    # Synthetic dark frame with a bright convex rectangle > 25% area
    img = np.zeros((400, 600, 3), dtype=np.uint8)
    cv2.rectangle(img, (100, 50), (500, 350), (255, 255, 255), -1)

    quad = _largest_quad(img)
    assert quad is not None
    assert len(quad) == 4


def test_moire_score_with_pattern():
    from pathlib import Path
    from unittest.mock import patch
    from restore.probe import MediaInfo
    from restore.screen import moire_score

    info = MediaInfo(Path("test.mp4"), 320, 240, 30.0, 10.0, "h264", False)
    # Synthetic high-frequency striped pattern (moiré / interference)
    x = np.arange(320)
    y = np.arange(240)
    xx, yy = np.meshgrid(x, y)
    pattern = (np.sin(xx * 0.8) * np.cos(yy * 0.8) * 127 + 128).astype(np.uint8)
    bgr_pattern = cv2.cvtColor(pattern, cv2.COLOR_GRAY2BGR)

    with patch("restore.screen._frame_at", return_value=bgr_pattern):
        score = moire_score(info)
        assert score > 0.15
