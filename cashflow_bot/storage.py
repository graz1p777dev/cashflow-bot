"""Локальное состояние бота: SQLite рядом с процессом.

В CRM живут игры и записи — это общая правда. Здесь только то, что нужно
самому боту и не интересно CRM:

  users      — кто уже писал, чтобы не здороваться дважды и знать имя;
  funnels    — незаконченные записи: на каком шаге человек застрял;
  followups  — какие дожимы уже отправлены (второй раз не шлём);
  reminders  — какие напоминания о какой брони уже ушли.

Состояние диалога держим в БД, а не в памяти: Railway перезапускает
процесс при каждом деплое, а человек не должен начинать запись заново.
"""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  chat_id     INTEGER PRIMARY KEY,
  name        TEXT,
  phone       TEXT,
  username    TEXT,
  created_at  TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

-- Незаконченная запись. Одна на человека: начал новую — старая заменяется.
CREATE TABLE IF NOT EXISTS funnels (
  chat_id     INTEGER PRIMARY KEY,
  game_id     TEXT,
  seats       INTEGER NOT NULL DEFAULT 1,
  step        TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS followups (
  chat_id     INTEGER NOT NULL,
  step_index  INTEGER NOT NULL,
  sent_at     TEXT    NOT NULL,
  PRIMARY KEY (chat_id, step_index)
);

CREATE TABLE IF NOT EXISTS reminders (
  booking_id  TEXT    NOT NULL,
  kind        TEXT    NOT NULL,
  sent_at     TEXT    NOT NULL,
  PRIMARY KEY (booking_id, kind)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.database_path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── Пользователи ────────────────────────────────────────────────────────

    def touch_user(self, chat_id: int, username: str | None) -> bool:
        """Отмечает визит. Возвращает True, если человек здесь впервые."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT chat_id FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET last_seen_at = ?, username = COALESCE(?, username) "
                    "WHERE chat_id = ?",
                    (_now(), username, chat_id),
                )
                conn.commit()
                return False
            conn.execute(
                "INSERT INTO users (chat_id, username, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, username, _now(), _now()),
            )
            conn.commit()
            return True

    def save_contact(self, chat_id: int, name: str | None, phone: str | None) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE users SET name = COALESCE(?, name), phone = COALESCE(?, phone) "
                "WHERE chat_id = ?",
                (name, phone, chat_id),
            )
            conn.commit()

    def get_user(self, chat_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            return dict(row) if row else None

    # ─── Незаконченная запись ────────────────────────────────────────────────

    def set_step(
        self,
        chat_id: int,
        step: str,
        game_id: str | None = None,
        seats: int | None = None,
    ) -> None:
        current = self.get_funnel(chat_id)
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO funnels (chat_id, game_id, seats, step, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET "
                "game_id = excluded.game_id, seats = excluded.seats, "
                "step = excluded.step, updated_at = excluded.updated_at",
                (
                    chat_id,
                    game_id if game_id is not None else (current or {}).get("game_id"),
                    seats if seats is not None else (current or {}).get("seats", 1),
                    step,
                    _now(),
                ),
            )
            conn.commit()

    def get_funnel(self, chat_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM funnels WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            return dict(row) if row else None

    def clear_funnel(self, chat_id: int) -> None:
        """Запись завершена или отменена — дожимать больше не за чем."""
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM funnels WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM followups WHERE chat_id = ?", (chat_id,))
            conn.commit()

    def stalled_funnels(self) -> list[dict]:
        """Незаконченные записи вместе с уже отправленными дожимами."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT f.chat_id, f.game_id, f.seats, f.step, f.updated_at, "
                "       COALESCE(MAX(fu.step_index), -1) AS last_step "
                "FROM funnels f "
                "LEFT JOIN followups fu ON fu.chat_id = f.chat_id "
                "WHERE f.step <> 'done' "
                "GROUP BY f.chat_id"
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_followup(self, chat_id: int, step_index: int) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO followups (chat_id, step_index, sent_at) "
                "VALUES (?, ?, ?)",
                (chat_id, step_index, _now()),
            )
            conn.commit()

    # ─── Напоминания ─────────────────────────────────────────────────────────

    def reminder_sent(self, booking_id: str, kind: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM reminders WHERE booking_id = ? AND kind = ?",
                (booking_id, kind),
            ).fetchone()
            return row is not None

    def mark_reminder(self, booking_id: str, kind: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO reminders (booking_id, kind, sent_at) "
                "VALUES (?, ?, ?)",
                (booking_id, kind, _now()),
            )
            conn.commit()
