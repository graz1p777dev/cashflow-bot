"""HTTP-клиент публичного API CRM (/api/public/*).

У бота нет ключей Supabase: он ходит по HTTP с общим секретом
CRM_BOT_TOKEN. Все методы возвращают None вместо исключения — недоступная
CRM не должна ронять обработчик сообщения, человек получит понятный текст
из templates.CRM_OFFLINE.
"""

import logging

import aiohttp

from .config import settings

log = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=10)


class CrmClient:
    def __init__(self) -> None:
        self.base = settings.crm_base_url.rstrip("/")
        self.token = settings.crm_bot_token.get_secret_value()
        self._session: aiohttp.ClientSession | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.base and self.token)

    async def _request(self, method: str, path: str, **kwargs) -> dict | None:
        if not self.enabled:
            return None
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=TIMEOUT)
        url = f"{self.base}/api/public/{path.lstrip('/')}"
        try:
            async with self._session.request(
                method, url, headers={"x-bot-token": self.token}, **kwargs
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    # 409 «мест нет» — рабочий ответ, а не сбой: его
                    # обработчик показывает человеком, не логируем как ошибку.
                    if response.status != 409:
                        log.warning("CRM %s %s → %s %s", method, path, response.status, body)
                    return {"_status": response.status, **(body or {})}
                return body
        except Exception as error:  # сеть, таймаут, невалидный JSON
            log.warning("CRM %s %s failed: %s", method, path, error)
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── Игры ────────────────────────────────────────────────────────────────

    async def games(self) -> list[dict] | None:
        data = await self._request("GET", "games")
        if data is None or "_status" in data:
            return None
        return data.get("games", [])

    async def game(self, game_id: str) -> dict | None:
        games = await self.games()
        if games is None:
            return None
        return next((g for g in games if g["id"] == game_id), None)

    # ─── Записи ──────────────────────────────────────────────────────────────

    async def book(
        self,
        game_id: str,
        name: str,
        seats: int,
        chat_id: int,
        phone: str | None,
        username: str | None,
    ) -> dict | None:
        return await self._request(
            "POST",
            "bookings",
            json={
                "gameId": game_id,
                "name": name,
                "seats": seats,
                "phone": phone,
                "telegramChatId": chat_id,
                "telegramUsername": username,
            },
        )

    async def bookings(self, chat_id: int) -> list[dict] | None:
        data = await self._request("GET", f"bookings?chatId={chat_id}")
        if data is None or "_status" in data:
            return None
        return data.get("bookings", [])

    async def set_booking_status(
        self, booking_id: str, chat_id: int, status: str
    ) -> bool:
        data = await self._request(
            "PATCH",
            "bookings",
            json={"bookingId": booking_id, "telegramChatId": chat_id, "status": status},
        )
        return bool(data and "_status" not in data)

    async def reminders(self, within_hours: float) -> list[dict] | None:
        data = await self._request("GET", f"reminders?withinHours={within_hours}")
        if data is None or "_status" in data:
            return None
        return data.get("reminders", [])

    # ─── Переписка ───────────────────────────────────────────────────────────

    async def log_message(
        self, chat_id: int, direction: str, text: str, sender: str | None = None
    ) -> None:
        """Лог для карточки сделки. Тихий: не мешает диалогу, если упал."""
        await self._request(
            "POST",
            "messages",
            json={
                "chatId": chat_id,
                "direction": direction,
                "sender": sender or ("client" if direction == "in" else "bot"),
                "text": text,
            },
        )


crm = CrmClient()
