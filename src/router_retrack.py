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
MSG_RETRACK_HEADER = "Замените <b>{artist} — {title}</b>:"
MSG_RETRACK_NOT_FOUND = "❌ Ответь на недавнюю музыку. Я понимаю только последнее."
MSG_RETRACK_SEARCHING = "Меняю..."
MSG_RETRACK_NO_RESULTS = "❌ Ниче не нашёл."
MSG_RETRACK_DOWNLOADING = "Ща-ща..."


def _search_youtube_candidates(query: str, limit: int = 50) -> list[dict]:
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
    if offset + 5 < len(candidates):
        nav.append(InlineKeyboardButton(text="Ещё →", callback_data=f"rtp:{orig_msg_id}:{offset + 5}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Временное хранилище кандидатов: {chat_id: {orig_msg_id: [candidates]}}
_candidates_cache: dict = {}


@router.message(Command("r"))
async def cmd_retrack(message: Message):
    logging.info("CMD /r triggered, reply=%r", message.reply_to_message)
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

    loading = await message.answer(MSG_RETRACK_SEARCHING, parse_mode="HTML")

    loop = asyncio.get_event_loop()
    candidates = await loop.run_in_executor(
        None, _search_youtube_candidates, f"{artist} {title}"
    )

    await loading.delete()

    if not candidates:
        await message.answer(MSG_RETRACK_NO_RESULTS, parse_mode="HTML")
        return

    # Кешируем кандидатов
    if message.chat.id not in _candidates_cache:
        _candidates_cache[message.chat.id] = {}
    _candidates_cache[message.chat.id][orig_msg_id] = candidates

    keyboard = _build_keyboard(candidates, offset=0, chat_id=message.chat.id, orig_msg_id=orig_msg_id)

    await message.answer(
        MSG_RETRACK_HEADER.format(artist=artist, title=title),
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("rtp:"))
async def handle_retrack_page(cb: CallbackQuery):
    """Пагинация кандидатов."""
    _, orig_msg_id_str, offset_str = cb.data.split(":")
    orig_msg_id = int(orig_msg_id_str)
    offset = int(offset_str)

    candidates = _candidates_cache.get(cb.message.chat.id, {}).get(orig_msg_id)
    if not candidates:
        await cb.answer("Сессия устарела, запусти /r заново.")
        return

    track_data = sm.get_track_from_buffer(cb.message.chat.id, orig_msg_id)
    title = track_data["title"] if track_data else "?"
    artist = track_data["artist"] if track_data else "?"

    keyboard = _build_keyboard(candidates, offset=offset, chat_id=cb.message.chat.id, orig_msg_id=orig_msg_id)
    await cb.message.edit_text(
        MSG_RETRACK_HEADER.format(artist=artist, title=title),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("rt:"))
async def handle_retrack_pick(cb: CallbackQuery):
    """Пользователь выбрал конкретный вариант замены."""
    _, orig_msg_id_str, idx_str = cb.data.split(":")
    orig_msg_id = int(orig_msg_id_str)
    idx = int(idx_str)

    candidates = _candidates_cache.get(cb.message.chat.id, {}).get(orig_msg_id)
    if not candidates or idx >= len(candidates):
        await cb.answer("Сессия устарела, запусти /r заново.")
        return

    track_data = sm.get_track_from_buffer(cb.message.chat.id, orig_msg_id)
    if not track_data:
        await cb.answer("Сессия устарела, запусти /r заново.")
        return

    chosen = candidates[idx]
    video_url = chosen.get("webpage_url") or chosen.get("url")
    title = track_data["title"]
    artist = track_data["artist"]
    deezer_id = track_data["deezer_id"]

    await cb.message.edit_text(MSG_RETRACK_DOWNLOADING, parse_mode="HTML")

    # Скачиваем по прямому YouTube URL
    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(None, _download_direct, video_url, deezer_id)

    if not path:
        await cb.message.edit_text(config.MSG_NO_STREAM, parse_mode="HTML")
        return

    # Удаляем старое аудио
    try:
        await cb.message.bot.delete_message(cb.message.chat.id, orig_msg_id)
    except Exception:
        pass

    # Отправляем новое
    sent = await cb.message.answer_audio(
        FSInputFile(path),
        title=title,
        performer=artist,
        thumbnail=FSInputFile(config.THUMB_PATH),
    )
    delete_file(path)

    # Обновляем буфер на новый message_id
    sm.update_track_buffer_message_id(cb.message.chat.id, orig_msg_id, sent.message_id)

    # Чистим кеш кандидатов
    _candidates_cache.get(cb.message.chat.id, {}).pop(orig_msg_id, None)

    # Удаляем сообщение с выбором
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