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


_STATIC_CHANGE_THRESHOLD = 2.0  # mean abs gray-diff (0-255); static stories score ~0


def _run_ffmpeg(cmd: list[str], event: str, *, check: bool) -> subprocess.CompletedProcess[bytes]:
    """Run an ffmpeg command, logging a truncated stderr under `event` on failure.

    When check is True, re-raise via CalledProcessError after logging; otherwise
    the caller inspects the returned result.
    """
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        log.warning(event, stderr=result.stderr.decode(errors="replace")[-500:])
        if check:
            result.check_returncode()
    return result


def is_static_video(data: bytes) -> bool:
    """True if the clip is effectively a single still image (no motion).

    Instagram delivers photo-stories that carry background audio as a 1fps
    single-frame mp4. Those render as a frozen image with sound in Drive's
    player, so we want to detect them and serve a JPEG instead. We sample up to
    24 frames (2 fps), downscale to 32x32 grayscale, and measure the maximum
    mean absolute difference from the first frame. Real video scores well above
    the threshold; a static story scores ~0.

    On any ffmpeg failure we return False (treat as a normal video) so a probe
    glitch never silently turns a real clip into a still.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.mp4"
            src.write_bytes(data)
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            cmd = [
                "ffmpeg", "-v", "error", "-i", str(src),
                "-vf", "fps=2,scale=32:32,format=gray",
                "-frames:v", "24",
                str(frame_dir / "f_%03d.png"),
            ]
            result = _run_ffmpeg(cmd, "media_optimize.static_probe_failed", check=False)
            if result.returncode != 0:
                return False
            frames = [Image.open(p).tobytes() for p in sorted(frame_dir.glob("*.png"))]
    except Exception as exc:
        log.warning("media_optimize.static_probe_error", error=str(exc))
        return False

    if not frames:
        return False
    base = frames[0]
    return all(
        sum(abs(a - b) for a, b in zip(base, f, strict=True)) / len(f) < _STATIC_CHANGE_THRESHOLD
        for f in frames[1:]
    )


def extract_poster_frame(data: bytes) -> bytes:
    """Extract the first frame of a video and return it as a compressed JPEG.

    Used for static photo-stories (see is_static_video): we serve the single
    still as an image rather than a frozen-looking video. Raises
    subprocess.CalledProcessError if ffmpeg fails; caller should catch and skip.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.mp4"
        dst = Path(tmp) / "frame.png"
        src.write_bytes(data)
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-frames:v", "1", str(dst),
        ]
        _run_ffmpeg(cmd, "media_optimize.poster_extract_failed", check=True)
        return compress_image(dst.read_bytes())


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
        _run_ffmpeg(cmd, "media_optimize.transcode_failed", check=True)
        return dst.read_bytes()
