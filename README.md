# video-restore 🎬✨

An open-source CLI and local web application that makes poorly recorded video **legible and clear**:
removes camera shake, sensor noise, compression blocking, fixes exposure and color cast, and sharpens text and edges.

Designed to run efficiently on commodity CPUs (no heavy ML models, GPUs, or external cloud APIs required).

---

## Features

- 🔬 **Automated Defect Profiling**: Inspects input video for shake, sensor grain, flicker, color casts, underexposure, and hiss.
- 📐 **Scientific Filter Pipeline**: Enforces load-bearing filter order (*Stabilize → Denoise → Deblock → Tonal Calibration → Edge Sharpening*).
- 📺 **Screen Re-Record Recovery (`--screen`)**: Specially tuned for camera/phone recordings of TV screens, monitors, or lecture slides. Corrects keystone perspective, neutralizes moiré rainbow patterns, suppresses rolling scan lines, and maximizes blackboard/slide text legibility.
- ⚡ **Multi-Core Fast Mode (`--fast`)**: Auto-scales resolution, engages multi-core CPU threads, and accelerates throughput to 20–30+ fps.
- ✈️ **Telegram Integration**: Direct download and restoration of Telegram videos (public posts, private channels, and forum topics with saving restrictions).
- 🌐 **Web Interface**: Clean, local browser UI to upload clips, visualize defect scores, and download restored videos.

---

## Installation

### Prerequisites
- Linux / macOS / Windows (WSL)
- Python 3.10+
- FFmpeg and FFprobe with `libvidstab`

```bash
git clone https://github.com/<your-username>/video-restore.git
cd video-restore
./install.sh
make test
```

---

## Quick Start

### 1. Basic Restoration
```bash
# Analyze defect profile
restore analyze clip.mp4

# Run restoration with standard preset
restore run clip.mp4 -o fixed.mp4 --preset standard
```

### 2. Fast Multi-Core Screen Mode (Lectures / Classes recorded from TVs)
```bash
restore run recording.mp4 -o clear_lecture.mp4 --screen --fast
```

### 3. Telegram Videos
```bash
# Public post
restore run "https://t.me/channel/1234" -o fixed.mp4

# Forum topic message or private channel
restore run "https://t.me/c/1234567890/50/654" -o fixed.mp4 --screen --fast
```

*To configure Telegram API credentials for private/restricted channels, copy `.env.example` to `.env` and fill in your `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from [my.telegram.org](https://my.telegram.org).*

### 4. Local Web UI
```bash
make web
```
Open [http://localhost:8800](http://localhost:8800) in your browser.

---

## CLI Options

| Flag | Description |
| :--- | :--- |
| `--screen` | Enables camera-recorded screen recovery (moiré suppression, flicker removal, slide tonal balance) |
| `--fast` | Multi-core acceleration mode (auto-scales to 720p, utilizes all CPU cores) |
| `--preset` | Restoration preset: `preview`, `fast`, `standard`, `max`, or `telegram` |
| `--height <px>` | Downscale height (e.g. `720`) to accelerate rendering on low-power CPUs |
| `--threads <n>` | Set explicit CPU worker thread count |
| `--start` / `--duration` | Process a short preview slice (in seconds) |

---

## License

This project is licensed under the [MIT License](LICENSE).
