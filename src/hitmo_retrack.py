import logging
import os
import re
import urllib.parse
from typing import Optional

import requests


BASE_SEARCH_URL = "https://music.hitmo.net/search/"


def _build_search_url(query: str) -> str:
    # music.hitmo.net/search/{encoded_query}
    encoded = urllib.parse.quote(query, safe="")
    return f"{BASE_SEARCH_URL}{encoded}"


def _extract_mp3_link(html: str) -> Optional[str]:
    """
    Ищет первую ссылку вида https://d1.hitmo.net/...mp3 в HTML.
    """
    match = re.search(r"https://d1\.hitmo\.net/[A-Za-z0-9_=/+\-]+\.mp3", html)
    if not match:
        return None
    return match.group(0)


def download_from_hitmo_net(
    title: str,
    artist: str,
    output_path: str,
    timeout: int = 15,
) -> Optional[str]:
    """
    Пытается найти и скачать трек с music.hitmo.net.
    Возвращает путь к локальному mp3 или None.
    """
    query = f"{artist} {title}".strip()
    if not query:
        logging.warning("hitmo_net: empty query, skip")
        return None

    search_url = _build_search_url(query)
    logging.info("hitmo_net: search url=%s", search_url)

    try:
        resp = requests.get(search_url, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logging.error("hitmo_net: search request failed: %s", e)
        return None

    mp3_url = _extract_mp3_link(resp.text)
    if not mp3_url:
        logging.error("hitmo_net: no mp3 link found for query='%s'", query)
        return None

    logging.info("hitmo_net: downloading %s", mp3_url)

    try:
        r = requests.get(mp3_url, stream=True, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        logging.error("hitmo_net: mp3 download failed: %s", e)
        return None

    os.makedirs(output_path, exist_ok=True)
    file_path = os.path.join(output_path, "hitmo_net_track.mp3")

    try:
        with open(file_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        logging.error("hitmo_net: error writing file: %s", e)
        return None

    logging.info("hitmo_net: saved to %s", file_path)
    return file_path
