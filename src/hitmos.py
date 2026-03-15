import logging
import os
import re
from typing import Optional, List, Dict
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://rus.hitmotop.com"
SEARCH_URL = BASE_URL + "/search?q={query}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def _normalize(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def _fetch_search_html(query: str) -> Optional[str]:
    url = SEARCH_URL.format(query=quote_plus(query))
    logging.info("hitmotop: search url=%s", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logging.error("hitmotop: request error: %s", e)
        return None


def _parse_tracks(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.tracks__item.track")
    tracks: List[Dict] = []

    for item in items:
        info = item.select_one("div.track__info")
        if not info:
            continue

        title_el = info.select_one("div.track__title")
        artist_el = info.select_one("div.track__desc")
        duration_el = info.select_one("div.track__fulltime")
        dl_el = item.select_one("a.track__download-btn[href$='.mp3']")

        if not (title_el and artist_el and dl_el):
            continue

        title = title_el.get_text(strip=True)
        artist = artist_el.get_text(strip=True)
        duration = duration_el.get_text(strip=True) if duration_el else ""
        download_url = dl_el.get("href", "").strip()

        # делаем абсолютный URL на всякий случай
        if download_url.startswith("/"):
            download_url = BASE_URL + download_url

        tracks.append(
            {
                "title": title,
                "artist": artist,
                "duration": duration,
                "download": download_url,
            }
        )

    logging.info("hitmotop: parsed %d tracks from search page", len(tracks))
    return tracks


def _find_best_track(tracks: List[Dict], artist: str, title: str) -> Optional[Dict]:
    if not tracks:
        return None

    norm_title = _normalize(title)
    norm_artist = _normalize(artist)

    # 1) точный матч по всем словам title + artist
    for t in tracks:
        t_title = _normalize(t.get("title", ""))
        t_artist = _normalize(t.get("artist", ""))
        title_ok = all(w in t_title for w in norm_title.split()) if norm_title else True
        artist_ok = all(w in t_artist for w in norm_artist.split()) if norm_artist else True
        if title_ok and artist_ok:
            return t

    # 2) fallback — частичное совпадение title
    for t in tracks:
        t_title = _normalize(t.get("title", ""))
        if norm_title and norm_title in t_title:
            return t

    # 3) последний fallback — первый результат
    return tracks[0]


def _download_mp3(url: str, output_path: str, artist: str, title: str) -> Optional[str]:
    try:
        os.makedirs(output_path, exist_ok=True)
    except Exception as e:
        logging.error("hitmotop: failed to create dir '%s': %s", output_path, e)
        return None

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", f"{artist} - {title}.mp3")
    filepath = os.path.join(output_path, safe_name)

    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
        logging.info("hitmotop: downloaded to %s", filepath)
        return filepath
    except Exception as e:
        logging.error("hitmotop: download error for %s: %s", url, e)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
        return None


def download_track(artist: str, title: str, output_path: str) -> Optional[str]:
    """
    Ищет трек на rus.hitmotop.com и качает первый подходящий mp3.
    """
    logging.info("hitmotop: starting download for '%s' - '%s'", artist, title)
    query = f"{artist} {title}"

    html = _fetch_search_html(query)
    if not html:
        return None

    tracks = _parse_tracks(html)
    if not tracks:
        logging.error("hitmotop: no tracks found for '%s'", query)
        return None

    best = _find_best_track(tracks, artist, title)
    if not best:
        logging.error("hitmotop: no matching track for '%s'", query)
        return None

    dl_url = best.get("download")
    if not dl_url:
        logging.error("hitmotop: best track has no download url")
        return None

    return _download_mp3(dl_url, output_path, best["artist"], best["title"])
