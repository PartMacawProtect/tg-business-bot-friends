import datetime
import pytz
from aiogram import Router
from aiogram.types import Message
from groq import AsyncGroq

from app.settings import secrets, bot
from app.utils.opening_hours import check_opening_hours
from app.views import system_prompt

router = Router()
client = AsyncGroq(api_key=secrets.groq_api_key)


def format_schedule(opening_hours) -> str:
    """Форматирует сырые интервалы времени от Telegram в понятный для ИИ 7-дневный график"""
    if not opening_hours or not hasattr(opening_hours, "opening_hours") or not opening_hours.opening_hours:
        return "График работы свободный или не настроен."

    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    schedule_dict = {i: [] for i in range(7)}

    for interval in opening_hours.opening_hours:
        start_day = (interval.opening_minute // 1440) % 7
        start_hour = (interval.opening_minute % 1440) // 60
        start_min = (interval.opening_minute % 1440) % 60

        end_day = (interval.closing_minute // 1440) % 7
        end_hour = (interval.closing_minute % 1440) // 60
        end_min = (interval.closing_minute % 1440) % 60

        duration = interval.closing_minute - interval.opening_minute

        if duration >= 1440 and start_hour == 0 and start_min == 0:
            curr_day = start_day
            rem_duration = duration
            while rem_duration > 0:
                schedule_dict[curr_day].append("Круглосуточно")
                curr_day = (curr_day + 1) % 7
                rem_duration -= 1440
            continue

        time_str = f"{start_hour:02d}:{start_min:02d} - {end_hour:02d}:{end_min:02d}"

        if start_day == end_day:
            schedule_dict[start_day].append(time_str)
        else:
            schedule_dict[start_day].append(f"с {start_hour:02d}:{start_min:02d}")
            schedule_dict[end_day].append(f"до {end_hour:02d}:{end_min:02d}")

    lines = []
    for i, day_name in enumerate(days):
        intervals = schedule_dict[i]
        if not intervals:
            lines.append(f"• {day_name}: Выходной (Закрыто)")
        else:
            unique_intervals = list(dict.fromkeys(intervals))
            lines.append(f"• {day_name}: {', '.join(unique_intervals)}")

    tz_str = f"\nЧасовой пояс: {opening_hours.time_zone_name}" if hasattr(opening_hours, "time_zone_name") else ""
    return "\n".join(lines) + tz_str


@router.business_message()
async def business_message_handler(message: Message):
    # Игнорируем сообщения от самого администратора бота
    if message.from_user.id == secrets.admin_id:
        return

    # Игнорируем обычные сообщения в ЛС бота (работаем только в бизнес-чатах)
    if not message.business_connection_id:
        return

    try:
        # Получаем данные о бизнес-подключении и графике работы аккаунта
        business_conn = await bot.get_business_connection(business_connection_id=message.business_connection_id)
        chat_info = await bot.get_chat(chat_id=business_conn.user_chat_id)
        opening_hours = chat_info.business_opening_hours

        # Если график вообще удалили, выходим
        if not opening_hours:
            return

        # Проверяем, открыты мы сейчас или закрыты. Если время РАБОЧЕЕ — бот молчит
        if not check_opening_hours(opening_hours):
            return

    except Exception as e:
        print(f"Ошибка при проверке бизнес-статуса или часов работы: {e}")
        return

    # --- ЕСЛИ СЕЙЧАС НЕРАБОЧЕЕ ВРЕМЯ -> ОТВЕЧАЕМ ---
    schedule_text = format_schedule(opening_hours)

    try:
        tz_name = opening_hours.time_zone_name if hasattr(opening_hours, "time_zone_name") else "UTC"
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.utc

    now = datetime.datetime.now(tz)
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    current_day = days_ru[now.weekday()]
    current_time = now.strftime("%H:%M")

    try:
        # Запрос к нейросети Groq
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt(schedule_text, current_day, current_time)},
                {"role": "user", "content": message.text},
            ],
        )
        answer = response.choices[0].message.content

        # Защита разметки Telegram (экранирование)
        safe_answer = answer.replace("_", "\\_")

        # Отправка ответа клиенту в бизнес-чат
        await bot.send_message(
            chat_id=message.chat.id, 
            text=safe_answer, 
            business_connection_id=message.business_connection_id
        )

    except Exception as e:
        print(f"Ошибка при генерации ответа в Groq или отправке сообщения: {e}")
