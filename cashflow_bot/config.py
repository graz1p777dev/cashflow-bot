from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: SecretStr

    # CRM: расписание игр и записи. Пустой base_url = офлайн-режим, бот
    # отвечает на вопросы об игре, но записать никого не может — так он
    # переживает недоступность CRM, а не падает при старте.
    crm_base_url: str = ""
    crm_bot_token: SecretStr = SecretStr("")

    database_path: str = "data/cashflow.db"

    # Часовой пояс Бишкека: время игры показываем людям в нём, а не в UTC.
    timezone: str = "Asia/Bishkek"

    # Куда писать о новых записях. 0 = никуда (уведомления и так есть в CRM).
    admin_chat_id: int = 0

    # Как часто планировщик проверяет дожимы и напоминания.
    scheduler_interval_seconds: int = 120

    # Дожимы для тех, кто начал запись и не закончил (часы после последнего
    # шага). Пустая строка выключает дожимы совсем.
    followup_hours: str = "0.5,6,24"

    # За сколько часов до игры напоминать. Второе число — короткое
    # напоминание в день игры.
    reminder_hours: str = "24,3"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def followup_offsets(self) -> list[float]:
        return [float(v) for v in self.followup_hours.split(",") if v.strip()]

    @property
    def reminder_offsets(self) -> list[float]:
        return [float(v) for v in self.reminder_hours.split(",") if v.strip()]


settings = Settings()  # type: ignore[call-arg]
