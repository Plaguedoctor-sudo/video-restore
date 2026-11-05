from restore.analyze import DefectProfile
from restore.plan import build_plan

CLEAN = DefectProfile(0, 0, 0, 0, 0, 0, 0, 0)


def test_clean_clip_gets_no_heavy_stages():
    plan = build_plan(CLEAN, "standard")
    assert not any("nlmeans" in f for f in plan.filters)
    assert not plan.stabilize


def test_order_denoise_before_sharpen():
    p = DefectProfile(0, 0.9, 0.5, 0, 0, 0, 0, 0.9)
    plan = build_plan(p, "standard")
    idx = {k: next(i for i, f in enumerate(plan.filters) if k in f)
           for k in ("nlmeans", "deblock", "cas")}
    assert idx["nlmeans"] < idx["deblock"] < idx["cas"]


def test_sharpen_capped():
    p = DefectProfile(0, 0.5, 0, 0, 0, 0, 0, 1.0)
    plan = build_plan(p, "max", sharpen_mult=2.0)
    cas = next(f for f in plan.filters if f.startswith("cas"))
    assert float(cas.split("=")[-1]) <= 0.6


def test_chroma_threshold_double_luma():
    p = DefectProfile(0, 0.8, 0, 0, 0, 0, 0, 0)
    f = next(x for x in build_plan(p, "standard").filters if x.startswith("atadenoise"))
    luma = float(f.split("0a=")[1].split(":")[0])
    chroma = float(f.split("1a=")[1].split(":")[0])
    assert abs(chroma - luma * 2) < 1e-6


def test_no_resolution_change():
    p = DefectProfile(1, 1, 1, 1, 1, 1, 1, 1)
    assert "scale=" not in build_plan(p, "max").graph()


def test_telegram_preset_adds_deband():
    p = DefectProfile(0, 0.6, 0.5, 0, 0, 0, 0, 0.5)
    plan = build_plan(p, "telegram", telegram=True)
    assert any(f.startswith("deband") for f in plan.filters)


def test_telegram_uses_strongest_deblock():
    p = DefectProfile(0, 0.5, 0.6, 0, 0, 0, 0, 0)
    plan = build_plan(p, "telegram", telegram=True)
    assert any("strongest" in f for f in plan.filters)


def test_telegram_keeps_nlmeans_low():
    p = DefectProfile(0, 0.9, 0, 0, 0, 0, 0, 0)
    plan = build_plan(p, "telegram", telegram=True)
    s = next(f for f in plan.filters if f.startswith("nlmeans"))
    assert int(s.split("s=")[-1].split(":")[0]) <= 7


def test_video_note_disables_stabilization():
    p = DefectProfile(0.9, 0.4, 0.4, 0, 0, 0, 0, 0.4)
    assert not build_plan(p, "telegram", telegram=True, video_note=True).stabilize
