import time
from typing import Dict
from typing import Optional

# Структура: {user_id: {query, search_type, offset, has_next, mode, context_id, context_name}}
_states: dict = {}

def set_search_state(
    user_id: int, query: str, search_type: str, offset: int, has_next: bool
) -> None:
    _states[user_id] = {
        "query": query,
        "search_type": search_type,
        "offset": offset,
        "has_next": has_next,
        "mode": "search",
        "context_id": None,
        "context_name": None,
    }


def set_artist_state(
    user_id: int, artist_id: int, artist_name: str, offset: int, has_next: bool
) -> None:
    prev = _states.get(user_id, {})
    _states[user_id] = {
        "query": prev.get("query", ""),
        "search_type": prev.get("search_type", "artist"),
        "offset": offset,
        "has_next": has_next,
        "mode": "artist_tracks",
        "context_id": artist_id,
        "context_name": artist_name,
    }


def get_state(user_id: int) -> Optional[dict]:
    return _states.get(user_id)


def update_offset(user_id: int, offset: int, has_next: bool) -> None:
    if user_id in _states:
        _states[user_id]["offset"] = offset
        _states[user_id]["has_next"] = has_next


def update_search_type(user_id: int, search_type: str) -> None:
    if user_id in _states:
        _states[user_id]["search_type"] = search_type
        _states[user_id]["offset"] = 0
        _states[user_id]["has_next"] = False
        _states[user_id]["mode"] = "search"

def set_search_state(
    user_id: int, query: str, search_type: str, offset: int, has_next: bool,
    results_message_id: int = None
) -> None:
    _states[user_id] = {
        "query": query,
        "search_type": search_type,
        "offset": offset,
        "has_next": has_next,
        "mode": "search",
        "context_id": None,
        "context_name": None,
        "results_message_id": results_message_id,
    }


def set_artist_state(
    user_id: int, artist_id: int, artist_name: str, offset: int, has_next: bool,
    results_message_id: int = None
) -> None:
    prev = _states.get(user_id, {})
    _states[user_id] = {
        "query": prev.get("query", ""),
        "search_type": prev.get("search_type", "artist"),
        "offset": offset,
        "has_next": has_next,
        "mode": "artist_tracks",
        "context_id": artist_id,
        "context_name": artist_name,
        "results_message_id": results_message_id,
    }


# Буфер отправленных треков: {chat_id: {message_id: {title, artist, deezer_id, ts}}}
_track_buffer: dict = {}

BUFFER_TTL = 600  # 10 минут


def _cleanup_buffer(chat_id: int) -> None:
    now = time.time()
    buf = _track_buffer.get(chat_id, {})
    expired = [mid for mid, data in buf.items() if now - data["ts"] > BUFFER_TTL]
    for mid in expired:
        del buf[mid]


def add_track_to_buffer(
    chat_id: int, message_id: int, title: str, artist: str, deezer_id: int
) -> None:
    _cleanup_buffer(chat_id)
    if chat_id not in _track_buffer:
        _track_buffer[chat_id] = {}
    _track_buffer[chat_id][message_id] = {
        "title": title,
        "artist": artist,
        "deezer_id": deezer_id,
        "ts": time.time(),
    }


def get_track_from_buffer(chat_id: int, message_id: int) -> Optional[dict]:
    _cleanup_buffer(chat_id)
    return _track_buffer.get(chat_id, {}).get(message_id)


def update_track_buffer_message_id(
    chat_id: int, old_message_id: int, new_message_id: int
) -> None:
    """После замены трека переносим запись на новый message_id."""
    buf = _track_buffer.get(chat_id, {})
    if old_message_id in buf:
        buf[new_message_id] = buf.pop(old_message_id)
        buf[new_message_id]["ts"] = time.time()

_stop_flags: Dict[int, bool] = {}

def set_stop(chat_id: int) -> None:
    _stop_flags[chat_id] = True

def clear_stop(chat_id: int) -> None:
    if chat_id in _stop_flags:
        del _stop_flags[chat_id]

def should_stop(chat_id: int) -> bool:
    return _stop_flags.get(chat_id, False)