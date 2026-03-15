import os
import asyncio
import logging
from typing import Optional
from pathlib import Path
import traceback

from hitmo_retrack import download_from_hitmo_net

from src import hitmos


BASE_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)


def _download_sync(title: str, artist: str, output_path: str) -> Optional[str]:
    logging.info(
        "hitmos start, artist=%r, title=%r, output=%r",
        artist,
        title,
        output_path,
    )
    try:
        mp3 = hitmos.download_track(artist=artist, title=title, output_path=output_path)
        if mp3 and os.path.exists(mp3):
            logging.info("hitmos success, file=%r", mp3)
            return mp3
        logging.error("hitmos finished but file not found")
        return None
    except Exception as e:
        logging.error(
            "hitmos error for artist=%r title=%r: %s", artist, title, e
        )
        logging.error("traceback:\n%s", traceback.format_exc())
        return None

async def _transcode_to_128(orig_path: Path) -> Path | None:
    """
    Пережимает mp3 до 128 kbps CBR с помощью ffmpeg.
    Возвращает путь к новому файлу или None при ошибке.
    """
    try:
        if not orig_path.exists():
            logging.warning("ffmpeg: orig file not found: %s", orig_path)
            return None

        out_path = orig_path.with_name("compressed_128.mp3")

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(orig_path),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-b:a",
            "128k",
            str(out_path),
        ]

        logging.info("ffmpeg: start transcode %s -> %s", orig_path, out_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        returncode = await proc.wait()

        if returncode != 0 or not out_path.exists():
            logging.error(
                "ffmpeg: failed, code=%s, out_exists=%s",
                returncode,
                out_path.exists(),
            )
            return None

        try:
            orig_path.unlink()
        except Exception:
            logging.warning("ffmpeg: failed to remove orig file: %s", orig_path)

        logging.info(
            "ffmpeg: done, path=%s, size=%s bytes",
            out_path,
            out_path.stat().st_size,
        )
        return out_path

    except Exception as e:
        logging.exception("ffmpeg: unexpected error: %s", e)
        return None

async def download_track(
    track_id: int, title: str = "", artist: str = ""
) -> Optional[str]:
    output_path = os.path.join(TMP_DIR, f"track_{track_id}")
    loop = asyncio.get_event_loop()

    # 1. Пытаемся через старый hitmos
    local_path = await loop.run_in_executor(
        None, _download_sync, title, artist, output_path
    )

    # 2. Если не вышло — fallback на hitmo.net
    if not local_path:
        logging.info(
            "fallback: trying hitmo_net for '%s' - '%s'",
            artist,
            title,
        )
        local_path = await loop.run_in_executor(
            None, download_from_hitmo_net, title, artist, output_path
        )

    if not local_path:
        return None

    orig_path = Path(local_path)
    compressed = await _transcode_to_128(orig_path)
    if compressed is not None:
        return str(compressed)

    return str(orig_path)

def delete_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
