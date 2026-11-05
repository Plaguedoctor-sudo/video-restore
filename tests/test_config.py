from pathlib import Path
from restore.config import Config, Encoder, Preset


def test_config_defaults():
    cfg = Config(source=Path("in.mp4"), output=Path("out.mp4"))
    assert cfg.preset == Preset.STANDARD
    assert cfg.encoder == Encoder.QSV
    assert cfg.crf == 19
    assert cfg.threads == 2
    assert not cfg.force


def test_config_with_override():
    cfg = Config(source=Path("in.mp4"), output=Path("out.mp4"))
    cfg2 = cfg.with_(preset=Preset.MAX, crf=16, force=True)
    assert cfg2.preset == Preset.MAX
    assert cfg2.crf == 16
    assert cfg2.force is True
    # Original is unchanged (immutable)
    assert cfg.preset == Preset.STANDARD
