# AGENTS.md — video-restore

## What this is
A CLI + local web tool that makes badly-recorded video *legible*: removes shake,
noise, blocking, fixes exposure and colour cast, sharpens last.

## Hard constraints — do not violate
1. **Never change resolution.** No `scale=` to a larger size. Native dimensions only
   (final `format=yuv420p,setsar=1` is allowed). Exception: screen-recording mode (see below).
2. **No ML models.** No Real-ESRGAN, no ONNX, no OpenVINO. Classical ffmpeg filters only.
   Target hardware is an Intel i3-8100 + UHD 630 iGPU with no discrete GPU.
3. **Filter order is load-bearing.** Stabilize -> denoise -> deblock -> tonal -> sharpen.
   Sharpen before denoise produces permanent speckle. Denoise before stabilize smears
   across the shake.
4. **Never sharpen a noisy clip above cas strength 0.6.**
5. **Stabilization is two-pass and always first.** Use libvidstab, not `deshake`.
6. Chroma denoise thresholds run 2x luma thresholds. Chroma noise is blotchy and
   carries almost no detail.
7. Offline only. Do not add a real-time capture path.
8. Every stage is skippable. A clip with no shake must not get a stabilize pass.

## Conventions
- Python 3.10+, type hints everywhere, no `Any` in public signatures.
- Pure functions in `analyze.py` and `plan.py` — no subprocess, no I/O. These are unit-tested.
- All ffmpeg invocation goes through `pipeline.py`. Nothing else shells out.
- Config is a frozen dataclass. Presets are data, not branches.
- Fail loudly with a specific message if a required ffmpeg filter is missing.

## Definition of done
- `make test` passes.
- `restore analyze clip.mp4` prints a defect profile.
- `restore run clip.mp4 -o out.mp4 --preset standard` completes and output is playable.
- `restore report clip.mp4 out.mp4` emits VMAF, SSIM and a verdict.
- Output dimensions equal input dimensions.

## Pitfalls that have bitten before
- `normalize` with `independence=1` wrecks white balance. Keep it 0.
- `vidstabtransform` without `optzoom` leaves black borders.
- `nlmeans` on a moving shot at s>12 turns faces to wax.
- `-global_quality` is a QSV-only flag; it is not `-crf`.

## Telegram specifics
- Telegram re-encodes uploads sent as *video*; files sent as *document* are untouched.
  Only the re-encoded case has the artifact signature.
- Signature: waxy smooth surfaces + hard block edges, mushy chroma, gradient banding,
  bitrate under ~0.05 bits/pixel. Do NOT treat it as generic noise.
- Telegram clips get a `deband` stage. The general pipeline has none.
- Telegram clips get chroma sharpening (non-zero on the last two `unsharp` fields).
  General clips get luma-only sharpening.
- `nlmeans` stays LOW on Telegram (s=5-7). The surfaces are already smooth; s>9
  destroys what little texture survives.
- `deblock=strongest` is correct here, not `strong`.
- Video notes (1:1, <= 384px) are the worst case. Crop is baked in — do not touch geometry.
- Live streams and group video calls are WebRTC. Out of scope; say so.

## Rule 1 exception
Screen-recording mode DOES change dimensions: it perspective-corrects and crops to
the screen region. That is geometry recovery, not upscaling. The crop never
interpolates above native pixel density.

## Screen re-record specifics
- The video is a camera pointed at a monitor. Defects: keystone, moiré, rolling
  bands, silhouette occlusion, blown screen highlights, room-light white balance.
- **Geometry first.** Perspective + crop run before every other filter.
- **Moiré suppression runs before sharpening.** Sharpening first bakes the
  interference pattern into hard edges.
- After cropping, tonal correction operates on the slide only. This is the point —
  `normalize` on the full frame measures the room, not the content.
- Cap `cas` at 0.4 in screen mode. Text edges are already high-contrast.
- Rolling bands: `deflicker` + light `tmix`. Safe here because lecture slides change
  slowly; do not use `tmix` on fast-motion clips.
- If quad detection fails, warn and continue without geometry. Never abort.
