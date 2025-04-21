import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()

import asyncio
import logging



async def main():
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram import Bot, Dispatcher
    from tg.handlers.utils import inactivity_checker
    from tg.middleware import ActivityLoggerMiddleware
    from tg.handlers import brouter, operator, start, business, operator2


    bot = Bot(token="7798229141:AAHAJLIhT5SgAqtboo2B_AXQEa8vF2Boojo")
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(ActivityLoggerMiddleware())
    dp.callback_query.middleware(ActivityLoggerMiddleware())


    dp.include_routers(start.router, brouter.router, operator.router, business.router, operator2.router)

    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(inactivity_checker(bot))

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())