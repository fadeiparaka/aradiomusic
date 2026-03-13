import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

THUMB_PATH = str(BASE_DIR / "media" / "Frame 5.jpg")

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
TRACKS_PER_PAGE: int = int(os.getenv("TRACKS_PER_PAGE", 6))
ALBUM_SEND_DELAY: float = float(os.getenv("ALBUM_SEND_DELAY", 0.5))


DEEZER_API_URL = "https://api.deezer.com"

# Сообщения
MSG_WELCOME = (
    "Ищи музыку и слушай в телеграме.\n\n"
    "Напиши название трека, артиста или альбома.\n\n"
    "Наслаждайся,\n@fadeiparaka"
)

MSG_SEARCHING = "Ищу <b>{query}</b>..."
MSG_NO_RESULTS = "Ничего не нашёл. Я тупой. Напиши конкретнее."
MSG_YT_FALLBACK = "🔍 В Deezer не нашёл, вот варианты с YouTube:"
MSG_RESULTS_HEADER = "<b>{query}</b>:"
MSG_ARTIST_HEADER = "Топ треки <b>{name}</b>:"
MSG_DOWNLOADING = "Подожди, бля..."
MSG_SENDING_ALBUM = "Скидываю альбом <b>{title}</b> ({count} треков)..."
MSG_ALBUM_DONE = "Альбом <b>{title}</b>"
MSG_NO_STREAM = "❌ Трек недоступен для скачивания."
MSG_ERROR = "❌ Произошла ошибка. Попробуй ещё раз."
MSG_SC_ERROR = "❌ Ошибка Deezer. Попробуй позже."
MSG_NO_STATE = "🔍 Напиши запрос для поиска."

# Кнопки
BTN_TRACK = "🎵 Трек"
BTN_ARTIST = "👤 Артист"
BTN_ALBUM = "💿 Альбом"
BTN_TRACK_ACTIVE = "• 🎵 Трек"
BTN_ARTIST_ACTIVE = "• 👤 Артист"
BTN_ALBUM_ACTIVE = "• 💿 Альбом"
BTN_PREV = "<--"
BTN_NEXT = "-->"
BTN_BACK = "НАЗАД."
BTN_PAGE = "{page}"

MSG_YT_PLAYLIST_SENDING = "Альбом с ютюба…"
MSG_YT_PLAYLIST_DONE = "Готово."
MSG_YT_PLAYLIST_STOPPED = "СТОПНУЛ."
MSG_YT_VIDEO_SENDING = "Качаю трек с ютюба..."
MSG_YT_VIDEO_FAILED = "Я очень-очень глупый. Не смог прочитать эту ссылку."
MSG_STOP_NO_TASK = "Сейчас нечего останавливать."
MSG_STOP_OK = "Ну ок."
