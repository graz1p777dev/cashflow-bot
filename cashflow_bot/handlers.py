"""Диалог бота: меню, рассказ об игре, запись, свои брони.

Состояние шага записи лежит в SQLite (storage.Storage), а не в памяти
процесса: Railway перезапускает бота при каждом деплое, и человек не
должен начинать запись заново.
"""

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from . import keyboards as kb
from . import templates as t
from .crm import crm
from .storage import Storage

log = logging.getLogger(__name__)

router = Router()
store = Storage()

PHONE_RE = re.compile(r"^\+?[\d\s\-()]{9,20}$")


async def _reply(message: Message, text: str, **kwargs) -> None:
    """Ответ человеку + копия в CRM: менеджер видит переписку в сделке."""
    await message.answer(text, **kwargs)
    await crm.log_message(message.chat.id, "out", text)


async def _edit(call: CallbackQuery, text: str, markup) -> None:
    if isinstance(call.message, Message):
        try:
            await call.message.edit_text(text, reply_markup=markup)
        except Exception:
            # Сообщение могло быть удалено или не изменилось — тогда новым.
            await call.message.answer(text, reply_markup=markup)
        await crm.log_message(call.message.chat.id, "out", text)
    await call.answer()


# ─── Вход ────────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def start(message: Message) -> None:
    if not message.from_user:
        return
    is_new = store.touch_user(message.chat.id, message.from_user.username)
    store.set_step(message.chat.id, "menu")
    await crm.log_message(message.chat.id, "in", "/start")
    await _reply(
        message,
        t.GREETING if is_new else t.RETURNING_GREETING,
        reply_markup=kb.MAIN_MENU,
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await _reply(message, t.faq_text(), reply_markup=kb.MAIN_MENU)


@router.callback_query(F.data == "menu")
async def menu(call: CallbackQuery) -> None:
    await _edit(call, t.RETURNING_GREETING, kb.MAIN_MENU)


# ─── Рассказ об игре ─────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("about:"))
async def about(call: CallbackQuery) -> None:
    step = int((call.data or "about:0").split(":")[1])
    step = max(0, min(step, len(t.ABOUT_SCREENS) - 1))
    await _edit(call, t.ABOUT_SCREENS[step], kb.about(step))


@router.callback_query(F.data == "faq")
async def faq(call: CallbackQuery) -> None:
    await _edit(call, t.faq_text(), kb.TO_GAMES)


# ─── Запись: выбор игры ──────────────────────────────────────────────────────


@router.callback_query(F.data == "games")
async def games(call: CallbackQuery) -> None:
    items = await crm.games()
    if items is None:
        await _edit(call, t.CRM_OFFLINE, kb.BACK_TO_MENU)
        return

    available = [g for g in items if g["seatsFree"] > 0]
    if not available:
        await _edit(call, t.GAMES_EMPTY, kb.BACK_TO_MENU)
        return

    # Человек дошёл до списка дат — с этого момента его есть смысл дожимать.
    store.set_step(call.message.chat.id if call.message else 0, "games")
    await _edit(call, t.GAMES_HEADER, kb.games(available))


@router.callback_query(F.data.startswith("game:"))
async def pick_game(call: CallbackQuery) -> None:
    game_id = (call.data or "").split(":", 1)[1]
    game = await crm.game(game_id)
    if game is None:
        await _edit(call, t.GAME_CLOSED, kb.TO_GAMES)
        return
    if game["seatsFree"] <= 0:
        await _edit(call, t.NO_SEATS, kb.TO_GAMES)
        return

    chat_id = call.message.chat.id if call.message else 0
    store.set_step(chat_id, "seats", game_id=game_id)
    await _edit(
        call,
        f"{t.game_card(game)}\n\n{t.ASK_SEATS}",
        kb.seats(game_id, game["seatsFree"]),
    )


@router.callback_query(F.data.startswith("seats:"))
async def pick_seats(call: CallbackQuery) -> None:
    _, game_id, raw = (call.data or "seats::1").split(":")
    seats = max(1, min(int(raw), 10))
    chat_id = call.message.chat.id if call.message else 0

    known = store.get_user(chat_id) or {}
    store.set_step(chat_id, "name", game_id=game_id, seats=seats)

    # Имя уже знаем с прошлой записи — не спрашиваем второй раз.
    if known.get("name"):
        store.set_step(chat_id, "phone", game_id=game_id, seats=seats)
        if known.get("phone"):
            await call.answer()
            if isinstance(call.message, Message):
                # username берём у нажавшего кнопку: в call.message
                # from_user — сам бот, а не человек.
                await _finish_booking(
                    call.message,
                    known["name"],
                    known["phone"],
                    username=call.from_user.username if call.from_user else None,
                )
            return
        await _edit(call, t.ASK_PHONE, None)
        if isinstance(call.message, Message):
            await call.message.answer(t.ASK_PHONE, reply_markup=kb.PHONE_REQUEST)
        return

    await _edit(call, t.ASK_NAME, None)


# ─── Запись: имя и телефон ───────────────────────────────────────────────────


@router.message(F.contact)
async def contact(message: Message) -> None:
    funnel = store.get_funnel(message.chat.id)
    if not funnel or funnel["step"] != "phone" or not message.contact:
        return
    phone = message.contact.phone_number
    store.save_contact(message.chat.id, None, phone)
    await crm.log_message(message.chat.id, "in", f"телефон: {phone}")
    user = store.get_user(message.chat.id) or {}
    await _finish_booking(message, user.get("name") or "Гость", phone)


@router.message(F.text)
async def text(message: Message) -> None:
    if not message.text:
        return
    await crm.log_message(message.chat.id, "in", message.text)
    funnel = store.get_funnel(message.chat.id)
    step = funnel["step"] if funnel else "menu"

    if step == "name":
        name = message.text.strip()
        if len(name) < 2 or name.startswith("/"):
            await _reply(message, t.NAME_TOO_SHORT)
            return
        store.save_contact(message.chat.id, name[:200], None)
        store.set_step(message.chat.id, "phone")
        await _reply(message, t.ASK_PHONE, reply_markup=kb.PHONE_REQUEST)
        return

    if step == "phone":
        phone = message.text.strip()
        if not PHONE_RE.match(phone):
            await _reply(message, t.PHONE_INVALID)
            return
        store.save_contact(message.chat.id, None, phone)
        user = store.get_user(message.chat.id) or {}
        await _finish_booking(message, user.get("name") or "Гость", phone)
        return

    await _reply(message, t.FALLBACK, reply_markup=kb.MAIN_MENU)


async def _finish_booking(
    message: Message,
    name: str,
    phone: str | None,
    username: str | None = None,
) -> None:
    funnel = store.get_funnel(message.chat.id)
    if not funnel or not funnel.get("game_id"):
        await _reply(message, t.FALLBACK, reply_markup=kb.MAIN_MENU)
        return

    game_id = funnel["game_id"]
    seats = funnel.get("seats") or 1
    if username is None and message.from_user:
        username = message.from_user.username

    result = await crm.book(
        game_id=game_id,
        name=name,
        seats=seats,
        chat_id=message.chat.id,
        phone=phone,
        username=username,
    )

    if result is None:
        await _reply(message, t.CRM_OFFLINE, reply_markup=kb.REMOVE_KEYBOARD)
        return
    if result.get("_status") == 409:
        # Места разобрали, пока человек вводил имя, — предлагаем другую дату.
        await message.answer(t.NO_SEATS, reply_markup=kb.REMOVE_KEYBOARD)
        await _reply(message, t.GAMES_HEADER, reply_markup=kb.TO_GAMES)
        return
    if "_status" in result:
        await _reply(message, t.CRM_OFFLINE, reply_markup=kb.REMOVE_KEYBOARD)
        return

    game = await crm.game(game_id)
    store.clear_funnel(message.chat.id)
    # Клавиатуру запроса контакта убираем вместе с подтверждением: у одного
    # сообщения может быть только одна разметка, поэтому меню — следующим.
    done = t.booking_done(game, seats, name) if game else t.CONFIRMED
    await _reply(message, done, reply_markup=kb.REMOVE_KEYBOARD)
    await _reply(message, t.MENU_PROMPT, reply_markup=kb.MAIN_MENU)


# ─── Свои записи ─────────────────────────────────────────────────────────────


@router.callback_query(F.data == "my")
async def my_bookings(call: CallbackQuery) -> None:
    chat_id = call.message.chat.id if call.message else 0
    items = await crm.bookings(chat_id)
    if items is None:
        await _edit(call, t.CRM_OFFLINE, kb.BACK_TO_MENU)
        return
    if not items:
        await _edit(call, t.BOOKINGS_EMPTY, kb.TO_GAMES)
        return

    latest = items[0]
    body = "\n\n".join(t.booking_line(b) for b in items)
    await _edit(call, f"{t.BOOKINGS_HEADER}\n\n{body}", kb.booking_actions(latest["id"]))


@router.callback_query(F.data.startswith("confirm:"))
async def confirm(call: CallbackQuery) -> None:
    booking_id = (call.data or "").split(":", 1)[1]
    chat_id = call.message.chat.id if call.message else 0
    ok = await crm.set_booking_status(booking_id, chat_id, "confirmed")
    await _edit(call, t.CONFIRMED if ok else t.CRM_OFFLINE, kb.BACK_TO_MENU)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel(call: CallbackQuery) -> None:
    booking_id = (call.data or "").split(":", 1)[1]
    chat_id = call.message.chat.id if call.message else 0
    ok = await crm.set_booking_status(booking_id, chat_id, "cancelled")
    await _edit(call, t.CANCELLED if ok else t.CRM_OFFLINE, kb.TO_GAMES)
