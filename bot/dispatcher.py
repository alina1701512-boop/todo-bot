from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramBadRequest
import re
import logging
import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import TG_TOKEN, TZ
from services import task_service
from services.ai_parser import parse_task_with_ai, make_naive, chat_with_ai
from database import async_session
from sqlalchemy import select, func
from models import Task

logger = logging.getLogger(__name__)
user_context = {}
tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

ITEMS_PER_PAGE = 8

# ================= КЛАВИАТУРЫ =================
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Все задачи")],
        [KeyboardButton(text="🤖 AI Чат")],
        [KeyboardButton(text="🔥 Важность"), KeyboardButton(text="📅 Период")],
        [KeyboardButton(text="⚙️ Меню")]
    ], resize_keyboard=True)

def get_settings_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📅 Google Calendar")],
        [KeyboardButton(text="❓ Помощ�")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

def get_google_calendar_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔌 Подключить"), KeyboardButton(text="🔌 Отключить")],
        [KeyboardButton(text="📋 Статус")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

def get_stats_period_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 За неделю"), KeyboardButton(text="📊 За месяц")],
        [KeyboardButton(text="📊 За год")],
        [KeyboardButton(text="🔙 Назад")]
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

def parse_date(text):
    now = datetime.now(tz)
    text_lower = text.lower().strip()
    corrections = {"сегодны": "сегодня", "завтрп": "завтра", "послезавтрп": "послезавтра"}
    for wrong, correct in corrections.items(): text_lower = text_lower.replace(wrong, correct)
    time_match = re.search(r'(\d{1,2})[:.](\d{2})', text_lower)
    target_hour = None
    target_minute = 0
    if time_match:
        target_hour = int(time_match.group(1))
        target_minute = int(time_match.group(2))
        if not (0 <= target_hour <= 23 and 0 <= target_minute <= 59): target_hour = None
    if "сегодня" in text_lower: return now.replace(hour=target_hour or 23, minute=target_minute or 59, second=0, microsecond=0)
    if "завтра" in text_lower:
        t = now + timedelta(days=1)
        return t.replace(hour=target_hour or 23, minute=target_minute or 59, second=0, microsecond=0)
    if "послезавтра" in text_lower:
        t = now + timedelta(days=2)
        return t.replace(hour=target_hour or 23, minute=target_minute or 59, second=0, microsecond=0)
    if "на днях" in text_lower:
        t = now + timedelta(days=3)
        return t.replace(hour=target_hour or 23, minute=target_minute or 59, second=0, microsecond=0)
    if "в конце месяца" in text_lower:
        t = datetime(now.year, now.month + 1 if now.month < 12 else 1, 1, tzinfo=tz) - timedelta(days=3)
        return t.replace(hour=target_hour or 23, minute=target_minute or 59, second=0, microsecond=0)
    return None

def clean_title(text):
    words = ["красный", "срочно", "важно", "горит", "зеленый", "легко", "лайт", 
             "каждый день", "каждую неделю", "каждый месяц", "ежедневно", "еженедельно",
             "сегодня", "завтра", "послезавтра", "неделю", "месяц", "на днях",
             "в конце месяца", "в начале месяца", "в середине месяца", "в выходные",
             "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    for w in words: text = text.lower().replace(w, "")
    return text.strip().title()

# ================= ФУНКЦИЯ СОРТИРОВКИ =================
def get_sort_key(task):
    if task.is_done:
        priority_order = 4
    else:
        priority_order = {
            "red": 0,
            "yellow": 1,
            "green": 2,
            "none": 3
        }.get(task.priority, 3)
    
    if task.due_at:
        if hasattr(task.due_at, 'tzinfo') and task.due_at.tzinfo is not None:
            due_time = task.due_at.replace(tzinfo=None)
        else:
            due_time = task.due_at
    else:
        due_time = datetime.max
    
    return (priority_order, due_time)

def sort_tasks_by_priority_and_time(tasks):
    return sorted(tasks, key=get_sort_key)

# ================= СТАТИСТИКА С ПЕРИОДАМИ =================
async def get_stats_for_period(user_id: str, period: str):
    now = datetime.utcnow()
    
    if period == "week":
        start_date = now - timedelta(days=7)
    elif period == "month":
        start_date = now - timedelta(days=30)
    elif period == "year":
        start_date = now - timedelta(days=365)
    else:
        start_date = None
    
    async with async_session() as session:
        base_conditions = [Task.is_archived == False, Task.user_id == str(user_id)]
        if start_date:
            base_conditions.append(Task.created_at >= start_date)
        
        total = await session.scalar(select(func.count(Task.id)).where(*base_conditions))
        done = await session.scalar(select(func.count(Task.id)).where(*base_conditions, Task.is_done == True))
        
        return {
            "total": total or 0,
            "done": done or 0,
            "pending": (total or 0) - (done or 0),
        }

# ================= ОТРИСОВКА СПИСКА =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False, page_offset=0):
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if filter_type == "all": 
        tasks = await task_service.get_all_tasks(user_id=user_id_str)
    elif filter_type == "priority":
        all_t = await task_service.get_all_tasks(user_id=user_id_str)
        tasks = [t for t in all_t if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Сегодня": 
            tasks = await task_service.get_tasks_for_date(now.date(), user_id=user_id_str)
        elif filter_val == "Завтра": 
            tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1), user_id=user_id_str)
        elif filter_val == "📆 Неделя": 
            tasks = await task_service.get_tasks_for_week(now.date(), user_id=user_id_str)
        elif filter_val == "🗓️ Месяц":
            all_t = await task_service.get_all_tasks(user_id=user_id_str)
            end = now.date() + timedelta(days=30)
            tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
        else: 
            tasks = []
    else: 
        tasks = []
    
    all_tasks = sort_tasks_by_priority_and_time(tasks)
    total = len(all_tasks)
    
    if page_offset >= total and total > 0: 
        page_offset = ((total - 1) // ITEMS_PER_PAGE) * ITEMS_PER_PAGE
    if page_offset < 0: 
        page_offset = 0
    
    user_context.setdefault(user_id, {})
    user_context[user_id].update({
        "title": title, 
        "type": filter_type, 
        "val": filter_val, 
        "offset": page_offset
    })

    if total == 0:
        text = "📋 Задач нет"
        kb = [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")]
        try:
            if is_edit: 
                await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
            else: 
                await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
        except Exception as e:
            logger.error(f"❌ Show empty list error: {e}")
        return

    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    current_page = (page_offset // ITEMS_PER_PAGE) + 1
    page_tasks = all_tasks[page_offset : page_offset + ITEMS_PER_PAGE]

    text = f"📋 {title} (всего {total})\n📄 Страница {current_page} из {total_pages}\n\n"
    kb = []
    
    for t in page_tasks:
        if t.is_done:
            icon = "✅"
        else:
            icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
        
        task_text = t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
        cb = f"done_{t.id}" if t.is_done else f"task_{t.id}"
        
        kb.append([InlineKeyboardButton(text=f"{icon} {task_text} | {due}", callback_data=cb)])
    
    nav = []
    if page_offset > 0: 
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="page_prev"))
    if page_offset + ITEMS_PER_PAGE < total: 
        nav.append(InlineKeyboardButton(text="Вперед ➡️", callback_data="page_next"))
    if nav: 
        kb.append(nav)

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    try:
        if is_edit: 
            await message.edit_text(text, reply_markup=markup)
        else: 
            await message.answer(text, reply_markup=markup)
    except TelegramBadRequest as e:
        logger.error(f"❌ Edit failed: {e}")
        try:
            await message.answer(text, reply_markup=markup)
        except:
            pass
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")

# ================= ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ =================
def get_welcome_message():
    return """👋 **Привет! Я твой AI-планировщик.**

Я помогаю управлять задачами, напоминаю о дедлайнах и синхронизирую с Google Календарём.

---

📌 **Как добавлять задачи:**
Просто напиши текст — я сам пойму дату и важность. Формат: (текст задачи, дата и срочность) 
пример: `приготовить ужин завтра в 19:00 красный`

---

📋 **Мои кнопки:**

**Основные:**
📋 Все задачи — показать список дел
🤖 AI Чат — поговорить с искусственным интеллектом
🔥 Важность — фильтр по приоритетам
📅 Период — фильтр по дате
⚙️ Меню — все настройки

---

🎯 **Как работают приоритеты:**
🔴 Срочные — вверху списка
🟡 Средние — посередине
🟢 Лайтовые — внизу
✅ Выполненные — уходят в конец

---

💡 **Советы:**
• Нажми на задачу — отметится галочкой ✅ и уйдет в конец списка
• Напиши "срочно" — поставлю красный приоритет

Приятного использования! 🚀"""

# ================= ОБРАБОТЧИКИ МЕНЮ =================
@dp.message(Command("start"))
async def cmd_start(message): 
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await message.answer(get_welcome_message(), parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔙 Назад")
async def go_back(message): 
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await message.answer("🔙 Главное меню:", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "⚙️ Меню")
async def settings_menu(message):
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await message.answer("⚙️ **Настройки и информация:**", parse_mode="Markdown", reply_markup=get_settings_menu_keyboard())

# ================= СТАТИСТИКА =================
@dp.message(lambda m: m.text == "📊 Статистика")
async def stats_menu(message):
    await message.answer("📊 **Выбери период для статистики:**", parse_mode="Markdown", reply_markup=get_stats_period_keyboard())

@dp.message(lambda m: m.text in ["📊 За неделю", "📊 За месяц", "📊 За год"])
async def show_stats_period(message):
    uid_str = str(message.from_user.id)
    period_map = {
        "📊 За неделю": "week",
        "📊 За месяц": "month", 
        "📊 За год": "year"
    }
    period = period_map.get(message.text, "week")
    
    await message.answer("📊 **Готовлю статистику...**")
    
    stats = await get_stats_for_period(uid_str, period)
    period_name = {"week": "неделю", "month": "месяц", "year": "год"}.get(period, "неделю")
    
    completion = (stats['done'] / stats['total'] * 100) if stats['total'] > 0 else 0
    
    text = (f"📊 **Статистика за {period_name}:**\n\n"
            f"📦 **Всего задач:** {stats['total']}\n"
            f"✅ **Выполнено:** {stats['done']}\n"
            f"⏳ **В работе:** {stats['pending']}\n\n"
            f"📈 **Прогресс:** {completion:.1f}%")
    
    await message.answer(text, parse_mode="Markdown")

# ================= GOOGLE CALENDAR =================
@dp.message(lambda m: m.text == "📅 Google Calendar")
async def google_menu(message):
    await message.answer("📅 **Управление Google Calendar:**", parse_mode="Markdown", reply_markup=get_google_calendar_menu_keyboard())

@dp.message(lambda m: m.text == "🔌 Подключить")
async def connect_google_button(message):
    await connect_google(message)

@dp.message(lambda m: m.text == "🔌 Отключить")
async def disconnect_google_button(message):
    await disconnect_google(message)

@dp.message(lambda m: m.text == "📋 Статус")
async def google_status_button(message):
    await google_status(message)

# ================= НАПОМИНАНИЯ =================
# @dp.message(lambda m: m.text == "🔔 Напоминания")
async def reminders_menu(message):
    await message.answer("🔔 **Настройка напоминаний:**\n\nВыбери интервал или включи/выключи уведомления.", parse_mode="Markdown", reply_markup=get_reminders_menu_keyboard())

# @dp.message(lambda m: m.text == "✅ Включить")
async def enable_reminders(message):
    await message.answer("✅ **Напоминания включены!**\n\nТы будешь получать уведомления о задачах.", parse_mode="Markdown")

# @dp.message(lambda m: m.text == "❌ Выключить")
async def disable_reminders(message):
    await message.answer("❌ **Напоминания выключены.**\n\nТы не будешь получать уведомления.", parse_mode="Markdown")

# @dp.message(lambda m: m.text in ["🔔 За 15 минут", "🔔 За 30 минут", "🔔 За 1 час", "🔔 За 1 день"])
async def set_reminder_time(message):
    await message.answer(f"✅ **Время напоминания установлено:** {message.text}\n\nТы будешь получать уведомления за {message.text[2:]} до дедлайна.", parse_mode="Markdown")

# ================= ПОМОЩЬ =================
@dp.message(lambda m: m.text == "❓ Помощь")
async def help_button(message):
    help_text = """👋 **Помощь по боту**

**📌 Как добавлять задачи:**
Просто напиши текст — я сам пойму дату и важность. Формат: (текст задачи, дата и срочность) 
пример: `приготовить ужин завтра в 19:00 красный`

**🎯 Кнопки меню:**
📋 Все задачи — показать список
🤖 AI Чат — поговорить с ИИ
🔥 Важность — фильтр по приоритетам
📅 Период — фильтр по дате
⚙️ Меню — все настройки

**💡 Советы:**
• Нажми на задачу — отметится галочкой ✅ и уйдет в конец списка
• Напиши "срочно" — поставлю красный приоритет"""
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Написать разработчику", url="https://t.me/alinakoor")]
    ])
    
    await message.answer(help_text, parse_mode="Markdown", reply_markup=kb)

# ================= ОСТАЛЬНЫЕ КНОПКИ =================
@dp.message(lambda m: m.text == "🔥 Важность")
async def priority_menu(message): 
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await message.answer("🔥 Выбери важность:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda m: m.text == "📅 Период")
async def period_menu(message): 
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await message.answer("📅 Выбери период:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "📋 Все задачи")
async def all_tasks(message):
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await show_task_list(message, "Все задачи", "all", None, page_offset=0)

@dp.message(lambda m: m.text in ["🔴 Срочные", "🟡 Средние", "🟢 Лайтовые"])
async def filter_importance(message):
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    p_map = {"🔴 Срочные": "red", "🟡 Средние": "yellow", "🟢 Лайтовые": "green"}
    await show_task_list(message, message.text, "priority", p_map[message.text], page_offset=0)

@dp.message(lambda m: m.text in ["Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"])
async def filter_period(message):
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await show_task_list(message, message.text, "period", message.text, page_offset=0)

# 🤖 AI ЧАТ
@dp.message(lambda m: m.text == "🤖 AI Чат")
async def enter_ai_mode(message):
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = True
    await message.answer("🤖 **Режим AI-чата включен**\n\nПиши что угодно, я помогу!\nЧтобы вернуться к задачам, нажми /start или 🔙 Назад.")

# 📝 ГЛАВНЫЙ ОБРАБОТЧИК ТЕКСТА
@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "📋 Все задачи", "🔥 Важность", "📅 Период", "🔙 Назад", "🤖 AI Чат",
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые", "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц",
    "⚙️ Меню", "📊 Статистика", "📅 Google Calendar", "❓ Помощь",
    "📊 За неделю", "📊 За месяц", "📊 За год", "🔌 Подключить", "🔌 Отключить", "📋 Статус",
])
async def handle_text(message):
    uid = message.from_user.id
    uid_str = str(uid)
    state = user_context.setdefault(uid, {})
    text = message.text.strip()

    if state.get("ai_mode") or text.endswith("?"):
        await message.answer("🤖 Думаю...")
        reply = await chat_with_ai(text)
        await message.answer(reply or "❌ Не удалось получить ответ.")
        return

    ai_result = await parse_task_with_ai(text)
    if ai_result and ai_result.get("title"):
        title = ai_result.get("title")
        priority = ai_result.get("priority", "none")
        due_at = ai_result.get("due_at")
    else:
        priority = parse_priority(text)
        due_at = parse_date(text)
        title = clean_title(text)

    if due_at and hasattr(due_at, 'tzinfo') and due_at.tzinfo is not None:
        due_at = due_at.replace(tzinfo=None)

    task = await task_service.create_task(title, due_at, priority, user_id=uid_str)
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(priority, "⚪️")
    due_str = due_at.strftime("%d.%m в %H:%M") if due_at else "Без срока"
    
    await message.answer(f"{emoji} Задача добавлена!\n📝 {task.title}\n🕐 {due_str}")
    
    ctx = user_context.get(uid)
    if ctx:
        await show_task_list(message, ctx["title"], ctx["type"], ctx["val"], is_edit=False, page_offset=0)

# ================= СТАТИСТИКА /stats =================
@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    await stats_menu(message)

# ================= ГОЛОСОВЫЕ СООБЩЕНИЯ =================
@dp.message(lambda m: m.voice)
async def handle_voice(message: types.Message):
    await message.answer("🎤 Голосовые задачи временно отключены. Пожалуйста, напишите текст.")

# ================= GOOGLE CALENDAR COMMANDS =================
@dp.message(Command("connect_google"))
async def connect_google(message: types.Message):
    try:
        from services.google_calendar import get_auth_url
    except ImportError:
        await message.answer("❌ Модуль Google Calendar не найден.")
        return
    
    user_id = message.from_user.id
    parts = message.text.split()
    
    if len(parts) > 1:
        code = parts[1]
        await message.answer("🔄 Проверяю код...")
        
        from services.google_calendar import save_code
        success = await save_code(user_id, code)
        
        if success:
            await message.answer("✅ **Google Календарь подключен!**")
        else:
            await message.answer("❌ Ошибка при проверке кода.")
    else:
        try:
            url = await get_auth_url(user_id)
            await message.answer(
                f"📅 **Подключение Google Calendar**\n\n"
                f"**1.** Перейди по ссылке:\n{url}\n\n"
                f"**2.** Скопируй код и отправь:\n"
                f"`/connect_google КОД`"
            )
        except Exception as e:
            logger.error(f"Google auth error: {e}")
            await message.answer("❌ Ошибка при генерации ссылки.")

@dp.message(Command("disconnect_google"))
async def disconnect_google(message: types.Message):
    try:
        from services.google_calendar import disconnect_google as google_disconnect
    except ImportError:
        await message.answer("❌ Модуль не найден.")
        return
    
    success = await google_disconnect(message.from_user.id)
    if success:
        await message.answer("🗑️ **Google Calendar отключен**")
    else:
        await message.answer("⚠️ Не удалось отключить.")

@dp.message(Command("google_status"))
async def google_status(message: types.Message):
    try:
        from services.google_calendar import _get_creds_from_db
    except ImportError:
        await message.answer("❌ Модуль не найден.")
        return
    
    creds = await _get_creds_from_db(message.from_user.id)
    
    if creds:
        await message.answer("✅ **Google Calendar подключен**")
    else:
        await message.answer("⚪️ **Google Calendar не подключен**\n\nНапиши `/connect_google`")
        
# ================= КОЛБЭККИ =================
@dp.callback_query(lambda c: c.data == "refresh")
async def refresh_list(callback):
    ctx = user_context.get(callback.from_user.id)
    if ctx:
        ctx["ai_mode"] = False
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True, page_offset=ctx.get("offset", 0))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "page_next")
async def page_next(callback):
    ctx = user_context.get(callback.from_user.id)
    if ctx:
        new_offset = ctx.get("offset", 0) + ITEMS_PER_PAGE
        ctx["offset"] = new_offset
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True, page_offset=new_offset)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "page_prev")
async def page_prev(callback):
    ctx = user_context.get(callback.from_user.id)
    if ctx:
        new_offset = max(0, ctx.get("offset", 0) - ITEMS_PER_PAGE)
        ctx["offset"] = new_offset
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True, page_offset=new_offset)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("task_") or c.data.startswith("done_"))
async def handle_task_click(callback):
    try:
        uid = callback.from_user.id
        tid = int(callback.data.split("_")[1])
        
        task = await task_service.get_task_by_id(tid)
        if task:
            if str(task.user_id) == str(uid):
                await task_service.update_task(tid, is_done=not task.is_done)
            else:
                await callback.answer("❌ Это не твоя задача!", show_alert=True)
                return
        
        await callback.answer("")
        
        ctx = user_context.get(uid, {})
        
        if ctx.get("title"):
            await show_task_list(
                callback.message,
                ctx.get("title", "Все задачи"),
                ctx.get("type", "all"),
                ctx.get("val"),
                is_edit=True,
                page_offset=ctx.get("offset", 0)
            )
        else:
            await show_task_list(
                callback.message,
                "Все задачи",
                "all",
                None,
                is_edit=True,
                page_offset=0
            )
    except Exception as e:
        logger.error(f"❌ handle_task_click error: {e}")
        await callback.answer("⚠️ Ошибка при обновлении", show_alert=True)
