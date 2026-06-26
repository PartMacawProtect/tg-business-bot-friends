import datetime
import pytz
from aiogram import Router
from aiogram.types import Message
from groq import AsyncGroq

from app.settings import secrets, bot
from app.views import system_prompt

router = Router()
client = AsyncGroq(api_key=secrets.groq_api_key)


@router.business_message()
async def business_message_handler(message: Message):
    user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
    
    # 📥 Проверяем, пришло ли сообщение в лог
    print(f"\n[DEBUG] 📥 Бот поймал сообщение от {user_info}: '{message.text}'")

    # 1. Фильтр админа (чтобы бот не отвечал на твои собственные сообщения)
    if message.from_user.id == secrets.admin_id:
        print(f"[DEBUG] 🛑 Выход: Сообщение от администратора, игнорируем.")
        return

    # 2. Проверка, что это именно бизнес-чат
    if not message.business_connection_id:
        print("[DEBUG] 🛑 Выход: Это сообщение пришло боту в ЛС, а не в бизнес-чат.")
        return

    # --- РЕЖИМ 24/7 (БЕЗ ПРОВЕРКИ ГРАФИКА) ---
    print(f"[DEBUG] 🔥 Проверки пройдены! Генерируем круглосуточный ответ...")
    
    # Заглушка для промпта, так как график теперь не важен
    schedule_text = "График работы: круглосуточно, без выходных."

    # Определяем текущее время (по Москве, при желании можно поменять часовой пояс)
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.datetime.now(tz)
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    current_day = days_ru[now.weekday()]
    current_time = now.strftime("%H:%M")

    try:
        print(f"[DEBUG] 🤖 Отправляем запрос в Groq API (модель llama-3.3-70b)...")
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt(schedule_text, current_day, current_time)},
                {"role": "user", "content": message.text},
            ],
        )
        answer = response.choices[0].message.content
        print(f"[DEBUG] 🎯 Ответ от Groq получен успешно!")

        # Экранируем нижние подчеркивания, чтобы разметка Telegram не ломалась
        safe_answer = answer.replace("_", "\\_")

        # Отправляем ответ клиенту в бизнес-чат
        await bot.send_message(
            chat_id=message.chat.id, 
            text=safe_answer, 
            business_connection_id=message.business_connection_id
        )
        print("[DEBUG] 📤 Ответ успешно отправлен пользователю!")

    except Exception as e:
        print(f"❌ [DEBUG] Ошибка при генерации или отправке: {e}")
