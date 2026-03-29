import asyncio
import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps


def process_photo(original_data: bytes, variant_specs: list[dict[str, int | str]]) -> dict[str, bytes]:
    base: Image.Image = Image.open(io.BytesIO(original_data))
    transposed = ImageOps.exif_transpose(base)
    img: Image.Image = transposed if transposed is not None else base

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    results: dict[str, bytes] = {}
    for spec in variant_specs:
        name = str(spec["name"])
        max_width = int(spec["max_width"])
        quality = int(spec["quality"])

        variant: Image.Image = img.copy()
        if variant.width > max_width:
            ratio = max_width / variant.width
            new_height = int(variant.height * ratio)
            variant = variant.resize((max_width, new_height), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        variant.save(buf, format="WEBP", quality=quality)
        results[name] = buf.getvalue()

    return results


def build_video_command(
    input_path: str,
    output_path: str,
    max_height: int,
    video_bitrate: str,
    *,
    audio: bool,
    max_duration_seconds: int | None,
) -> list[str]:
    cmd = ["ffmpeg", "-y", "-i", input_path]

    if max_duration_seconds is not None:
        cmd.extend(["-t", str(max_duration_seconds)])

    cmd.extend(
        [
            "-vf",
            f"scale=-2:'min({max_height},ih)'",
            "-c:v",
            "libvpx-vp9",
            "-b:v",
            video_bitrate,
        ]
    )

    if audio:
        cmd.extend(["-c:a", "libopus", "-b:a", "128k"])
    else:
        cmd.append("-an")

    cmd.append(output_path)
    return cmd


async def process_video(
    original_data: bytes,
    variant_specs: list[dict[str, int | str | bool]],
    original_filename: str,
) -> dict[str, bytes]:
    results: dict[str, bytes] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / original_filename
        input_path.write_bytes(original_data)

        for spec in variant_specs:
            name = str(spec["name"])
            output_path = Path(tmpdir) / f"{name}.webm"

            raw_max_height = spec["max_height"]
            raw_duration = spec.get("max_duration_seconds")

            cmd = build_video_command(
                input_path=str(input_path),
                output_path=str(output_path),
                max_height=int(raw_max_height),
                video_bitrate=str(spec["video_bitrate"]),
                audio=bool(spec.get("audio", True)),
                max_duration_seconds=int(raw_duration) if raw_duration else None,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                msg = f"ffmpeg failed for variant '{name}': {stderr.decode()}"
                raise RuntimeError(msg)

            results[name] = output_path.read_bytes()

    return results
