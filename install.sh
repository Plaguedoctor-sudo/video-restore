#!/usr/bin/env bash
set -euo pipefail
for f in ffmpeg ffprobe; do
  command -v "$f" >/dev/null || { echo "missing $f"; exit 1; }
done
ffmpeg -hide_banner -h filter=vidstabdetect 2>&1 | grep -q vidstabdetect \
  || { echo "ffmpeg lacks libvidstab"; exit 1; }
python3 -m venv .venv && . .venv/bin/activate
pip install -e . -r requirements.txt
python -c "import cv2; from restore.capabilities import require; require('nlmeans','cas','deblock')"
echo "ok — run 'make test'"
