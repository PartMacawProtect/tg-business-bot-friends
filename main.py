import asyncio
from aiogram import Dispatcher
from app.settings import bot, secrets
from app.views import start_bot_message, stop_bot_message
from app.handlers import router

dp = Dispatcher()
dp.include_router(router)

async def on_startup():
    try:
        await bot.send_message(secrets.admin_id, start_bot_message())
    except Exception as e:
        print(f"⚠️ Не удалось отправить сообщение о запуске админу: {e}")
        print("💡 Подсказка: зайдите в ТУ ОШИБКУ, которую выдает бот. Нужно открыть нового бота в Telegram и нажать /start.")

async def on_shutdown():
    try:
        await bot.send_message(secrets.admin_id, stop_bot_message())
    except Exception as e:
        print(f"⚠️ Не удалось отправить сообщение об остановке админу: {e}")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
