import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image
from PIL.ExifTags import Base as ExifBase

from app.media.processing import build_video_command, process_document, process_photo, process_video


def _create_test_image(width: int = 2000, height: int = 1500, fmt: str = "JPEG") -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


async def test_process_photo_creates_variants() -> None:
    original = _create_test_image(2000, 1500)
    variant_specs: list[dict[str, int | str]] = [
        {"name": "large", "max_width": 1200, "quality": 85},
        {"name": "medium", "max_width": 600, "quality": 80},
        {"name": "small", "max_width": 200, "quality": 75},
    ]

    results = process_photo(original, variant_specs)

    assert len(results) == 3
    for spec in variant_specs:
        name = str(spec["name"])
        assert name in results
        img = Image.open(io.BytesIO(results[name]))
        assert img.format == "WEBP"
        assert img.width <= int(spec["max_width"])


async def test_process_photo_does_not_upscale() -> None:
    original = _create_test_image(100, 75)
    variant_specs: list[dict[str, int | str]] = [
        {"name": "large", "max_width": 1200, "quality": 85},
        {"name": "small", "max_width": 200, "quality": 75},
    ]

    results = process_photo(original, variant_specs)

    for name in results:
        img = Image.open(io.BytesIO(results[name]))
        assert img.width <= 100


async def test_process_photo_strips_exif() -> None:
    img = Image.new("RGB", (800, 600), color="blue")
    exif_data = img.getexif()
    exif_data[ExifBase.Make] = "TestCamera"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_data.tobytes())
    original = buf.getvalue()

    results = process_photo(original, [{"name": "medium", "max_width": 600, "quality": 80}])

    result_img = Image.open(io.BytesIO(results["medium"]))
    result_exif = result_img.getexif()
    assert ExifBase.Make not in result_exif


async def test_build_video_full_command() -> None:
    cmd = build_video_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.webm",
        max_height=720,
        video_bitrate="1.5M",
        audio=True,
        max_duration_seconds=None,
    )
    assert "-vf" in cmd
    assert any("scale=" in c for c in cmd)
    assert "-b:v" in cmd
    assert "1.5M" in cmd
    assert "-an" not in cmd


async def test_build_video_preview_command() -> None:
    cmd = build_video_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/preview.webm",
        max_height=480,
        video_bitrate="500k",
        audio=False,
        max_duration_seconds=10,
    )
    assert "-an" in cmd
    assert "-t" in cmd
    assert "10" in cmd


async def test_document_processing_is_passthrough() -> None:
    original = b"%PDF-1.4 fake pdf content"
    result = process_document(original)
    assert result == original


# ── RGBA / palette mode conversion ──────────────────────


def _create_rgba_image(width: int = 400, height: int = 300) -> bytes:
    img = Image.new("RGBA", (width, height), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_palette_image(width: int = 400, height: int = 300) -> bytes:
    img = Image.new("P", (width, height))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_process_photo_rgba_conversion() -> None:
    original = _create_rgba_image()
    variant_specs: list[dict[str, int | str]] = [
        {"name": "medium", "max_width": 600, "quality": 80},
    ]

    results = process_photo(original, variant_specs)

    assert "medium" in results
    img = Image.open(io.BytesIO(results["medium"]))
    assert img.format == "WEBP"


async def test_process_photo_palette_mode() -> None:
    original = _create_palette_image()
    variant_specs: list[dict[str, int | str]] = [
        {"name": "small", "max_width": 200, "quality": 75},
    ]

    results = process_photo(original, variant_specs)

    assert "small" in results
    img = Image.open(io.BytesIO(results["small"]))
    assert img.format == "WEBP"


# ── process_video with mocked ffmpeg ────────────────────


def _write_fake_output(path: str, data: bytes) -> None:
    """Write fake ffmpeg output (sync helper to avoid ASYNC240 lint)."""
    Path(path).write_bytes(data)


async def test_process_video_calls_ffmpeg() -> None:
    variant_specs: list[dict[str, int | str | bool]] = [
        {"name": "full", "max_height": 720, "video_bitrate": "1.5M", "audio": True},
    ]

    async def fake_subprocess(*args: object, **_kwargs: object) -> AsyncMock:
        # The output path is the last argument to ffmpeg
        output_path = str(args[-1])
        _write_fake_output(output_path, b"fake webm data")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        return mock_proc

    with patch("app.media.processing.asyncio.create_subprocess_exec", side_effect=fake_subprocess):
        results = await process_video(b"fake input video", variant_specs, "input.mp4")

    assert "full" in results
    assert results["full"] == b"fake webm data"


async def test_process_video_multiple_variants() -> None:
    variant_specs: list[dict[str, int | str | bool]] = [
        {"name": "full", "max_height": 720, "video_bitrate": "1.5M", "audio": True},
        {"name": "preview", "max_height": 480, "video_bitrate": "500k", "audio": False, "max_duration_seconds": 10},
    ]

    async def fake_subprocess(*args: object, **_kwargs: object) -> AsyncMock:
        output_path = str(args[-1])
        _write_fake_output(output_path, b"variant data")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        return mock_proc

    with patch("app.media.processing.asyncio.create_subprocess_exec", side_effect=fake_subprocess):
        results = await process_video(b"fake video", variant_specs, "clip.mp4")

    assert "full" in results
    assert "preview" in results


async def test_process_video_ffmpeg_failure() -> None:
    variant_specs: list[dict[str, int | str | bool]] = [
        {"name": "full", "max_height": 720, "video_bitrate": "1.5M", "audio": True},
    ]

    async def failing_subprocess(*_args: object, **_kwargs: object) -> AsyncMock:
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"ffmpeg error output"))
        return mock_proc

    with patch("app.media.processing.asyncio.create_subprocess_exec", side_effect=failing_subprocess):
        with pytest.raises(RuntimeError, match="ffmpeg failed for variant 'full'"):
            await process_video(b"fake video", variant_specs, "input.mp4")
