import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import yt_dlp

from aiogram.types import Message
from aiogram.filters import Command

import src.state_manager as sm
import src.config as config
from src.downloader import download_track, delete_file
from aiogram.types import FSInputFile

router = Router()

# Сообщения
MSG_RETRACK_HEADER = "Замени <b>{artist} — {title}</b>:"
MSG_RETRACK_NOT_FOUND = "❌ Ответь на недавнюю музыку. Я понимаю только последнее."
MSG_RETRACK_SEARCHING = "Меняю..."
MSG_RETRACK_NO_RESULTS = "❌ Ниче не нашёл."
MSG_RETRACK_DOWNLOADING = "Подожди, бля..."


def _search_youtube_candidates(query: str, limit: int = 5) -> list[dict]:
    """Возвращает список кандидатов без скачивания."""
    info_opts = {
        "quiet": True,
        "no_warnings": True,
        "verbose": False,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        if isinstance(info, dict) and info.get("_type") == "playlist":
            return [e for e in info.get("entries", []) if e]
    except Exception as e:
        logging.error("yt-dlp retrack search error: %s", e)
    return []

async def _preload_next_page(chat_id: int, orig_msg_id: int, query: str, current_count: int, next_offset: int):
    """Тихо подгружает следующую страницу в кеш."""
    if current_count >= next_offset + 5:
        return  # уже есть
    loop = asyncio.get_event_loop()
    new_entries = await loop.run_in_executor(
        None, _search_youtube_candidates, query, next_offset + 5
    )
    cache = _candidates_cache.get(chat_id, {}).get(orig_msg_id)
    if cache and len(new_entries) > len(cache["entries"]):
        cache["entries"] = new_entries
        logging.info("PRELOAD done chat_id=%d orig=%d entries=%d", chat_id, orig_msg_id, len(new_entries))

def _format_duration(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return "?:??"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

def _build_keyboard(candidates: list[dict], offset: int, chat_id: int, orig_msg_id: int) -> InlineKeyboardMarkup:
    page = candidates[offset:offset + 5]
    buttons = []
    for i, c in enumerate(page):
        dur = _format_duration(c.get("duration"))
        label = f"[{dur}] {c.get('uploader', '?')} — {c.get('title', '?')}"[:64]
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"rt:{orig_msg_id}:{offset + i}"
            )
        ])
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f"rtp:{orig_msg_id}:{offset - 5}"))
    # Показываем "Ещё" если страница полная — значит возможно есть ещё
    if len(page) == 5:
        nav.append(InlineKeyboardButton(text="Ещё →", callback_data=f"rtp:{orig_msg_id}:{offset + 5}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Изменяем структуру кеша: теперь хранит query + накопленные entries
# {chat_id: {orig_msg_id: {"query": str, "entries": list}}}
_candidates_cache: dict = {}


@router.message(Command("r"))
async def cmd_retrack(message: Message):
    logging.info("CMD /r triggered, reply=%r", message.reply_to_message)
    _candidates_cache[message.chat.id][orig_msg_id] = {
        "query": query,
        "entries": candidates,
        "header": MSG_RETRACK_HEADER.format(artist=artist, title=title),
    }

    reply = message.reply_to_message
    if not reply:
        await message.answer(MSG_RETRACK_NOT_FOUND, parse_mode="HTML")
        return

    logging.info("reply content_type=%r, audio=%r, document=%r", reply.content_type, reply.audio, reply.document)

    if not reply.audio and not reply.document:
        await message.answer(MSG_RETRACK_NOT_FOUND, parse_mode="HTML")
        return

    orig_msg_id = reply.message_id
    track_data = sm.get_track_from_buffer(message.chat.id, orig_msg_id)

    if not track_data:
        await message.answer(MSG_RETRACK_NOT_FOUND, parse_mode="HTML")
        return

    title = track_data["title"]
    artist = track_data["artist"]
    query = f"{artist} {title}"

    loading = await message.answer(MSG_RETRACK_SEARCHING, parse_mode="HTML")

    loop = asyncio.get_event_loop()
    candidates = await loop.run_in_executor(
        None, _search_youtube_candidates, query, 5  # ← только первые 5
    )

    await loading.delete()

    if not candidates:
        await message.answer(MSG_RETRACK_NO_RESULTS, parse_mode="HTML")
        return

    # Кешируем с запросом
    if message.chat.id not in _candidates_cache:
        _candidates_cache[message.chat.id] = {}
    _candidates_cache[message.chat.id][orig_msg_id] = {
        "query": query,
        "entries": candidates,
    }

    keyboard = _build_keyboard(candidates, offset=0, chat_id=message.chat.id, orig_msg_id=orig_msg_id)

    await message.answer(
        MSG_RETRACK_HEADER.format(artist=artist, title=title),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    asyncio.create_task(
        _preload_next_page(message.chat.id, orig_msg_id, query, len(candidates), 5)
    )

@router.callback_query(F.data.startswith("rtp:"))
async def handle_retrack_page(cb: CallbackQuery):
    await cb.answer()  # сразу — иначе Telegram отклонит через 10 сек

    _, orig_msg_id_str, offset_str = cb.data.split(":")
    orig_msg_id = int(orig_msg_id_str)
    offset = int(offset_str)

    cache = _candidates_cache.get(cb.message.chat.id, {}).get(orig_msg_id)
    if not cache:
        await cb.message.edit_text("Сессия устарела, запусти заново.", parse_mode="HTML")
        return

    entries = cache["entries"]
    query = cache["query"]
    header = cache.get("header", "Выбери вариант:")

    # Если preload не успел — грузим с отдельным сообщением-лоадером
    if len(entries) < offset + 5:
        loading = await cb.message.answer(config.MSG_DOWNLOADING, parse_mode="HTML")
        loop = asyncio.get_event_loop()
        new_entries = await loop.run_in_executor(
            None, _search_youtube_candidates, query, offset + 5
        )
        try:
            await loading.delete()
        except Exception:
            pass
        if len(new_entries) > len(entries):
            cache["entries"] = new_entries
            entries = new_entries

    keyboard = _build_keyboard(entries, offset=offset, chat_id=cb.message.chat.id, orig_msg_id=orig_msg_id)
    await cb.message.edit_text(header, parse_mode="HTML", reply_markup=keyboard)

    # Фоновая подгрузка следующей страницы
    asyncio.create_task(
        _preload_next_page(cb.message.chat.id, orig_msg_id, query, len(entries), offset + 5)
    )

@router.callback_query(F.data.startswith("rt:"))
async def handle_retrack_pick(cb: CallbackQuery):
    """Пользователь выбрал конкретный вариант замены."""
    _, orig_msg_id_str, idx_str = cb.data.split(":")
    orig_msg_id = int(orig_msg_id_str)
    idx = int(idx_str)

    candidates = (_candidates_cache.get(cb.message.chat.id, {}).get(orig_msg_id) or {}).get("entries")
    if not candidates or idx >= len(candidates):
        await cb.answer("Сессия устарела, запусти /r заново.")
        return

    chosen = candidates[idx]
    video_url = chosen.get("webpage_url") or chosen.get("url")

    track_data = sm.get_track_from_buffer(cb.message.chat.id, orig_msg_id)

    if track_data:
        # режим /r — заменяем существующий трек
        title = track_data["title"]
        artist = track_data["artist"]
        deezer_id = track_data["deezer_id"]
    else:
        # режим YouTube-fallback поиска — трека в буфере нет
        title = chosen.get("title") or chosen.get("fulltitle") or "Unknown"
        artist = chosen.get("uploader") or chosen.get("channel") or ""
        deezer_id = abs(hash(chosen.get("id", "0"))) % (10 ** 9)

    await cb.message.edit_text(MSG_RETRACK_DOWNLOADING, parse_mode="HTML")

    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(None, _download_direct, video_url, deezer_id)

    if not path:
        await cb.message.edit_text(config.MSG_NO_STREAM, parse_mode="HTML")
        return

    # В режиме /r удаляем старое аудио; в режиме поиска — нечего удалять
    if track_data:
        try:
            await cb.message.bot.delete_message(cb.message.chat.id, orig_msg_id)
        except Exception:
            pass

    sent = await cb.message.answer_audio(
        FSInputFile(path),
        title=title,
        performer=artist,
        thumbnail=FSInputFile(config.THUMB_PATH),
    )
    delete_file(path)

    if track_data:
        sm.update_track_buffer_message_id(cb.message.chat.id, orig_msg_id, sent.message_id)
    else:
        sm.add_track_to_buffer(cb.message.chat.id, sent.message_id, title, artist, deezer_id)

    _candidates_cache.get(cb.message.chat.id, {}).pop(orig_msg_id, None)

    try:
        await cb.message.delete()
    except Exception:
        pass

    await cb.answer()

def _download_direct(video_url: str, track_id: int) -> str | None:
    """Скачивает по прямому YouTube URL без поиска."""
    from pathlib import Path
    from src.downloader import TMP_DIR
    import os

    output_path = str(TMP_DIR / f"retrack_{track_id}")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "verbose": False,
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
            ydl.download([video_url])
        mp3 = output_path + ".mp3"
        return mp3 if os.path.exists(mp3) else None
    except Exception as e:
        logging.error("yt-dlp direct download error: %s", e)
        return None

@router.message(Command("test_r"))
async def cmd_test_r(message: Message):
    await message.answer("test_r OK")