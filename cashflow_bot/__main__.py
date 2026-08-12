import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import settings
from .crm import crm
from .handlers import router, store
from .scheduler import scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cashflow_bot")


async def main() -> None:
    bot = Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    if not crm.enabled:
        log.warning(
            "CRM не настроена (CRM_BASE_URL/CRM_BOT_TOKEN пустые): "
            "бот расскажет об игре, но записать никого не сможет"
        )

    # Дожимы и напоминания живут рядом с поллингом: отдельный процесс на
    # Railway стоил бы ещё один сервис ради двух таймеров.
    task = asyncio.create_task(scheduler_loop(bot, store))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        task.cancel()
        await crm.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
