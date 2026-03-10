import os
import asyncio
import tempfile
import logging
from typing import Optional
from pathlib import Path
import yt_dlp
import traceback

BASE_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)


def _build_query(title: str, artist: str) -> str:
    return f"ytsearch1:{artist} {title} official audio"

def _download_sync(query: str, output_path: str) -> Optional[str]:
    logging.info("yt-dlp start, query=%r, output=%r", query, output_path)
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "quiet": False,          # временно включим вывод
        "no_warnings": False,    # чтобы видеть предупреждения
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
        ],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([query])
        mp3 = output_path + ".mp3"
        if os.path.exists(mp3):
            logging.info("yt-dlp success, file=%r", mp3)
            return mp3
        logging.error("yt-dlp finished but file not found: %r", mp3)
        return None
    except Exception as e:
        logging.error("yt-dlp error for query %r: %s", query, e)
        logging.error("traceback:\n%s", traceback.format_exc())
        return None

async def download_track(track_id: int, title: str = "", artist: str = "") -> Optional[str]:
    query = f"ytsearch1:{artist} {title} audio"
    output_path = os.path.join(TMP_DIR, f"track_{track_id}")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_sync, query, output_path)

def delete_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
