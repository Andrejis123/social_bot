"""Tests for drive sync path helpers, media_optimize, and sync_client_to_drive."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from social_bot.media_optimize import compress_image
from social_bot.pipeline.run_context import RunContext
from social_bot.pipeline.sync_drive import (
    _drive_folder_for_post,
    _drive_folder_for_story,
    _ext_from_mime,
    _prune,
    sync_client_to_drive,
)

# ---------------------------------------------------------------------------
# Path building
# ---------------------------------------------------------------------------


def test_drive_folder_for_post_basic():
    path = _drive_folder_for_post(
        "SMM - Live", "ecig-monitoring", "pulzeczech",
        "2026-06-28T10:00:00+00:00", "3922100065003843139",
    )
    assert path == "SMM - Live/ecig-monitoring/@pulzeczech/Posts/28-06-2026_843139"


def test_drive_folder_for_post_date_truncation():
    path = _drive_folder_for_post("Root", "client", "handle", "2026-01-15", "123456789")
    assert "15-01-2026_456789" in path


def test_drive_folder_for_post_empty_posted_at():
    path = _drive_folder_for_post("Root", "c", "h", "", "id")
    assert path == "Root/c/@h/Posts/_id"


def test_drive_folder_for_story_basic():
    path = _drive_folder_for_story("SMM - Live", "agape", "agapeslovensko", "2026-06-28T09:00:00")
    assert path == "SMM - Live/agape/@agapeslovensko/Stories/28-06-2026"


def test_drive_folder_for_story_empty_date():
    path = _drive_folder_for_story("Root", "c", "h", "")
    assert path == "Root/c/@h/Stories/"


# ---------------------------------------------------------------------------
# ext_from_mime
# ---------------------------------------------------------------------------


def test_ext_from_mime_jpeg():
    assert _ext_from_mime("image/jpeg", "image") == "jpg"


def test_ext_from_mime_png_converts_to_jpg():
    assert _ext_from_mime("image/png", "image") == "jpg"


def test_ext_from_mime_video_mp4():
    assert _ext_from_mime("video/mp4", "video") == "mp4"


def test_ext_from_mime_quicktime_to_mp4():
    assert _ext_from_mime("video/quicktime", "video") == "mp4"


def test_ext_from_mime_unknown_falls_back_to_media_type():
    assert _ext_from_mime("application/octet-stream", "video") == "mp4"
    assert _ext_from_mime("application/octet-stream", "image") == "jpg"


# ---------------------------------------------------------------------------
# compress_image: size reduction and output format
# ---------------------------------------------------------------------------


def _make_png(width: int = 2000, height: int = 2000) -> bytes:
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_rgba_png(width: int = 800, height: int = 800) -> bytes:
    img = Image.new("RGBA", (width, height), color=(100, 150, 200, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_compress_image_reduces_size():
    original = _make_png(2000, 2000)
    compressed = compress_image(original)
    assert len(compressed) < len(original)


def test_compress_image_output_is_jpeg():
    compressed = compress_image(_make_png())
    # JPEG magic bytes: FF D8
    assert compressed[:2] == b"\xff\xd8"


def test_compress_image_downscales_large_image():
    compressed = compress_image(_make_png(3000, 3000))
    result = Image.open(io.BytesIO(compressed))
    assert max(result.width, result.height) <= 1080


def test_compress_image_small_image_not_upscaled():
    small = _make_png(200, 200)
    compressed = compress_image(small)
    result = Image.open(io.BytesIO(compressed))
    assert max(result.width, result.height) <= 200


def test_compress_image_rgba_flattened_to_rgb():
    compressed = compress_image(_make_rgba_png())
    result = Image.open(io.BytesIO(compressed))
    assert result.mode == "RGB"


def test_compress_image_custom_quality_and_edge():
    tiny = compress_image(_make_png(500, 500), max_long_edge=100, quality=50)
    result = Image.open(io.BytesIO(tiny))
    assert max(result.width, result.height) <= 100


# ---------------------------------------------------------------------------
# transcode_video: verify ffmpeg call and error handling
# ---------------------------------------------------------------------------


def test_transcode_video_invokes_subprocess():
    """transcode_video calls subprocess.run with ffmpeg and returns output bytes."""

    with (
        patch("social_bot.media_optimize.subprocess.run") as mock_run,
        patch("social_bot.media_optimize.tempfile.TemporaryDirectory") as mock_tmpdir,
        patch("social_bot.media_optimize.Path") as mock_path,
    ):
        # Make two distinct path mocks: src and dst
        src_path = MagicMock()
        dst_path = MagicMock()
        dst_path.read_bytes.return_value = b"output_mp4_data"

        call_count = [0]
        def fake_div(self, name: str) -> MagicMock:
            call_count[0] += 1
            return src_path if call_count[0] == 1 else dst_path

        mock_path.return_value.__truediv__ = fake_div
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/tmp/x")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        from social_bot.media_optimize import transcode_video

        transcode_video(b"fake_video")
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-vf" in cmd
        assert "scale=-2:480" in cmd


def test_transcode_video_raises_on_ffmpeg_failure():
    """transcode_video should raise CalledProcessError if ffmpeg fails."""
    import subprocess

    with patch("social_bot.media_optimize.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"some ffmpeg error"
        mock_result.check_returncode.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
        mock_run.return_value = mock_result

        from social_bot.media_optimize import transcode_video

        with (
            pytest.raises(subprocess.CalledProcessError),
            patch("social_bot.media_optimize.tempfile.TemporaryDirectory"),
            patch("builtins.open", MagicMock()),
            patch("social_bot.media_optimize.Path") as mock_path,
        ):
            p = MagicMock()
            p.__truediv__ = MagicMock(return_value=p)
            p.write_bytes = MagicMock()
            p.read_bytes = MagicMock(return_value=b"")
            mock_path.return_value = p
            transcode_video(b"fake_data")


# ---------------------------------------------------------------------------
# Helpers for sync_client_to_drive tests
# ---------------------------------------------------------------------------


def _make_settings_mock() -> MagicMock:
    s = MagicMock()
    s.google_drive_live_root_folder = "SMM - Live"
    return s


def _post_media_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "media_id": "media-1",
        "slide_index": 0,
        "media_type": "image",
        "storage_path": "media/client/img.jpg",
        "post_id": "post-1",
        "platform_post_id": "post123",
        "posted_at": "2026-06-01T10:00:00+00:00",
        "account_id": "acct-1",
    }
    row.update(overrides)
    return row


def _story_media_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "story_media_id": "smedia-1",
        "media_type": "image",
        "storage_path": "media/client/story.jpg",
        "story_id": "story-1",
        "platform_story_id": "story123",
        "posted_at": "2026-06-01T09:00:00+00:00",
        "account_id": "acct-1",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def sync_env() -> dict[str, MagicMock]:
    """Patch all external I/O so sync_client_to_drive runs without live APIs."""
    plist = {
        "start_run": patch("social_bot.db.queries.start_run", return_value="run-test-123"),
        "finish_run": patch("social_bot.db.queries.finish_run"),
        "record_item_error": patch("social_bot.db.queries.record_item_error"),
        "get_client_id": patch(
            "social_bot.db.queries.get_client_id_by_slug",
            return_value="client-uuid",
        ),
        "list_accounts": patch(
            "social_bot.db.queries.list_accounts_for_client",
            return_value=[{"id": "acct-1", "handle": "testhandle", "platform": "instagram"}],
        ),
        "list_post_media": patch(
            "social_bot.db.queries.list_unsynced_post_media", return_value=[]
        ),
        "list_story_media": patch(
            "social_bot.db.queries.list_unsynced_story_media", return_value=[]
        ),
        "list_exp_post": patch(
            "social_bot.db.queries.list_expired_drive_media", return_value=[]
        ),
        "list_exp_story": patch(
            "social_bot.db.queries.list_expired_drive_story_media", return_value=[]
        ),
        "mark_media_synced": patch("social_bot.db.queries.mark_media_synced"),
        "mark_story_synced": patch("social_bot.db.queries.mark_story_media_synced"),
        "clear_media_drive": patch("social_bot.db.queries.clear_media_drive"),
        "clear_story_drive": patch("social_bot.db.queries.clear_story_media_drive"),
        "get_settings": patch(
            "social_bot.pipeline.sync_drive.get_settings",
            return_value=_make_settings_mock(),
        ),
        "share_folder": patch(
            "social_bot.pipeline.sync_drive.share_folder_anyone",
            return_value="https://drive.link/shared",
        ),
        "upload_bytes": patch(
            "social_bot.pipeline.sync_drive.upload_bytes",
            return_value={"id": "drive-file-xyz"},
        ),
        "delete_file": patch("social_bot.pipeline.sync_drive.delete_file"),
        "download": patch(
            "social_bot.pipeline.sync_drive.download_from_storage",
            return_value=(b"img_bytes", "image/jpeg"),
        ),
        "compress_image": patch(
            "social_bot.pipeline.sync_drive.compress_image", return_value=b"compressed"
        ),
        "transcode_video": patch(
            "social_bot.pipeline.sync_drive.transcode_video", return_value=b"transcoded"
        ),
        "check_quota": patch("social_bot.pipeline.sync_drive._check_quota"),
        "tg_started": patch("social_bot.notifications.telegram.notify_run_started"),
        "tg_completed": patch("social_bot.notifications.telegram.notify_run_completed"),
    }
    started = {k: p.start() for k, p in plist.items()}
    yield started  # type: ignore[misc]
    for p in plist.values():
        p.stop()


# ---------------------------------------------------------------------------
# sync_client_to_drive: account / client lookup
# ---------------------------------------------------------------------------


def test_sync_client_not_found_returns_run_id(sync_env: dict[str, MagicMock]) -> None:
    """Returns run_id without crashing when client_slug is unknown."""
    sync_env["get_client_id"].return_value = None

    run_id = sync_client_to_drive("no-such-client")

    assert run_id == "run-test-123"
    # No accounts fetched, no media queries issued.
    sync_env["list_accounts"].assert_not_called()
    sync_env["list_post_media"].assert_not_called()


# ---------------------------------------------------------------------------
# sync_client_to_drive: post media happy path
# ---------------------------------------------------------------------------


def test_sync_post_media_uploads_and_marks_synced(sync_env: dict[str, MagicMock]) -> None:
    """Unsynced image post media: download -> compress -> upload -> mark_synced."""
    sync_env["list_post_media"].return_value = [_post_media_row()]

    sync_client_to_drive("test-client")

    sync_env["download"].assert_called_once_with("media/client/img.jpg")
    sync_env["compress_image"].assert_called_once_with(b"img_bytes")
    sync_env["transcode_video"].assert_not_called()
    sync_env["upload_bytes"].assert_called_once()
    sync_env["mark_media_synced"].assert_called_once_with("media-1", "drive-file-xyz")


def test_sync_post_media_video_path(sync_env: dict[str, MagicMock]) -> None:
    """Unsynced video post media: download -> transcode -> upload (not compress_image)."""
    sync_env["list_post_media"].return_value = [
        _post_media_row(media_type="video", storage_path="media/client/vid.mp4")
    ]
    sync_env["download"].return_value = (b"vid_bytes", "video/mp4")

    sync_client_to_drive("test-client")

    sync_env["transcode_video"].assert_called_once_with(b"vid_bytes")
    sync_env["compress_image"].assert_not_called()
    sync_env["mark_media_synced"].assert_called_once_with("media-1", "drive-file-xyz")


# ---------------------------------------------------------------------------
# sync_client_to_drive: story media happy path
# ---------------------------------------------------------------------------


def test_sync_story_media_uploads_and_marks_synced(sync_env: dict[str, MagicMock]) -> None:
    """Unsynced image story media: download -> compress -> upload -> mark_story_synced."""
    sync_env["list_story_media"].return_value = [_story_media_row()]

    sync_client_to_drive("test-client")

    sync_env["download"].assert_called_once_with("media/client/story.jpg")
    sync_env["compress_image"].assert_called_once()
    sync_env["upload_bytes"].assert_called_once()
    sync_env["mark_story_synced"].assert_called_once_with("smedia-1", "drive-file-xyz")
    sync_env["mark_media_synced"].assert_not_called()


# ---------------------------------------------------------------------------
# sync_client_to_drive: error resilience
# ---------------------------------------------------------------------------


def test_sync_video_transcode_failure_continues(sync_env: dict[str, MagicMock]) -> None:
    """CalledProcessError from ffmpeg marks item as error; remaining items still processed."""
    sync_env["list_post_media"].return_value = [
        _post_media_row(media_id="media-1", media_type="video"),
        _post_media_row(media_id="media-2", media_type="image"),
    ]
    sync_env["download"].return_value = (b"data", "image/jpeg")
    sync_env["transcode_video"].side_effect = subprocess.CalledProcessError(1, "ffmpeg")

    sync_client_to_drive("test-client")

    # First item (video) errored; second item (image) was still processed.
    sync_env["transcode_video"].assert_called_once()
    sync_env["compress_image"].assert_called_once()
    sync_env["mark_media_synced"].assert_called_once_with("media-2", "drive-file-xyz")
    # The failed item was never marked synced.
    assert sync_env["mark_media_synced"].call_args_list[0][0][0] != "media-1"


def test_sync_download_failure_continues(sync_env: dict[str, MagicMock]) -> None:
    """Download failure marks item as error; remaining items still processed."""
    sync_env["list_post_media"].return_value = [
        _post_media_row(media_id="media-1"),
        _post_media_row(media_id="media-2"),
    ]
    # First download raises, second succeeds.
    sync_env["download"].side_effect = [
        OSError("storage unavailable"),
        (b"img_bytes", "image/jpeg"),
    ]

    sync_client_to_drive("test-client")

    assert sync_env["download"].call_count == 2
    # Only the second item reaches upload/mark_synced.
    sync_env["mark_media_synced"].assert_called_once_with("media-2", "drive-file-xyz")


# ---------------------------------------------------------------------------
# sync_client_to_drive: share folder is idempotent (called once per run)
# ---------------------------------------------------------------------------


def test_share_folder_called_once_per_run(sync_env: dict[str, MagicMock]) -> None:
    """share_folder_anyone is called exactly once regardless of how many accounts exist."""
    sync_env["list_accounts"].return_value = [
        {"id": "acct-1", "handle": "handle1", "platform": "instagram"},
        {"id": "acct-2", "handle": "handle2", "platform": "instagram"},
    ]
    sync_env["list_post_media"].return_value = [
        _post_media_row(account_id="acct-1"),
        _post_media_row(media_id="media-2", account_id="acct-2"),
    ]

    sync_client_to_drive("test-client")

    sync_env["share_folder"].assert_called_once()


# ---------------------------------------------------------------------------
# sync_client_to_drive: silent=True suppresses start Telegram notification
# ---------------------------------------------------------------------------


def test_silent_true_no_start_notification(sync_env: dict[str, MagicMock]) -> None:
    """RunContext is always created with silent=True: no Telegram start notification sent."""
    sync_client_to_drive("test-client")
    sync_env["tg_started"].assert_not_called()


# ---------------------------------------------------------------------------
# _prune: direct unit test (no RunContext.__enter__ needed)
# ---------------------------------------------------------------------------


def test_prune_calls_delete_and_clear_for_expired_media() -> None:
    """_prune deletes Drive files and clears ledger columns for expired post media."""
    expired_post = [{"media_id": "old-media-1", "drive_file_id": "gfile-111"}]
    expired_story = [{"story_media_id": "old-story-1", "drive_file_id": "gfile-222"}]

    run = RunContext(job_name="sync_drive", client_slug="test-client")

    with (
        patch("social_bot.db.queries.list_expired_drive_media", return_value=expired_post),
        patch(
            "social_bot.db.queries.list_expired_drive_story_media",
            return_value=expired_story,
        ),
        patch("social_bot.pipeline.sync_drive.delete_file") as m_delete,
        patch("social_bot.db.queries.clear_media_drive") as m_clear_media,
        patch("social_bot.db.queries.clear_story_media_drive") as m_clear_story,
    ):
        _prune(datetime.now(UTC), run)

    assert m_delete.call_count == 2
    m_delete.assert_any_call("gfile-111")
    m_delete.assert_any_call("gfile-222")
    m_clear_media.assert_called_once_with("old-media-1")
    m_clear_story.assert_called_once_with("old-story-1")
    assert run.items_updated == 2


def test_prune_continues_on_delete_failure() -> None:
    """_prune does not crash when delete_file raises; items_updated not incremented."""
    expired_post = [{"media_id": "old-media-1", "drive_file_id": "gfile-111"}]

    run = RunContext(job_name="sync_drive", client_slug="test-client")

    with (
        patch("social_bot.db.queries.list_expired_drive_media", return_value=expired_post),
        patch("social_bot.db.queries.list_expired_drive_story_media", return_value=[]),
        patch(
            "social_bot.pipeline.sync_drive.delete_file",
            side_effect=RuntimeError("Drive API down"),
        ),
        patch("social_bot.db.queries.clear_media_drive") as m_clear,
    ):
        _prune(datetime.now(UTC), run)

    # clear_media_drive is never called when delete_file raises.
    m_clear.assert_not_called()
    assert run.items_updated == 0


# ===========================================================================
# BUG A — orphan duplicate uploads
#
# Root cause: drive.upload_bytes defaults overwrite=False, so it always calls
# service.files().create() and never replaces a same-named file. The sync path
# (sync_client_to_drive) calls upload_bytes WITHOUT overwrite, so a re-sync of
# an item whose same-named Drive file already exists creates a DUPLICATE and
# orphans the old copy (e.g. when the DB ledger drive_synced_at is reset but the
# physical Drive files survive).
#
# Intended (to be implemented by the human):
#   - upload_bytes(overwrite=True) replaces the existing same-named file via
#     service.files().update() instead of .create().  [A1 — already honored by
#     drive.py today, kept as a contract/guard test; should PASS.]
#   - sync_client_to_drive must call upload_bytes(..., overwrite=True) so a
#     re-sync REPLACES rather than duplicates.  [A2 — FAILS today: the call site
#     omits overwrite and inherits the False default.]
# ===========================================================================


def test_upload_bytes_overwrite_true_updates_existing() -> None:
    """upload_bytes(overwrite=True) replaces a same-named file via files().update().

    Contract/guard test for the idempotent path. drive.upload_bytes already
    implements this branch, so this PASSES today; the bug A regression is
    captured by the sync-call-site test below.
    """
    service = MagicMock()
    service.files.return_value.update.return_value.execute.return_value = {
        "id": "existing-123",
        "webViewLink": "https://drive.link/existing",
    }

    with (
        patch("social_bot.drive.get_or_create_folder", return_value="folder-1"),
        patch("social_bot.drive._build_service", return_value=service),
        patch("social_bot.drive._find_file_in_folder", return_value="existing-123"),
    ):
        from social_bot.drive import upload_bytes

        result = upload_bytes(
            data=b"new_bytes",
            name="0.jpg",
            drive_folder_path="SMM - Live/c/@h/Posts/01-06-2026_post123",
            mime_type="image/jpeg",
            overwrite=True,
        )

    service.files.return_value.update.assert_called_once()
    service.files.return_value.create.assert_not_called()
    assert result["id"] == "existing-123"


def test_sync_post_media_upload_is_idempotent_overwrite(
    sync_env: dict[str, MagicMock],
) -> None:
    """sync_client_to_drive must call upload_bytes with overwrite=True.

    FAILS today: the call site in sync_drive omits overwrite, so the False
    default is inherited and a re-sync creates a duplicate Drive file instead
    of replacing the existing same-named one.
    """
    sync_env["list_post_media"].return_value = [_post_media_row()]

    sync_client_to_drive("test-client")

    sync_env["upload_bytes"].assert_called_once()
    assert sync_env["upload_bytes"].call_args.kwargs.get("overwrite") is True


def test_sync_story_media_upload_is_idempotent_overwrite(
    sync_env: dict[str, MagicMock],
) -> None:
    """Story sync path must also call upload_bytes with overwrite=True.

    FAILS today for the same reason as the post path.
    """
    sync_env["list_story_media"].return_value = [_story_media_row()]

    sync_client_to_drive("test-client")

    sync_env["upload_bytes"].assert_called_once()
    assert sync_env["upload_bytes"].call_args.kwargs.get("overwrite") is True


# ===========================================================================
# BUG B — static photo+audio stories render as frozen video
#
# Root cause: Instagram ships a photo-story that has background audio as a 1fps
# single-frame mp4 (all frames identical, 0 scene changes). media_optimize.
# transcode_video preserves it as video, so Drive shows a static image with
# audio that looks frozen.
#
# Proposed (not-yet-implemented) interface the human should build to satisfy
# these tests:
#
#   media_optimize.is_static_video(data: bytes) -> bool
#       Returns True when the clip has a single distinct frame / no scene change
#       (a static image with an audio track), False for a clip with real motion.
#
#   sync_client_to_drive: when is_static_video(data) is True for a video item,
#       render a JPEG still instead of transcoding, and upload it as
#       "<platform_story_id>.jpg" with mime_type "image/jpeg" (NOT ".mp4" /
#       "video/mp4").
# ===========================================================================


_FFMPEG = shutil.which("ffmpeg")


def _make_static_video_bytes() -> bytes:
    """A 1fps clip of a single constant frame plus a silent audio track.

    Mimics Instagram's photo-story-with-audio: every video frame is identical
    (zero scene changes).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "static.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=3:r=1",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                "-shortest",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                str(out),
            ],
            capture_output=True,
            check=True,
        )
        return out.read_bytes()


