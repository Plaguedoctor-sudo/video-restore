# Video-Restore - Forensic Video Clarity and Enhancement Engine

> [!IMPORTANT]
> Development status: Under active development.

Video-Restore is an open-source command-line tool and local web application that enhances poorly recorded video files. It stabilizes camera shake, reduces sensor noise, removes compression blocking artifacts, balances exposure and color casts, and sharpens text and edge boundaries on commodity CPUs without cloud dependencies or heavy neural models.

---

## What it can do

- **Automated defect profiling**:
  - Analyzes video inputs to detect and quantify camera shake, sensor grain, compression blocking, luminance flicker, color temperature imbalance, and audio background hiss.
  - Generates comprehensive defect diagnostic scores to calibrate downstream processing.

- **Scientific multi-stage filter pipeline**:
  - Enforces a deterministic filter order:
    1. *Camera stabilization*: Two-pass motion vector stabilization powered by `libvidstab`.
    2. *Temporal and spatial denoising*: Sensor grain suppression via adaptive spatio-temporal algorithms (`hqdn3d` and `nlmeans`).
    3. *Deblocking*: Suppresses macroblock boundaries and MPEG/H.264 compression artifacts.
    4. *Tonal and color calibration*: Fixes underexposure, overexposure, and color temperature casts through dynamic histogram equalization.
    5. *Edge and text sharpening*: Unsharp masking tuned to maximize legibility of blackboard writing, slides, and printed documents.

- **Screen re-record recovery mode (`--screen`)**:
  - Specifically engineered for camera recordings of projector screens, TV monitors, or laptops.
  - Suppresses moire interference patterns and rainbow banding.
  - Neutralizes rolling shutter scan lines and display refresh flicker.
  - Corrects keystone perspective distortion and boosts high-contrast text edges.

- **Multi-core fast mode (`--fast`)**:
  - Automatically downscales intermediate resolution to 720p and allocates all available CPU cores.
  - Delivers 20 to 30+ frames per second processing speeds on commodity hardware.

- **Telegram video integration**:
  - Directly ingests and restores videos from Telegram public posts, private channels, and forum topics with saving restrictions.

- **Local web user interface**:
  - Local browser interface (`http://localhost:8800`) to upload clips, view defect diagnostic radars, and download processed files.

- **Lightweight CPU execution**:
  - Runs entirely on standard multi-core CPUs using FFmpeg and Python; requires no external cloud APIs, expensive GPUs, or large neural network weights.

---

## What it cannot do

- **Does not perform generative AI hallucination**: Video-Restore is a signal-processing and forensic enhancement pipeline; it does not synthesize artificial imagery or fabricate details that were never captured by the camera sensor.
- **Cannot recover clipped highlight or shadow detail**: Pixels that are 100% clipped to white (severe overexposure) or completely clipped to zero black (complete underexposure) contain no recoverable photometric data.
- **Cannot compensate for extreme 360-degree rotational spin**: Stabilization operates via 2D affine transformations; extreme rotational movements or rapid tumbling will introduce excessive frame border cropping.
- **Does not perform real-time 4K 60fps streaming filtering on low-end hardware**: Processing 4K resolution requires substantial computation and operates as an asynchronous batch render rather than a zero-latency live camera filter.
- **Does not remove physical objects occluding the lens**: Static obstructions (e.g., fingers over the lens, water droplets on the protective glass) cannot be removed without generative inpainting.

---

## Installation and prerequisites

### Requirements
- Linux, macOS, or Windows (WSL2)
- Python 3.10+
- FFmpeg and FFprobe compiled with `libvidstab`

```bash
# Clone the repository
git clone https://github.com/Plaguedoctor-sudo/video-restore.git
cd video-restore

# Install dependencies and test
./install.sh
make test
```

---

## Quick start

### 1. Basic restoration
```bash
# Analyze defect profile
restore analyze clip.mp4

# Run restoration with standard preset
restore run clip.mp4 -o fixed.mp4 --preset standard
```

### 2. Fast multi-core screen mode (lecture slides / monitors)
```bash
restore run recording.mp4 -o clear_lecture.mp4 --screen --fast
```

### 3. Telegram videos
```bash
# Public post
restore run "https://t.me/channel/1234" -o fixed.mp4

# Private channel or forum topic
restore run "https://t.me/c/1234567890/50/654" -o fixed.mp4 --screen --fast
```

### 4. Local web UI
```bash
make web
```
Open http://localhost:8800 in your browser.

---

## CLI options

| Flag | Description |
| :--- | :--- |
| `--screen` | Enables camera-recorded screen recovery (moire suppression, flicker removal, slide tonal balance) |
| `--fast` | Multi-core acceleration mode (auto-scales to 720p, utilizes all CPU cores) |
| `--preset` | Restoration preset: `preview`, `fast`, `standard`, `max`, or `telegram` |
| `--height <px>` | Downscale height (e.g. `720`) to accelerate rendering on low-power CPUs |
| `--threads <n>` | Set explicit CPU worker thread count |
| `--start` / `--duration` | Process a short preview slice (in seconds) |

---

## License

This project is licensed under the [MIT License](LICENSE).
