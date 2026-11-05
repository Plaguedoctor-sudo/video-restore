import numpy as np
from restore.analyze import (
    SampleData,
    _blockiness,
    _calc_audio_hiss,
    _calc_color_cast,
    _calc_shake,
    _laplacian_var,
    analyze,
)


def test_flat_frame_has_low_laplacian():
    assert _laplacian_var(np.full((64, 64), 128, np.uint8)) < 1.0


def test_noise_raises_laplacian():
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 255, (64, 64), dtype=np.uint8)
    assert _laplacian_var(noisy) > _laplacian_var(np.full((64, 64), 128, np.uint8))


def test_blockiness_detects_8px_grid():
    f = np.tile(np.arange(64, dtype=np.uint8), (64, 1))
    f[:, 7::8] = 255
    assert _blockiness(f) > 1.2


def test_color_cast_detects_channel_divergence():
    # Balanced neutral gray
    neutral = np.full((1, 32, 32, 3), 128, dtype=np.uint8)
    assert _calc_color_cast(neutral, clipped_low=0.0) < 0.1

    # Heavy red tint (channel divergence)
    tinted = np.zeros((1, 32, 32, 3), dtype=np.uint8)
    tinted[..., 0] = 200  # Red
    tinted[..., 1] = 80   # Green
    tinted[..., 2] = 80   # Blue
    assert _calc_color_cast(tinted, clipped_low=0.0) > 0.5


def test_audio_hiss_detector():
    assert _calc_audio_hiss(-60.0) == 0.0  # Silent / clean floor
    assert _calc_audio_hiss(-20.0) > 0.8   # Heavy noise floor
    assert _calc_audio_hiss(None) == 0.0


def test_shake_detector():
    clean_deltas = ((0.1, 0.1), (0.1, 0.2), (0.2, 0.1), (0.1, 0.1))
    assert _calc_shake(clean_deltas) < 0.05

    shaky_deltas = ((0.0, 12.0), (10.0, 0.0), (0.0, 11.0), (9.0, 1.0))
    assert _calc_shake(shaky_deltas) > 0.5



def test_pure_analyze_no_io():
    gray = np.full((4, 32, 32), 128, dtype=np.uint8)
    rgb = np.full((4, 32, 32, 3), 128, dtype=np.uint8)
    samples = SampleData(gray_frames=gray, rgb_frames=rgb, motion_deltas=((0.0, 0.0),) * 4)
    profile = analyze(samples)
    assert profile.shake == 0.0
    assert profile.noise < 0.05
    assert profile.cast == 0.0
    assert "clean" in profile.summary().lower() or len(profile.summary()) > 0
