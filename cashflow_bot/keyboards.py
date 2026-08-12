"""Клавиатуры. Кнопки — основной способ общения с ботом: свободный текст
человек вводит только там, где иначе нельзя (имя и телефон)."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from . import templates

MAIN_MENU = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Записаться на игру", callback_data="games")],
        [InlineKeyboardButton(text="❓ Что это за игра", callback_data="about:0")],
        [
            InlineKeyboardButton(text="📋 Мои записи", callback_data="my"),
            InlineKeyboardButton(text="💬 Вопросы", callback_data="faq"),
        ],
    ]
)

BACK_TO_MENU = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="← В меню", callback_data="menu")]]
)

TO_GAMES = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🗓 Выбрать дату", callback_data="games")],
        [InlineKeyboardButton(text="← В меню", callback_data="menu")],
    ]
)


def about(step: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if step + 1 < len(templates.ABOUT_SCREENS):
        rows.append(
            [InlineKeyboardButton(text="Дальше →", callback_data=f"about:{step + 1}")]
        )
    rows.append([InlineKeyboardButton(text="🎲 Записаться", callback_data="games")])
    rows.append([InlineKeyboardButton(text="← В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def games(items: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{templates.format_when(g['startsAt'])} · {templates.seats_line(g['seatsFree'])}",
                callback_data=f"game:{g['id']}",
            )
        ]
        for g in items
        if g["seatsFree"] > 0
    ]
    rows.append([InlineKeyboardButton(text="← В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def seats(game_id: str, free: int) -> InlineKeyboardMarkup:
    # Больше 4 мест за раз — это уже корпоратив, его обсуждают отдельно.
    options = [n for n in (1, 2, 3, 4) if n <= free]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(n), callback_data=f"seats:{game_id}:{n}")
                for n in options
            ],
            [InlineKeyboardButton(text="← Другая дата", callback_data="games")],
        ]
    )


PHONE_REQUEST = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

REMOVE_KEYBOARD = ReplyKeyboardRemove()


def booking_actions(booking_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Буду", callback_data=f"confirm:{booking_id}"
                ),
                InlineKeyboardButton(
                    text="✖️ Не смогу", callback_data=f"cancel:{booking_id}"
                ),
            ],
            [InlineKeyboardButton(text="← В меню", callback_data="menu")],
        ]
    )


def reminder(booking_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтверждаю", callback_data=f"confirm:{booking_id}"
                ),
                InlineKeyboardButton(
                    text="✖️ Не смогу", callback_data=f"cancel:{booking_id}"
                ),
            ]
        ]
    )
