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
