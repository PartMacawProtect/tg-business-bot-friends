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
    """Функция строит точный 7-дневный график, отображая даже закрытые дни"""
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
    user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
    
    # ПРИНТ СТАРТА: Проверяем, видит ли бот сообщение вообще
    print(f"\n[DEBUG] 📥 Бот поймал сообщение от {user_info}: '{message.text}'")

    # 1. Проверка на ADMIN_ID
    print(f"[DEBUG] Проверка 1: Сравниваем ID отправителя ({message.from_user.id}) и ADMIN_ID ({secrets.admin_id})")
    if message.from_user.id == secrets.admin_id:
        print(f"[DEBUG] 🛑 Выход: Вы пишете со своего аккаунта администратора. Бот проигнорировал сообщение.")
        return

    # 2. Проверка на наличие бизнес-подключения
    print(f"[DEBUG] Проверка 2: Наличие business_connection_id ({message.business_connection_id})")
    if not message.business_connection_id:
        print("[DEBUG] 🛑 Выход: Сообщение отправлено боту прямо в ЛС, а хендлер ждет сообщений из бизнес-чатов.")
        return

    try:
        print("[DEBUG] Проверка 3: Запрашиваем статус бизнес-соединения и часы работы...")
        business_conn = await bot.get_business_connection(business_connection_id=message.business_connection_id)
        chat_info = await bot.get_chat(chat_id=business_conn.user_chat_id)
        opening_hours = chat_info.business_opening_hours

        if not opening_hours:
            print("[DEBUG] 🛑 Выход: У бизнес-аккаунта не настроено рабочее время (opening_hours пуст).")
            return

        # 3. Проверка времени работы
        is_hours_match = check_opening_hours(opening_hours)
        print(f"[DEBUG] Проверка 4: Результат check_opening_hours = {is_hours_match}")
        
        if not is_hours_match:
            print("[DEBUG] 🛑 Выход: Условие check_opening_hours не выполнено (сейчас рабочее время или график не совпал).")
            return

    except Exception as e:
        print(f"⚠️ [DEBUG] Ошибка в блоке проверки часов: {e}")
        return

    # --- РАБОТА В НЕРАБОЧЕЕ ВРЕМЯ ---
    print(f"[DEBUG] 🔥 Все проверки пройдены! Начинаем генерацию ответа через Groq...")
    
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
        print(f"🤖 Отправляем запрос в Groq API (Используем модель llama-3.3-70b)...")
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt(schedule_text, current_day, current_time)},
                {"role": "user", "content": message.text},
            ],
        )
        answer = response.choices[0].message.content
        print(f"🎯 Ответ от Groq получен: {answer}")

        safe_answer = answer.replace("_", "\\_")

        await bot.send_message(
            chat_id=message.chat.id, text=safe_answer, business_connection_id=message.business_connection_id
        )
        print("📤 Ответ успешно отправлен пользователю!")

    except Exception as e:
        print(f"❌ Ошибка в блоке Groq или при отправке: {e}")