def _make_moving_video_bytes() -> bytes:
    """A clip with genuine motion (animated test pattern)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "moving.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc=s=160x120:d=2:r=10",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(out),
            ],
            capture_output=True,
            check=True,
        )
        return out.read_bytes()


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not available")
def test_is_static_video_detects_single_frame_clip() -> None:
    """is_static_video returns True for a single-distinct-frame clip.

    FAILS today: media_optimize.is_static_video does not exist yet
    (AttributeError). Import is kept inside the test so module collection is
    not broken.
    """
    from social_bot import media_optimize

    static = _make_static_video_bytes()
    assert media_optimize.is_static_video(static) is True


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not available")
def test_is_static_video_rejects_moving_clip() -> None:
    """is_static_video returns False for a clip with real motion.

    Asserted separately from the static case so the function cannot be
    satisfied by a constant `return True`.
    """
    from social_bot import media_optimize

    moving = _make_moving_video_bytes()
    assert media_optimize.is_static_video(moving) is False


def test_sync_static_story_uploads_as_jpeg(sync_env: dict[str, MagicMock]) -> None:
    """A static (single-frame + audio) video story is uploaded as a JPEG image.

    FAILS today: sync_drive has no is_static_video branch, so a video story is
    transcoded and uploaded as "<platform_story_id>.mp4" / "video/mp4". The
    intended behavior uploads "<platform_story_id>.jpg" / "image/jpeg".

    The is_static_video symbol is patched with create=True so the test is
    forward-compatible once the human wires the import/branch into sync_drive.
    """
    sync_env["list_story_media"].return_value = [
        _story_media_row(
            media_type="video",
            storage_path="media/client/story.mp4",
            platform_story_id="story123",
        )
    ]
    sync_env["download"].return_value = (b"static_video_bytes", "video/mp4")

    with (
        patch(
            "social_bot.pipeline.sync_drive.is_static_video",
            create=True,
            return_value=True,
        ),
        patch(
            "social_bot.pipeline.sync_drive.extract_poster_frame",
            create=True,
            return_value=b"poster_jpeg",
        ),
    ):
        sync_client_to_drive("test-client")

    sync_env["upload_bytes"].assert_called_once()
    kwargs = sync_env["upload_bytes"].call_args.kwargs
    assert kwargs["name"] == "story123.jpg"
    assert kwargs["mime_type"] == "image/jpeg"
