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
from services.ai_parser import parse_task_with_ai, make_naive, chat_with_ai

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

    if "сегодня" in text_lower:
        return now.replace(hour=target_hour or 23, minute=target_minute or 59, second=0, microsecond=0)
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

# ================= ОТРИСОВКА СПИСКА =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False):
    user_id = message.from_user.id
    is_edit_mode = user_edit_mode.get(user_id, False)
    user_context[user_id] = {"title": title, "type": filter_type, "val": filter_val}

    if filter_type == "all": tasks = await task_service.get_all_tasks()
    elif filter_type == "priority":
        all_t = await task_service.get_all_tasks()
        tasks = [t for t in all_t if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Сегодня": tasks = await task_service.get_tasks_for_date(now.date())
        elif filter_val == "Завтра": tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
        elif filter_val == "📆 Неделя": tasks = await task_service.get_tasks_for_week(now.date())
        elif filter_val == "🗓️ Месяц":
            all_t = await task_service.get_all_tasks()
            end = now.date() + timedelta(days=30)
            tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
        else: tasks = []
    else: tasks = []

    if not tasks:
        text = "📋 Задач нет"
        kb = [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")]
        if is_edit:
            try: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
            except: pass
        else: await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
        return

    text = f"📋 {title} (всего {len(tasks)})\n\n"
    kb = []
    mode_btn_text = "✅ Обычный режим" if is_edit_mode else "✏️ Режим выбора"
    kb.append([InlineKeyboardButton(text=mode_btn_text, callback_data="toggle_mode")])

    for t in tasks[:20]:
        icon = "✅" if t.is_done else {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
        short = (t.title[:30] + "...") if len(t.title) > 30 else t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
        kb.append([InlineKeyboardButton(text=f"{icon} {short}\n🕐 {due}", callback_data=f"task_{t.id}")])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    try:
        if is_edit: await message.edit_text(text, reply_markup=markup)
        else: await message.answer(text, reply_markup=markup)
    except TelegramBadRequest: pass

# ================= ОБРАБОТЧИКИ МЕНЮ =================
@dp.message(Command("start"))
async def cmd_start(message): await message.answer("👋 Привет! Я твой планировщик.", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔙 Назад")
async def go_back(message): await message.answer("🔙 Главное меню:", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔥 Важность")
async def priority_menu(message): await message.answer("🔥 Выбери важность:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda m: m.text == "📅 Период")
async def period_menu(message): await message.answer("📅 Выбери период:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "📋 Все задачи")
async def all_tasks(message): await show_task_list(message, "Все задачи", "all", None)

@dp.message(lambda m: m.text in ["🔴 Срочные", "🟡 Средние", "🟢 Лайтовые"])
async def filter_importance(message):
    p_map = {"🔴 Срочные": "red", "🟡 Средние": "yellow", "🟢 Лайтовые": "green"}
    await show_task_list(message, message.text, "priority", p_map[message.text])

@dp.message(lambda m: m.text in ["Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"])
async def filter_period(message): await show_task_list(message, message.text, "period", message.text)

# ================= ДОБАВЛЕНИЕ ЗАДАЧ =================
@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "📋 Все задачи", "🔥 Важность", "📅 Период", "🔙 Назад",
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые",
    "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"
])
async def handle_text(message):
    text = message.text.strip()
    ai_result = await parse_task_with_ai(text)
    
    if ai_result:
        title = ai_result.get("title", text)
        priority = ai_result.get("priority", "none")
        due_at = ai_result.get("due_at")
    else:
        priority = parse_priority(text)
        due_at = parse_date(text)
        title = clean_title(text)

    if due_at and hasattr(due_at, 'tzinfo') and due_at.tzinfo is not None:
        due_at = due_at.replace(tzinfo=None)

    task = await task_service.create_task(title, due_at, priority)
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(priority, "⚪️")
    due_str = due_at.strftime("%d.%m в %H:%M") if due_at else "Без срока"
    
    await message.answer(f"{emoji} Задача добавлена!\n📝 {task.title}\n🕐 {due_str}")
    
    ctx = user_context.get(message.from_user.id)
    if ctx:
        class FakeMessage:
            def __init__(self, user_id): 
                self.from_user = types.User(id=user_id, is_bot=False, first_name="User")
            async def answer(self, text, reply_markup=None): 
                pass
        await show_task_list(FakeMessage(message.from_user.id), ctx["title"], ctx["type"], ctx["val"], is_edit=False)

# ================= КОЛБЭККИ (ВОССТАНОВЛЕНА СТАРАЯ ЛОГИКА) =================
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
    
    # ✅ ПЕРЕКЛЮЧАЕМ СТАТУС (вкл/выкл) - СТАРАЯ РАБОЧАЯ ВЕРСИЯ
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
    await callback.answer("Задача уже выполнена", show_alert=False)from aiogram import Bot, Dispatcher, types
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
from services.ai_parser import parse_task_with_ai, make_naive, chat_with_ai

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

    if "сегодня" in text_lower:
        return now.replace(hour=target_hour or 23, minute=target_minute or 59, second=0, microsecond=0)
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

# ================= ОТРИСОВКА СПИСКА =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False):
    user_id = message.from_user.id
    is_edit_mode = user_edit_mode.get(user_id, False)
    user_context[user_id] = {"title": title, "type": filter_type, "val": filter_val}

    if filter_type == "all": tasks = await task_service.get_all_tasks()
    elif filter_type == "priority":
        all_t = await task_service.get_all_tasks()
        tasks = [t for t in all_t if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Сегодня": tasks = await task_service.get_tasks_for_date(now.date())
        elif filter_val == "Завтра": tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
        elif filter_val == "📆 Неделя": tasks = await task_service.get_tasks_for_week(now.date())
        elif filter_val == "🗓️ Месяц":
            all_t = await task_service.get_all_tasks()
            end = now.date() + timedelta(days=30)
            tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
        else: tasks = []
    else: tasks = []

    if not tasks:
        text = "📋 Задач нет"
        kb = [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")]
        if is_edit:
            try: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
            except: pass
        else: await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
        return

    text = f"📋 {title} (всего {len(tasks)})\n\n"
    kb = []
    mode_btn_text = "✅ Обычный режим" if is_edit_mode else "✏️ Режим выбора"
    kb.append([InlineKeyboardButton(text=mode_btn_text, callback_data="toggle_mode")])

    for t in tasks[:20]:
        icon = "✅" if t.is_done else {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
        short = (t.title[:30] + "...") if len(t.title) > 30 else t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
        kb.append([InlineKeyboardButton(text=f"{icon} {short}\n🕐 {due}", callback_data=f"task_{t.id}")])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    try:
        if is_edit: await message.edit_text(text, reply_markup=markup)
        else: await message.answer(text, reply_markup=markup)
    except TelegramBadRequest: pass

# ================= ОБРАБОТЧИКИ МЕНЮ =================
@dp.message(Command("start"))
async def cmd_start(message): await message.answer("👋 Привет! Я твой планировщик.", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔙 Назад")
async def go_back(message): await message.answer("🔙 Главное меню:", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔥 Важность")
async def priority_menu(message): await message.answer("🔥 Выбери важность:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda m: m.text == "📅 Период")
async def period_menu(message): await message.answer("📅 Выбери период:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "📋 Все задачи")
async def all_tasks(message): await show_task_list(message, "Все задачи", "all", None)

@dp.message(lambda m: m.text in ["🔴 Срочные", "🟡 Средние", "🟢 Лайтовые"])
async def filter_importance(message):
    p_map = {"🔴 Срочные": "red", "🟡 Средние": "yellow", "🟢 Лайтовые": "green"}
    await show_task_list(message, message.text, "priority", p_map[message.text])

@dp.message(lambda m: m.text in ["Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"])
async def filter_period(message): await show_task_list(message, message.text, "period", message.text)

# ================= ДОБАВЛЕНИЕ ЗАДАЧ =================
@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "📋 Все задачи", "🔥 Важность", "📅 Период", "🔙 Назад",
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые",
    "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"
])
async def handle_text(message):
    text = message.text.strip()
    ai_result = await parse_task_with_ai(text)
    
    if ai_result:
        title = ai_result.get("title", text)
        priority = ai_result.get("priority", "none")
        due_at = ai_result.get("due_at")
    else:
        priority = parse_priority(text)
        due_at = parse_date(text)
        title = clean_title(text)

    if due_at and hasattr(due_at, 'tzinfo') and due_at.tzinfo is not None:
        due_at = due_at.replace(tzinfo=None)

    task = await task_service.create_task(title, due_at, priority)
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(priority, "⚪️")
    due_str = due_at.strftime("%d.%m в %H:%M") if due_at else "Без срока"
    
    await message.answer(f"{emoji} Задача добавлена!\n📝 {task.title}\n🕐 {due_str}")
    
    ctx = user_context.get(message.from_user.id)
    if ctx:
        class FakeMessage:
            def __init__(self, user_id): 
                self.from_user = types.User(id=user_id, is_bot=False, first_name="User")
            async def answer(self, text, reply_markup=None): 
                pass
        await show_task_list(FakeMessage(message.from_user.id), ctx["title"], ctx["type"], ctx["val"], is_edit=False)

# ================= КОЛБЭККИ (ВОССТАНОВЛЕНА СТАРАЯ ЛОГИКА) =================
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
    
    # ✅ ПЕРЕКЛЮЧАЕМ СТАТУС (вкл/выкл) - СТАРАЯ РАБОЧАЯ ВЕРСИЯ
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
