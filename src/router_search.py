import asyncio
import re

import yt_dlp
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)

from src import config
from src import state_manager as sm
from src.config import (
    MSG_YT_PLAYLIST_SENDING,
    MSG_YT_PLAYLIST_DONE,
    MSG_YT_PLAYLIST_STOPPED,
    MSG_YT_VIDEO_SENDING,
    MSG_YT_VIDEO_FAILED,
    MSG_STOP_NO_TASK,
    MSG_STOP_OK,
    ALBUM_SEND_DELAY,
)
from src import deezer as sc
from src.downloader import download_track, delete_file


router = Router()

YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/\S+$"
)


async def _typing_loop(bot, chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await bot.send_chat_action(chat_id, "upload_document")
        await asyncio.sleep(4)


def _truncate(text: str, max_len: int = 46) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def _build_item_buttons(items: list, search_type: str, mode: str) -> list:
    rows = []
    for item in items:
        if search_type == "artist" and mode == "search":
            label = _truncate(f"👤 {item.get('name', 'Unknown')}")
            cb = f"a:{item['id']}"
        elif search_type == "album" and mode == "search":
            title = item.get("title", "Unknown")
            artist = item.get("artist", {}).get("name", "")
            nb_tracks = item.get("nb_tracks", "?")
            label = _truncate(f"💿 {artist} — {title} ({nb_tracks} шт.)")
            cb = f"al:{item['id']}"
        else:
            title = item.get("title", "Unknown")
            artist = item.get("artist", {}).get("name", "")
            label = _truncate(f"{artist} — {title}")
            cb = f"t:{item['id']}"
        rows.append([InlineKeyboardButton(text=label, callback_data=cb)])
    return rows


def _build_type_row(active: str) -> list:
    mapping = {
        "track": (config.BTN_TRACK_ACTIVE if active == "track" else config.BTN_TRACK, "type:track"),
        "artist": (config.BTN_ARTIST_ACTIVE if active == "artist" else config.BTN_ARTIST, "type:artist"),
        "album": (config.BTN_ALBUM_ACTIVE if active == "album" else config.BTN_ALBUM, "type:album"),
    }
    return [InlineKeyboardButton(text=label, callback_data=cb) for label, cb in mapping.values()]


def _build_pagination_row(offset: int, has_next: bool) -> list:
    if offset == 0 and not has_next:
        return []
    page = offset // config.TRACKS_PER_PAGE + 1
    buttons = []
    if offset > 0:
        buttons.append(InlineKeyboardButton(text=config.BTN_PREV, callback_data="page:prev"))
    buttons.append(InlineKeyboardButton(
        text=config.BTN_PAGE.format(page=page),
        callback_data="noop"
    ))
    if has_next:
        buttons.append(InlineKeyboardButton(text=config.BTN_NEXT, callback_data="page:next"))
    return buttons


def build_keyboard(
    items: list, search_type: str, offset: int, has_next: bool, mode: str = "search"
) -> InlineKeyboardMarkup:
    rows = _build_item_buttons(items, search_type, mode)
    if mode == "artist_tracks":
        rows.append([InlineKeyboardButton(text=config.BTN_BACK, callback_data="back")])
    else:
        rows.append(_build_type_row(search_type))
    pagination = _build_pagination_row(offset, has_next)
    if pagination:
        rows.append(pagination)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _do_search(user_id: int, query: str, search_type: str, offset: int) -> tuple:
    try:
        if search_type == "track":
            items, has_next = await sc.search_tracks(query, offset)
        elif search_type == "artist":
            items, has_next = await sc.search_artists(query, offset)
        else:
            items, has_next = await sc.search_albums(query, offset)
    except Exception:
        return config.MSG_SC_ERROR, None
    if not items:
        return config.MSG_NO_RESULTS.format(query=query), None
    sm.set_search_state(user_id, query, search_type, offset, has_next)
    keyboard = build_keyboard(items, search_type, offset, has_next)
    return config.MSG_RESULTS_HEADER.format(query=query), keyboard


async def _show_artist_tracks(cb: CallbackQuery, artist_id: int, artist_name: str, offset: int) -> None:
    try:
        tracks, has_next = await sc.get_artist_top_tracks(artist_id, offset)
    except Exception:
        await cb.message.edit_text(config.MSG_SC_ERROR, parse_mode="HTML")
        return
    if not tracks:
        await cb.message.edit_text(
            config.MSG_NO_RESULTS.format(query=artist_name), parse_mode="HTML"
        )
        return
    sm.set_artist_state(cb.from_user.id, artist_id, artist_name, offset, has_next)
    keyboard = build_keyboard(tracks, "track", offset, has_next, mode="artist_tracks")
    await cb.message.edit_text(
        config.MSG_ARTIST_HEADER.format(name=artist_name),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _delete_results_message(cb: CallbackQuery) -> None:
    state = sm.get_state(cb.from_user.id)
    if state and state.get("results_message_id"):
        try:
            await cb.message.bot.delete_message(cb.message.chat.id, state["results_message_id"])
            state["results_message_id"] = None
        except Exception:
            pass


# ─── Команды / старт ────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(config.MSG_WELCOME, parse_mode="HTML")


@router.message(Command("stop"))
async def handle_stop(message: Message):
    chat_id = message.chat.id
    if not sm.should_stop(chat_id):
        sm.set_stop(chat_id)
        await message.answer(MSG_STOP_OK, parse_mode="HTML")
    else:
        await message.answer(MSG_STOP_NO_TASK, parse_mode="HTML")


# ─── YouTube: голый URL ─────────────────────────────────────────────────────


@router.message(F.text.regexp(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/\S+$"))
async def handle_youtube_url(message: Message):
    text = (message.text or "").strip()
    url = text

    if "list=" in url:
        await handle_youtube_playlist(message, url)
    else:
        await handle_youtube_video(message, url)


async def handle_youtube_video(message: Message, url: str):
    loading_msg = await message.answer(MSG_YT_VIDEO_SENDING, parse_mode="HTML")
    try:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "aradio_music/tmp/%(id)s.%(ext)s",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "verbose": False,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base_path = ydl.prepare_filename(info)

        if base_path.rsplit(".", 1)[-1] != "mp3":
            file_path = base_path.rsplit(".", 1)[0] + ".mp3"
        else:
            file_path = base_path

        title = info.get("track") or info.get("title") or "Audio"
        performer = info.get("artist") or info.get("uploader") or info.get("channel") or ""

        await message.bot.send_chat_action(message.chat.id, "upload_audio")
        await message.answer_audio(
            audio=FSInputFile(file_path),
            title=title,
            performer=performer,
            thumbnail=FSInputFile(config.THUMB_PATH),
        )

        delete_file(file_path) 

    except Exception as e:
        await message.answer(
            f"<b>Ошибка при отправке файла:</b> {e}",
            parse_mode="HTML",
        )
        raise
    finally:
        try:
            await loading_msg.delete()
        except Exception:
            pass

async def handle_youtube_playlist(message: Message, url: str):
    chat_id = message.chat.id
    sm.clear_stop(chat_id)

    info_msg = await message.answer(MSG_YT_PLAYLIST_SENDING, parse_mode="HTML")

    stop_event = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_loop(message.bot, message.chat.id, stop_event)
    )

    try:
        with yt_dlp.YoutubeDL({"extract_flat": False, "quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries") or []
        for entry in entries:
            if sm.should_stop(chat_id):
                break

            video_url = entry.get("webpage_url")
            if not video_url:
                continue

            try:
                ydl_opts_dl = {
                    "format": "bestaudio/best",
                    "outtmpl": "aradio_music/tmp/%(id)s.%(ext)s",
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "verbose": False,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
                with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl:
                    vinfo = ydl.extract_info(video_url, download=True)
                    base_path = ydl.prepare_filename(vinfo)

                if base_path.rsplit(".", 1)[-1] != "mp3":
                    file_path = base_path.rsplit(".", 1)[0] + ".mp3"
                else:
                    file_path = base_path

                title = vinfo.get("track") or vinfo.get("title") or entry.get("title") or "Audio"
                performer = (
                    vinfo.get("artist")
                    or vinfo.get("uploader")
                    or vinfo.get("channel")
                    or entry.get("uploader")
                    or entry.get("channel")
                    or ""
                )

                await message.bot.send_chat_action(message.chat.id, "upload_audio")
                await message.answer_audio(
                    audio=FSInputFile(file_path),
                    title=title,
                    performer=performer,
                    thumbnail=FSInputFile(config.THUMB_PATH),
                )

                delete_file(file_path) 

                await asyncio.sleep(ALBUM_SEND_DELAY)
            except Exception as e:
                await message.answer(
                    f"<b>Ошибка при скачивании трека плейлиста:</b> {e}",
                    parse_mode="HTML",
                )
                continue
    finally:
        stop_event.set()
        typing_task.cancel()
        try:
            await info_msg.delete()
        except Exception:
            pass

        stopped = sm.should_stop(chat_id)
        sm.clear_stop(chat_id)

        if stopped:
            await message.answer(MSG_YT_PLAYLIST_STOPPED, parse_mode="HTML")
        else:
            await message.answer(MSG_YT_PLAYLIST_DONE, parse_mode="HTML")

# ─── Поиск по тексту ────────────────────────────────────────────────────────


@router.message(F.text)
async def handle_search(message: Message):
    # игнорируем команды и YouTube‑URL
    if message.text.startswith("/"):
        return
    if YOUTUBE_URL_RE.match(message.text.strip()):
        return

    query = message.text.strip()
    loading = await message.answer(
        config.MSG_SEARCHING.format(query=query), parse_mode="HTML"
    )
    text, keyboard = await _do_search(message.from_user.id, query, "track", 0)
    await loading.delete()
    if keyboard:
        sent = await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        state = sm.get_state(message.from_user.id)
        if state:
            state["results_message_id"] = sent.message_id
    else:
        await message.answer(text, parse_mode="HTML")


# ─── Callbacks ──────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("type:"))
async def handle_type_switch(cb: CallbackQuery):
    search_type = cb.data.split(":")[1]
    state = sm.get_state(cb.from_user.id)
    if not state:
        await cb.answer()
        await cb.message.edit_text(config.MSG_NO_STATE, parse_mode="HTML")
        return
    sm.update_search_type(cb.from_user.id, search_type)
    await cb.answer()
    text, keyboard = await _do_search(cb.from_user.id, state["query"], search_type, 0)
    await cb.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    new_state = sm.get_state(cb.from_user.id)
    if new_state:
        new_state["results_message_id"] = cb.message.message_id


@router.callback_query(F.data == "page:next")
async def handle_next(cb: CallbackQuery):
    state = sm.get_state(cb.from_user.id)
    if not state:
        await cb.answer()
        return
    new_offset = state["offset"] + config.TRACKS_PER_PAGE
    await cb.answer()
    if state["mode"] == "artist_tracks":
        await _show_artist_tracks(cb, state["context_id"], state["context_name"], new_offset)
    else:
        text, keyboard = await _do_search(
            cb.from_user.id, state["query"], state["search_type"], new_offset
        )
        await cb.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "page:prev")
async def handle_prev(cb: CallbackQuery):
    state = sm.get_state(cb.from_user.id)
    if not state:
        await cb.answer()
        return
    new_offset = max(0, state["offset"] - config.TRACKS_PER_PAGE)
    await cb.answer()
    if state["mode"] == "artist_tracks":
        await _show_artist_tracks(cb, state["context_id"], state["context_name"], new_offset)
    else:
        text, keyboard = await _do_search(
            cb.from_user.id, state["query"], state["search_type"], new_offset
        )
        await cb.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "back")
async def handle_back(cb: CallbackQuery):
    state = sm.get_state(cb.from_user.id)
    if not state:
        await cb.answer()
        return
    await cb.answer()
    text, keyboard = await _do_search(
        cb.from_user.id, state["query"], state["search_type"], 0
    )
    await cb.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("a:"))
async def handle_artist(cb: CallbackQuery):
    artist_id = int(cb.data.split(":")[1])
    await cb.answer()
    try:
        artist_data = await sc.get_artist(artist_id)
        artist_name = artist_data.get("name", "Unknown")
    except Exception:
        await cb.message.edit_text(config.MSG_SC_ERROR, parse_mode="HTML")
        return
    await _show_artist_tracks(cb, artist_id, artist_name, offset=0)


@router.callback_query(F.data.startswith("al:"))
async def handle_album(cb: CallbackQuery):
    album_id = int(cb.data.split(":")[1])
    await cb.answer()

    try:
        tracks, album_title, album_artist = await sc.get_album_tracks(album_id)
    except Exception:
        await cb.message.edit_text(config.MSG_SC_ERROR, parse_mode="HTML")
        return

    if not tracks:
        await cb.message.answer(
            config.MSG_NO_RESULTS.format(query=album_title),
            parse_mode="HTML",
        )
        return

    loading = await cb.message.answer(
        config.MSG_SENDING_ALBUM.format(title=album_title, count=len(tracks)),
        parse_mode="HTML",
    )

    stop_event = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_loop(cb.message.bot, cb.message.chat.id, stop_event)
    )

    for track in tracks:
        track_id = track["id"]
        title = track.get("title", "Unknown")
        path = await download_track(track_id, title=title, artist=album_artist)
        if path:
            sent = await cb.message.answer_audio(
                FSInputFile(path),
                title=title,
                performer=album_artist,
                thumbnail=FSInputFile(config.THUMB_PATH),
            )
            delete_file(path)
            sm.add_track_to_buffer(
                cb.message.chat.id, sent.message_id, title, album_artist, track_id
            )

        await asyncio.sleep(config.ALBUM_SEND_DELAY)

    stop_event.set()
    typing_task.cancel()
    try:
        await loading.delete()
    except Exception:
        pass

    await cb.message.answer(
        config.MSG_ALBUM_DONE.format(title=album_title),
        parse_mode="HTML",
    )

    await _delete_results_message(cb)


@router.callback_query(F.data.startswith("t:"))
async def handle_track(cb: CallbackQuery):
    track_id = int(cb.data.split(":")[1])
    await cb.answer()
    loading = await cb.message.answer(config.MSG_DOWNLOADING, parse_mode="HTML")

    try:
        track_data = await sc.get_track(track_id)
        title = track_data.get("title", "")
        artist = track_data.get("artist", {}).get("name", "")
    except Exception:
        title, artist = "", ""

    stop_event = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_loop(cb.message.bot, cb.message.chat.id, stop_event)
    )

    path = await download_track(track_id, title=title, artist=artist)

    stop_event.set()
    typing_task.cancel()
    try:
        await loading.delete()
    except Exception:
        pass

    if not path:
        await cb.message.answer(config.MSG_NO_STREAM, parse_mode="HTML")
        return

    sent = await cb.message.answer_audio(
        FSInputFile(path),
        title=title,
        performer=artist,
        thumbnail=FSInputFile(config.THUMB_PATH),
    )
    delete_file(path)

    sm.add_track_to_buffer(
        cb.message.chat.id,
        sent.message_id,
        title,
        artist,
        track_id,
    )

    state = sm.get_state(cb.from_user.id)
    if state and state.get("results_message_id"):
        try:
            await cb.message.bot.delete_message(cb.message.chat.id, state["results_message_id"])
            state["results_message_id"] = None
        except Exception:
            pass


@router.callback_query(F.data == "noop")
async def handle_noop(cb: CallbackQuery):
    await cb.answer()
