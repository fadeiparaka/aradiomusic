import aiohttp
from src.config import DEEZER_API_URL, TRACKS_PER_PAGE


async def _get(endpoint: str, params: dict = None) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DEEZER_API_URL}{endpoint}",
            params=params or {},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def search_tracks(query: str, offset: int = 0) -> tuple:
    data = await _get("/search/track", {"q": query, "limit": TRACKS_PER_PAGE + 1, "index": offset})
    items = data.get("data", [])
    has_next = len(items) > TRACKS_PER_PAGE
    return items[:TRACKS_PER_PAGE], has_next


async def search_artists(query: str, offset: int = 0) -> tuple:
    data = await _get("/search/artist", {"q": query, "limit": TRACKS_PER_PAGE + 1, "index": offset})
    items = data.get("data", [])
    has_next = len(items) > TRACKS_PER_PAGE
    return items[:TRACKS_PER_PAGE], has_next


async def search_albums(query: str, offset: int = 0) -> tuple:
    data = await _get("/search/album", {"q": query, "limit": TRACKS_PER_PAGE + 1, "index": offset})
    items = data.get("data", [])
    has_next = len(items) > TRACKS_PER_PAGE
    return items[:TRACKS_PER_PAGE], has_next


async def get_artist_top_tracks(artist_id: int, offset: int = 0) -> tuple:
    data = await _get(f"/artist/{artist_id}/top", {"limit": TRACKS_PER_PAGE + 1, "index": offset})
    items = data.get("data", [])
    has_next = len(items) > TRACKS_PER_PAGE
    return items[:TRACKS_PER_PAGE], has_next


async def get_album_tracks(album_id: int) -> tuple:
    data = await _get(f"/album/{album_id}/tracks", {"limit": 100})
    items = data.get("data", [])
    album_info = await _get(f"/album/{album_id}")
    title = album_info.get("title", "Альбом")
    artist = album_info.get("artist", {}).get("name", "")
    return items, title, artist


async def get_artist(artist_id: int) -> dict:
    return await _get(f"/artist/{artist_id}")


async def get_track(track_id: int) -> dict:
    return await _get(f"/track/{track_id}")
