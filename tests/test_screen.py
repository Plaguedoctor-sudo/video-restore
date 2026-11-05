import cv2
import numpy as np

from restore.analyze import DefectProfile
from restore.plan import build_plan
from restore.screen import Quad, _largest_quad, parse_crop, parse_quad


def test_quad_filter_shape():
    q = Quad(((10, 20), (300, 20), (300, 200), (10, 200)))
    f = q.as_filter()
    assert f.startswith("perspective=") and "sense=source" in f


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
