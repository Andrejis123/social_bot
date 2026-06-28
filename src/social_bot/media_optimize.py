"""
Lightweight media optimization for the Drive live view.

Images are downscaled and JPEG-compressed to tens of KB. Videos are transcoded
to ~480p via ffmpeg so they remain playable at a fraction of the original size.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from .logging import get_logger

log = get_logger(__name__)

_MAX_LONG_EDGE = 1080
_JPEG_QUALITY = 82


def compress_image(data: bytes, *, max_long_edge: int = _MAX_LONG_EDGE, quality: int = _JPEG_QUALITY) -> bytes:
    """Downscale image to max_long_edge and encode as JPEG. Returns JPEG bytes."""
    im: Any = Image.open(io.BytesIO(data))
    if im.width > max_long_edge or im.height > max_long_edge:
        im.thumbnail((max_long_edge, max_long_edge), Image.LANCZOS)  # type: ignore[attr-defined]
    if im.mode != "RGB":
        if im.mode in ("P", "LA"):
            im = im.convert("RGBA")
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def transcode_video(data: bytes) -> bytes:
    """Transcode video to ~480p H.264 via ffmpeg. Returns MP4 bytes.

    Raises subprocess.CalledProcessError on non-zero exit. Caller should catch,
    log, and skip the file rather than failing the whole run.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.mp4"
        dst = Path(tmp) / "output.mp4"
        src.write_bytes(data)
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", "scale=-2:480",
            "-c:v", "libx264", "-crf", "30", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "64k",
            "-movflags", "+faststart",
            str(dst),
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            log.warning(
                "media_optimize.transcode_failed",
                stderr=result.stderr.decode(errors="replace")[-500:],
            )
            result.check_returncode()
        return dst.read_bytes()
