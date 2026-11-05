#!/usr/bin/env bash
set -euo pipefail

INPUT="${1:-lecture_raw.mp4}"
OUTPUT="${2:-lecture_clear.mp4}"

echo "Restoring $INPUT -> $OUTPUT using optimized fast mode..."
./.venv/bin/python -m restore.cli run "$INPUT" -o "$OUTPUT" --screen --fast --force

echo ""
echo "Done! Restored video written to $OUTPUT"
