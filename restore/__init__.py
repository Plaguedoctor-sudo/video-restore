"""video-restore: Classical video restoration tool."""

import os
import sys
from pathlib import Path

__version__ = "0.1.0"

# Ensure ffmpeg/ffprobe binaries in virtualenv or local bin are in PATH
venv_bin = str(Path(sys.executable).parent)
if venv_bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")
