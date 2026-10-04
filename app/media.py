"""Local media preparation before attaching files to Gemini."""
from __future__ import annotations

import logging
import shutil
import struct
import subprocess
from pathlib import Path

from .models import PROJECT_ROOT, ValidationError

log = logging.getLogger(__name__)

# VERIFIED: Gemini "can reference videos up to 10s"; longer videos open a trim dialog that
# blocks the prompt box, so they are trimmed locally first.
MAX_REFERENCE_SECONDS = 10.0
CACHE_DIR = PROJECT_ROOT / "output" / ".trimmed"


def mp4_duration(path: Path) -> float | None:
    """Duration in seconds from the MP4/MOV 'mvhd' box, or None if it cannot be read."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    i = data.find(b"mvhd")
    if i < 4:
        return None
    version = data[i + 4]
    try:
        if version == 1:
            timescale, duration = struct.unpack(">IQ", data[i + 24:i + 36])
        else:
            timescale, duration = struct.unpack(">II", data[i + 16:i + 24])
    except struct.error:
        return None
    return duration / timescale if timescale else None


def prepare_reference_video(path: Path, start: float = 0.0,
                            max_seconds: float = MAX_REFERENCE_SECONDS) -> Path:
    """Return a video Gemini accepts without its trim dialog: the original if it is short
    enough, otherwise a max_seconds clip starting at `start` (cached in output/.trimmed/)."""
    duration = mp4_duration(path)
    if duration is not None and duration <= max_seconds + 0.05 and start == 0:
        return path
    if duration is not None and start >= duration:
        raise ValidationError(f"--video-start {start}s is past the end of {path.name} ({duration:.1f}s)")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"{path.stem}-{start:g}s-{max_seconds:g}s.mp4"
    if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    log.info("Trimming %s (%.1fs) to %gs from %gs...", path.name, duration or 0, max_seconds, start)
    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(path), "-t", str(max_seconds),
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", str(out)]
    elif shutil.which("avconvert"):  # built into macOS
        cmd = ["avconvert", "--source", str(path), "--preset", "PresetHighestQuality", "--output", str(out),
               "--start", str(start), "--duration", str(max_seconds), "--replace"]
    else:
        raise ValidationError(
            f"{path.name} is longer than {max_seconds:g}s (Gemini's limit) and neither ffmpeg nor "
            f"avconvert is available to trim it; trim it yourself first."
        )
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise ValidationError(f"Could not trim {path.name}: {(result.stderr or result.stdout).strip()[:300]}")
    return out
