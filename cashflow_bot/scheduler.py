"""Фоновые рассылки: дожимы и напоминания перед игрой.

Дожим — человеку, который открыл список дат и не закончил запись.
Три касания (config.followup_hours), дальше не пишем: назойливый бот
отписывает лучше любой кнопки.

Напоминание — тем, кто уже записан: за сутки и в день игры. Что уже
отправлено, помнит SQLite бота, а не CRM: рассылка — его дело.
"""

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from . import keyboards as kb
from . import templates as t
from .config import settings
from .crm import crm
from .storage import Storage

log = logging.getLogger(__name__)


def _age_hours(iso: str) -> float:
    moment = datetime.fromisoformat(iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds() / 3600


def _hours_until(iso: str) -> float:
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (moment - datetime.now(timezone.utc)).total_seconds() / 3600


async def _send(bot: Bot, chat_id: int, text: str, markup=None) -> bool:
    try:
        await bot.send_message(chat_id, text, reply_markup=markup)
        await crm.log_message(chat_id, "out", text)
        return True
    except TelegramForbiddenError:
        # Человек заблокировал бота — это нормальный исход, не ошибка.
        return False
    except Exception as error:
        log.warning("send to %s failed: %s", chat_id, error)
        return False


async def run_followups(bot: Bot, store: Storage) -> None:
    offsets = settings.followup_offsets
    if not offsets:
        return

    games = await crm.games()
    seats_hint = ""
    if games:
        nearest = min(games, key=lambda g: g["startsAt"], default=None)
        if nearest and nearest["seatsFree"] > 0:
            seats_hint = "\n\n" + t.FOLLOWUP_SEATS_LEFT.format(
                seats=t.seats_line(nearest["seatsFree"])
            )

    for funnel in store.stalled_funnels():
        next_index = funnel["last_step"] + 1
        if next_index >= len(offsets) or next_index >= len(t.FOLLOWUPS):
            continue
        if _age_hours(funnel["updated_at"]) < offsets[next_index]:
            continue

        text = t.FOLLOWUPS[next_index]
        if next_index == 0 and seats_hint:
            text += seats_hint

        sent = await _send(bot, funnel["chat_id"], text, kb.TO_GAMES)
        # Помечаем и неудачу тоже: иначе заблокировавший бота человек
        # будет крутиться в очереди на каждом тике планировщика.
        store.mark_followup(funnel["chat_id"], next_index)
        if not sent:
            store.clear_funnel(funnel["chat_id"])


async def run_reminders(bot: Bot, store: Storage) -> None:
    offsets = settings.reminder_offsets
    if not offsets:
        return

    window = max(offsets) + 2
    items = await crm.reminders(window)
    if not items:
        return

    for booking in items:
        left = _hours_until(booking["game"]["startsAt"])
        if left < 0:
            continue

        # Ближайшее подходящее окно: за сутки → «завтра», в день игры →
        # короткое «сегодня». Отправляем по одному разу на бронь.
        if len(offsets) > 1 and left <= offsets[1]:
            kind, text, markup = "same_day", t.reminder_same_day(booking), None
        elif left <= offsets[0]:
            kind = "day_before"
            text = t.reminder_day_before(booking)
            markup = kb.reminder(booking["bookingId"])
        else:
            continue

        if store.reminder_sent(booking["bookingId"], kind):
            continue
        await _send(bot, booking["chatId"], text, markup)
        store.mark_reminder(booking["bookingId"], kind)


async def scheduler_loop(bot: Bot, store: Storage) -> None:
    while True:
        try:
            await run_followups(bot, store)
            await run_reminders(bot, store)
        except Exception as error:
            log.exception("scheduler tick failed: %s", error)
        await asyncio.sleep(settings.scheduler_interval_seconds)
