from __future__ import annotations

import os
from pathlib import Path

import typer

from . import sources, telegram
from .analyze import analyze
from .config import Config, Encoder, Preset
from .pipeline import FFmpegError, render
from .plan import build_plan
from .probe import probe
from .report import compare

app = typer.Typer(add_completion=False, help="Restore badly-recorded video.")


def _guard(cfg: Config) -> None:
    if not cfg.source.exists():
        raise typer.BadParameter(f"no such file: {cfg.source}")
    if cfg.output.exists() and not cfg.force:
        raise typer.BadParameter(f"{cfg.output} exists; pass --force")


@app.command("analyze")
def analyze_cmd(path: Path) -> None:
    """Print a defect profile for a clip."""
    info = probe(path)
    print(f"{info.width}x{info.height} @ {info.fps:.2f}fps, {info.duration:.1f}s")
    print(analyze(info).summary())


@app.command()
def fetch(link: str, output: Path = typer.Option(..., "-o"),
          api_id: int | None = None, api_hash: str | None = None) -> None:
    """Download a video from a t.me post (public, or authenticated)."""
    try:
        path = sources.resolve(link, output.parent, api_id=api_id,
                               api_hash=api_hash)
    except Exception as exc:
        typer.secho(f"failed: {exc}", fg="red")
        raise typer.Exit(1)
    if path != output:
        path.replace(output)
    typer.secho(f"wrote {output}", fg="green")


@app.command()
def run(
    source: str,
    output: Path = typer.Option(..., "-o"),
    preset: Preset = Preset.STANDARD,
    encoder: Encoder = Encoder.QSV,
    denoise: float = 1.0,
    sharpen: float = 1.0,
    tonal: bool = True,
    audio_denoise: bool | None = None,
    start: float | None = None,
    duration: float | None = None,
    api_id: int | None = None,
    api_hash: str | None = None,
    screen: bool = typer.Option(False, "--screen", help="camera-recorded screen"),
    quad: str | None = typer.Option(None, help="x0:y0,x1:y1,x2:y2,x3:y3"),
    crop: str | None = typer.Option(None, help="x,y,w,h"),
    scale_height: int | None = typer.Option(None, "--height", help="Downscale height (e.g. 720)"),
    threads: int | None = typer.Option(None, "--threads", help="Number of worker threads"),
    fast: bool = typer.Option(False, "--fast", help="Optimized fast mode for CPU rendering"),
    moire: float | None = None,
    force: bool = False,
) -> None:
    """Analyze, plan, and render. Accepts a path or a t.me link."""
    work = output.parent
    try:
        src = sources.resolve(source, work, api_id=api_id, api_hash=api_hash)
    except Exception as exc:
        typer.secho(f"failed: {exc}", fg="red")
        raise typer.Exit(1)

    info = probe(src)
    size = src.stat().st_size
    tg = telegram.looks_like_telegram(info, size)
    note = telegram.is_video_note(info)

    active_threads = threads or os.cpu_count() or 4
    if fast:
        preset = Preset.FAST if preset is Preset.STANDARD else preset
        if encoder is Encoder.QSV:
            from .capabilities import has_qsv
            if not has_qsv():
                encoder = Encoder.X264
        if scale_height is None and info.height > 720:
            scale_height = 720
        typer.secho("  fast mode enabled -> multi-core x264/fast preset", fg="green")
    elif tg:
        preset = Preset.TELEGRAM if preset is Preset.STANDARD else preset
        typer.secho("  detected Telegram re-encode -> telegram preset", fg="yellow")

    if note:
        typer.secho("  video note", fg="yellow")

    geometry = cropf = None
    if screen:
        from . import screen as scr
        if not fast and preset is Preset.STANDARD:
            preset = Preset.TELEGRAM
        if quad:
            q = scr.parse_quad(quad)
        elif crop:
            q = None
        else:
            q = scr.detect(info)
            if q is None:
                typer.secho("  no screen detected; continuing without geometry",
                            fg="yellow")
        if q is not None:
            geometry = q.as_filter()
            cropf = f"crop={q.bbox()[2]}:{q.bbox()[3]}:{q.bbox()[0]}:{q.bbox()[1]}"
        elif crop:
            cropf = scr.parse_crop(crop)
        m = moire if moire is not None else scr.moire_score(info)
        b = scr.band_score(info)
        typer.secho(f"  screen mode: moire {m:.2f}, bands {b:.2f}", fg="yellow")
    else:
        m, b = 0.0, 0.0

    cfg = Config(source=src, output=output, preset=preset, encoder=encoder,
                 denoise_strength=denoise, sharpen=sharpen, tonal=tonal,
                 audio_denoise=audio_denoise if audio_denoise is not None else tg,
                 threads=active_threads,
                 sample_start=start, sample_duration=duration, force=force,
                 screen_mode=screen, quad=quad, crop=crop, moire=m,
                 scale_height=scale_height)
    _guard(cfg)

    profile = analyze(info)
    print("Defects:")
    print(profile.summary())
    plan = build_plan(profile, preset.value, denoise, sharpen, tonal,
                      telegram=tg, video_note=note,
                      geometry=geometry, crop=cropf, moire=m, bands=b)
    print(f"Graph: {plan.graph()}")
    try:
        render(cfg, plan, info)
    except (FFmpegError, RuntimeError) as exc:
        typer.secho(f"failed: {exc}", fg="red")
        raise typer.Exit(1)
    typer.secho(f"wrote {output}", fg="green")


@app.command()
def report(source: Path, output: Path) -> None:
    """Compare restored output against the source."""
    print(compare(source, output))


if __name__ == "__main__":
    app()
