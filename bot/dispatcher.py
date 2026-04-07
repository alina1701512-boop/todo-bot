from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramBadRequest
import dateparser
import re
import logging
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from config import TG_TOKEN, TZ
from services import task_service
from services.ai_parser import parse_task_with_ai, make_naive  # ✅ Импорт AI-парсера

logger = logging.getLogger(__name__)
user_context = {}
user_edit_mode = {}
tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# ================= КЛАВИАТУРЫ =================
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Все задачи")],
        [KeyboardButton(text="🔥 Важность"), KeyboardButton(text="📅 Период")]
    ], resize_keyboard=True)

def get_priority_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔴 Срочные"), KeyboardButton(text="🟡 Средние")],
        [KeyboardButton(text="🟢 Лайтовые"), KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

def get_period_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Сегодня"), KeyboardButton(text="Завтра")],
        [KeyboardButton(text="📆 Неделя"), KeyboardButton(text="🗓️ Месяц")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

# ================= УТИЛИТЫ =================
def parse_priority(text):
    t = text.lower()
    if any(w in t for w in ["красный", "срочно", "важно", "горит", "срочн", "критич"]): return "red"
    if any(w in t for w in ["зеленый", "легко", "лайт", "обычн", "спокойн"]): return "green"
    return "none"

def parse_repeat(text):
    t = text.lower()
    if "каждый день" in t or "ежедневно" in t: return "daily"
    if "каждую неделю" in t or "еженедельно" in t: return "weekly"
    if "каждый месяц" in t or "ежемесячно" in t: return "monthly"
    return "none"

def clean_title(text):
    words = ["красный", "срочно", "важно", "горит", "зеленый", "легко", "лайт", 
             "каждый день", "каждую неделю", "каждый месяц", "ежедневно", "еженедельно",
             "сегодня", "завтра", "послезавтра", "неделю", "месяц", "на днях",
             "в конце месяца", "в начале месяца", "в середине месяца", "в выходные",
             "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    for w in words: text = text.lower().replace(w, "")
    return text.strip().title()

def parse_date(text):
    """Умный парсинг дат с исправлением ошибок и всеми фичами"""
    now = datetime.now(tz)
    text_lower = text.lower().strip()
    
    # 1. ИСПРАВЛЕНИЕ ЧАСТЫХ ОПЕЧАТОК
    corrections = {
        "сегодны": "сегодня", "сегоднЯ": "сегодня", "сгодня": "сегодня",
        "завтрп": "завтра", "завтпа": "завтра", "завтрра": "завтра",
        "послезавтрп": "послезавтра", "послезавтпа": "послезавтра",
        "неделю": "неделю", "неделе": "неделю", "недели": "неделю",
        "месяц": "месяц", "месяца": "месяц", "месяце": "месяц",
        "выходные": "выходные", "выходных": "выходные"
    }
    
    for wrong, correct in corrections.items():
        text_lower = text_lower.replace(wrong, correct)
    
    # 2. ИЗВЛЕЧЕНИЕ ВРЕМЕНИ
    time_match = re.search(r'(\d{1,2})[:.](\d{2})', text_lower)
    target_hour = None
    target_minute = 0
    
    if time_match:
        target_hour = int(time_match.group(1))
        target_minute = int(time_match.group(2))
        if not (0 <= target_hour <= 23 and 0 <= target_minute <= 59):
            target_hour = None
    
    # 3. РАСПОЗНАВАНИЕ ДАТ
    if "сегодня" in text_lower:
        if target_hour is not None:
            return now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return now.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "завтра" in text_lower:
        tomorrow = now + timedelta(days=1)
        if target_hour is not None:
            return tomorrow.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return tomorrow.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "послезавтра" in text_lower:
        day_after = now + timedelta(days=2)
        if target_hour is not None:
            return day_after.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return day_after.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "на днях" in text_lower:
        days_later = now + timedelta(days=3)
        if target_hour is not None:
            return days_later.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return days_later.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "в конце месяца" in text_lower or "конце месяца" in text_lower:
        if now.month == 12:
            end_of_month = datetime(now.year + 1, 1, 1, tzinfo=tz) - timedelta(days=1)
        else:
            end_of_month = datetime(now.year, now.month + 1, 1, tzinfo=tz) - timedelta(days=1)
        if target_hour is not None:
            return end_of_month.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return end_of_month.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "в начале месяца" in text_lower or "начале месяца" in text_lower:
        if now.day > 5:
            target_date = datetime(now.year, now.month + 1, 5, tzinfo=tz) if now.month < 12 else datetime(now.year + 1, 1, 5, tzinfo=tz)
        else:
            target_date = datetime(now.year, now.month, 5, tzinfo=tz)
        if target_hour is not None:
            return target_date.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return target_date.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "в середине месяца" in text_lower or "середине месяца" in text_lower:
        if now.day > 15:
            target_date = datetime(now.year, now.month + 1, 15, tzinfo=tz) if now.month < 12 else datetime(now.year + 1, 1, 15, tzinfo=tz)
        else:
            target_date = datetime(now.year, now.month, 15, tzinfo=tz)
        if target_hour is not None:
            return target_date.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return target_date.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "в выходные" in text_lower or "выходные" in text_lower:
        days_until_saturday = (5 - now.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        saturday = now + timedelta(days=days_until_saturday)
        if target_hour is not None:
            return saturday.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return saturday.replace(hour=23, minute=59, second=0, microsecond=0)
    
    days_match = re.search(r'через\s+(\d+)\s*(день|дня|дней|неделю|недели|месяц|месяца)', text_lower)
    if days_match:
        num = int(days_match.group(1))
        unit = days_match.group(2)
        if unit in ["день", "дня", "дней"]:
            target_date = now + timedelta(days=num)
        elif unit in ["неделю", "недели"]:
            target_date = now + timedelta(weeks=num)
        elif unit in ["месяц", "месяца"]:
            target_date = now + timedelta(days=num*30)
        else:
            target_date = now + timedelta(days=num)
        if target_hour is not None:
            return target_date.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return target_date.replace(hour=23, minute=59, second=0, microsecond=0)
    
    if "неделе" in text_lower or "неделю" in text_lower:
        if "следующ" in text_lower:
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 7
            target_date = now + timedelta(days=days_until_monday)
        else:
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0:
                target_date = now
            else:
                target_date = now + timedelta(days=days_until_monday)
        if target_hour is not None:
            return target_date.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        return target_date.replace(hour=23, minute=59, second=0, microsecond=0)
    
    weekdays = {
        'понедельник': 0, 'пон': 0, 'пн': 0,
        'вторник': 1, 'вт': 1, 'втор': 1,
        'среда': 2, 'ср': 2, 'сред': 2,
        'четверг': 3, 'чт': 3, 'четв': 3,
        'пятница': 4, 'пт': 4, 'пятн': 4,
        'суббота': 5, 'сб': 5, 'суб': 5,
        'воскресенье': 6, 'вс': 6, 'воскр': 6
    }
    
    for day_name, weekday_num in weekdays.items():
        if day_name in text_lower:
            if "следующ" in text_lower:
                days_until = (weekday_num - now.weekday()) % 7
                if days_until <= 3:
                    days_until += 7
            else:
                days_until = (weekday_num - now.weekday()) % 7
                if days_until == 0:
                    days_until = 7
            target_date = now + timedelta(days=days_until)
            if target_hour is not None:
                return target_date.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            return target_date.replace(hour=23, minute=59, second=0, microsecond=0)
    
    # Форматы дат: 29.04.2025, 29.04
    date_match = re.search(r'(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?', text_lower)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else now.year
        if year < 100:
            year = 2000 + year if year < 50 else 1900 + year
        try:
            target_date = datetime(year, month, day, tzinfo=tz)
            if target_hour is not None:
                target_date = target_date.replace(hour=target_hour, minute=target_minute)
            else:
                target_date = target_date.replace(hour=23, minute=59)
            if target_date < now:
                target_date = target_date.replace(year=now.year + 1)
            return target_date
        except ValueError:
            pass
    
    # Месяца текстом: "29 апреля"
    month_names = {
        'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'мая': 5, 'май': 5,
        'июн': 6, 'июл': 7, 'август': 8, 'сентябр': 9, 'октябр': 10,
        'ноябр': 11, 'декабр': 12
    }
    
    for month_str, month_num in month_names.items():
        if month_str in text_lower:
            day_match = re.search(r'(\d{1,2})\s*' + month_str, text_lower)
            if day_match:
                day = int(day_match.group(1))
                year = now.year
                try:
                    target_date = datetime(year, month_num, day, tzinfo=tz)
                    if target_hour is not None:
                        target_date = target_date.replace(hour=target_hour, minute=target_minute)
                    else:
                        target_date = target_date.replace(hour=23, minute=59)
                    if target_date < now:
                        target_date = target_date.replace(year=now.year + 1)
                    return target_date
                except ValueError:
                    pass
    
    # Дни недели
    for day_name, weekday_num in weekdays.items():
        if day_name in text_lower:
            days_until = (weekday_num - now.weekday()) % 7
            if days_until == 0:
                days_until = 7
            target_date = now + timedelta(days=days_until)
            if target_hour is not None:
                return target_date.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            return target_date.replace(hour=23, minute=59, second=0, microsecond=0)
    
    # Dateparser фолбэк
    try:
        parsed = dateparser.parse(
            text,
            settings={
                "TIMEZONE": TZ,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now
            }
        )
        if parsed and parsed > now:
            if target_hour is not None:
                parsed = parsed.replace(hour=target_hour, minute=target_minute)
            return parsed
    except:
        pass
    
    # Только время
    if target_hour is not None:
        today_time = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if today_time > now:
            return today_time
        else:
            return (now + timedelta(days=1)).replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    
    return None

# ================= ОТРИСОВКА СПИСКА =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False):
    user_id = message.from_user.id
    is_edit_mode = user_edit_mode.get(user_id, False)
    user_context[user_id] = {"title": title, "type": filter_type, "val": filter_val}

    if filter_type == "all":
        tasks = await task_service.get_all_tasks()
    elif filter_type == "priority":
        all_tasks = await task_service.get_all_tasks()
        tasks = [t for t in all_tasks if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Сегодня": tasks = await task_service.get_tasks_for_date(now.date())
        elif filter_val == "Завтра": tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
        elif filter_val == "📆 Неделя": tasks = await task_service.get_tasks_for_week(now.date())
        elif filter_val == "🗓️ Месяц":
            all_tasks = await task_service.get_all_tasks()
            end = now.date() + timedelta(days=30)
            tasks = [t for t in all_tasks if t.due_at and now.date() <= t.due_at.date() <= end]
        else: tasks = []
    else:
        tasks = []

    if not tasks:
        text = "📋 Задач нет"
        kb = [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")]
        if is_edit:
            try: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
            except: pass
        else:
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
        return

    text = f"📋 {title} (всего {len(tasks)})\n\n"
    kb = []

    mode_btn_text = "✅ Обычный режим" if is_edit_mode else "✏️ Режим выбора"
    kb.append([InlineKeyboardButton(text=mode_btn_text, callback_data="toggle_mode")])

    for t in tasks[:20]:
        if t.is_done:
            icon = "✅"
        else:
            icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
            
        short = (t.title[:30] + "...") if len(t.title) > 30 else t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
        
        btn_text = f"{icon} {short}\n🕐 {due}"
        cb_data = f"task_{t.id}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    try:
        if is_edit:
            await message.edit_text(text, reply_markup=markup)
        else:
            await message.answer(text, reply_markup=markup)
    except TelegramBadRequest: pass

# ================= ОБРАБОТЧИКИ МЕНЮ =================
@dp.message(Command("start"))
async def cmd_start(message):
    await message.answer("👋 Привет! Я твой планировщик задач.", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔙 Назад")
async def go_back(message):
    await message.answer("🔙 Главное меню:", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔥 Важность")
async def priority_menu(message):
    await message.answer("🔥 Выбери важность:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda m: m.text == "📅 Период")
async def period_menu(message):
    await message.answer("📅 Выбери период:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "📋 Все задачи")
async def all_tasks(message):
    await show_task_list(message, "Все задачи", "all", None)

@dp.message(lambda m: m.text in ["🔴 Срочные", "🟡 Средние", "🟢 Лайтовые"])
async def filter_importance(message):
    p_map = {"🔴 Срочные": "red", "🟡 Средние": "yellow", "🟢 Лайтовые": "green"}
    await show_task_list(message, message.text, "priority", p_map[message.text])

@dp.message(lambda m: m.text in ["Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"])
async def filter_period(message):
    await show_task_list(message, message.text, "period", message.text)

# ================= ДОБАВЛЕНИЕ ЗАДАЧ =================
@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "📋 Все задачи", "🔥 Важность", "📅 Период", "🔙 Назад",
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые",
    "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"
])
async def handle_text(message):
    text = message.text.strip()
    
    # 🤖 Пытаемся использовать AI
    ai_result = await parse_task_with_ai(text)
    
    if ai_result:
        # AI успешно распарсил
        title = ai_result.get("title", text)
        priority = ai_result.get("priority", "none")
        due_at = ai_result.get("due_at")  # Уже naive благодаря ai_parser.py
    else:
        # AI не сработал — используем старый код
        priority = parse_priority(text)
        due_at = parse_date(text)
        title = clean_title(text)

    # ✅ Финальная страховка: убираем tzinfo если вдруг осталось
    if due_at and hasattr(due_at, 'tzinfo') and due_at.tzinfo is not None:
        due_at = due_at.replace(tzinfo=None)

    # Создаем задачу
    task = await task_service.create_task(title, due_at, priority)
    
    # Ответ
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(priority, "⚪️")
    due_str_display = due_at.strftime("%d.%m в %H:%M") if due_at else "Без срока"
    
    await message.answer(f"{emoji} Задача добавлена!\n📝 {task.title}\n🕐 {due_str_display}")
    
    # Обновляем список
    ctx = user_context.get(message.from_user.id)
    if ctx:
        class FakeMessage:
            def __init__(self, user_id): 
                self.from_user = types.User(id=user_id, is_bot=False, first_name="User")
            async def answer(self, text, reply_markup=None): 
                pass
        await show_task_list(FakeMessage(message.from_user.id), ctx["title"], ctx["type"], ctx["val"], is_edit=False)

# ================= КОЛБЭККИ =================
@dp.callback_query(lambda c: c.data == "toggle_mode")
async def toggle_mode(callback):
    uid = callback.from_user.id
    user_edit_mode[uid] = not user_edit_mode.get(uid, False)
    ctx = user_context.get(uid)
    if ctx:
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "refresh")
async def refresh_list(callback):
    ctx = user_context.get(callback.from_user.id)
    if ctx:
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("task_"))
async def handle_task_click(callback):
    uid = callback.from_user.id
    tid = int(callback.data.split("_")[1])
    
    # ✅ ПЕРЕКЛЮЧАЕМ СТАТУС (вкл/выкл)
    task = await task_service.get_task_by_id(tid)
    if task:
        new_status = not task.is_done
        await task_service.update_task(tid, is_done=new_status)
        
        if new_status:
            await callback.answer("✅ Выполнено!", show_alert=False)
        else:
            await callback.answer("↩️ Снято с выполнения", show_alert=False)
    
    ctx = user_context.get(uid)
    if ctx:
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)

@dp.callback_query(lambda c: c.data.startswith("noop_"))
async def noop(callback):
    await callback.answer("Задача уже выполнена", show_alert=False)
