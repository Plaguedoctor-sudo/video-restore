# SPEC

## Goal
Input: video recorded by a poor camera (phone in low light, dashcam, CCTV, old
handycam). Output: same resolution, same duration, same frame rate, visibly more
legible.

## Non-goals
Resolution upscaling. Frame-rate interpolation. Real-time. Content generation.

## Defects handled
| ID | Defect | Detector | Stage |
|----|--------|----------|-------|
| D1 | Handheld shake | vidstab transform variance | stabilize (2-pass) |
| D2 | Luma/chroma sensor noise | temporal delta + high-freq energy | denoise |
| D3 | Compression blocking | 8px-boundary gradient ratio | deblock |
| D4 | Luminance flicker | YAVG variance across frames | deflicker |
| D5 | Underexposure / washout | YAVG, clipped-pixel fractions | normalize + eq |
| D6 | Colour cast | per-channel mean divergence | colorbalance |
| D7 | Softness | inverse Laplacian variance | cas + unsharp |
| D8 | Hiss / hum | spectral floor | afftdn |

## Presets
- `preview`  — analysis-driven, halved denoise strength, QSV encode. ~10-20 fps.
- `standard` — full strength. ~4-8 fps.
- `max`      — nlmeans + fftdnoiz stacked, x265 CRF 19. ~1-2 fps.

## Acceptance
VMAF of output >= source VMAF against a clean reference where available; SSIM must
not drop. Manual check: sign text and faces sharper at 100% crop, no wax, no halos.

## Safety
Refuse to overwrite input without `--force`. Always write to a temp file and rename
on success, so a killed job never leaves a truncated output.

## Telegram support
| ID | Defect | Detector | Stage |
|----|--------|----------|-------|
| T1 | Encoder deblock mush | bitrate < 0.05 bpp + 8px edge ratio | deblock strongest |
| T2 | Chroma destruction | 4:2:0 + low bpp | chroma-weighted nlmeans, chroma unsharp |
| T3 | Gradient banding | YAVG histogram gaps | deband |
| T4 | AAC 64k mono hiss | codec + bitrate | afftdn |

### Source resolution
- `t.me/<channel>/<id>` public post -> scrape embed page for CDN mp4, no auth.
- Private / restricted -> Telethon, needs api_id + api_hash + session file.
- Local file -> fingerprint heuristics decide if the Telegram preset auto-applies.

### Acceptance
Chroma noise visibly reduced, no banding steps in sky/walls, block edges gone,
faces not waxy at 100% crop. Never fewer than the source's pixels.

## Screen re-record mode
| ID | Defect | Detector | Stage |
|----|--------|----------|-------|
| S1 | Keystone / off-axis panel | largest-quad contour, area > 25% | perspective + crop |
| S2 | Panel moiré | high-freq band energy | smartblur + nlmeans |
| S3 | Rolling refresh bands | per-row luma variance over time | deflicker + tmix |
| S4 | Silhouette / room pollution | removed by S1 crop | tonal scoped to crop |

Quad detection samples 5 keyframes and takes the component-wise median, so one bad
frame can't swing the correction. `--quad` and `--crop` override it manually.

### Acceptance
Slide text readable at 100% with no rainbow fringing, banding gone, no ghosting on
slide transitions. Output aspect within 10% of 16:9 or 4:3.
