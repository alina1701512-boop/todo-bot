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

logger = logging.getLogger(__name__)

# Состояние пользователя
user_context = {} # {user_id: {"filter_type": "all", "filter_val": None}}
user_edit_mode = {} # {user_id: True/False} (Режим выбора цифр)
tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# ================= КЛАВИАТУРЫ =================
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="All Tasks")],
        [KeyboardButton(text="Priority"), KeyboardButton(text="Period")]
    ], resize_keyboard=True)

def get_priority_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Red Urgent"), KeyboardButton(text="Yellow Medium")],
        [KeyboardButton(text="Green Light"), KeyboardButton(text="Back")]
    ], resize_keyboard=True)

def get_period_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Today"), KeyboardButton(text="Tomorrow")],
        [KeyboardButton(text="Week"), KeyboardButton(text="Month")],
        [KeyboardButton(text="Back")]
    ], resize_keyboard=True)

# ================= УТИЛИТЫ =================
def get_selection_emoji(index):
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    return emojis[index] if index < len(emojis) else f"{index+1}."

def parse_priority(text):
    t = text.lower()
    if any(w in t for w in ["red", "urgent", "important", "critical"]): return "red"
    if any(w in t for w in ["green", "light", "easy", "calm"]): return "green"
    return "none"

def parse_repeat(text):
    t = text.lower()
    if "daily" in t or "every day" in t: return "daily"
    if "weekly" in t or "every week" in t: return "weekly"
    if "monthly" in t or "every month" in t: return "monthly"
    return "none"

def clean_title(text):
    words = ["red", "urgent", "important", "green", "light", "easy", 
             "daily", "weekly", "monthly", "every day", "every week", "every month"]
    for w in words: text = text.lower().replace(w, "")
    return text.strip().title()

def parse_date(text):
    now = datetime.now(tz)
    if "today" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mi <= 59: return now.replace(hour=h, minute=mi, second=0, microsecond=0)
    elif "tomorrow" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mi <= 59: return (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
    try:
        p = dateparser.parse(text, settings={"TIMEZONE": TZ, "RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DATES_FROM": "future"})
        if p and (p - now) > timedelta(hours=1): return p
    except: pass
    return None

# ================= ОТРИСОВКА СПИСКА =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False):
    user_id = message.from_user.id
    is_edit_mode = user_edit_mode.get(user_id, False)
    
    # Сохраняем контекст (какой фильтр сейчас активен)
    user_context[user_id] = {"title": title, "type": filter_type, "val": filter_val}

    # Получаем задачи из БД заново (чтобы данные были свежие)
    if filter_type == "all":
        tasks = await task_service.get_all_tasks()
    elif filter_type == "priority":
        all_tasks = await task_service.get_all_tasks()
        tasks = [t for t in all_tasks if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Today": tasks = await task_service.get_tasks_for_date(now.date())
        elif filter_val == "Tomorrow": tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
        elif filter_val == "Week": tasks = await task_service.get_tasks_for_week(now.date())
        elif filter_val == "Month":
            all_tasks = await task_service.get_all_tasks()
            end = now.date() + timedelta(days=30)
            tasks = [t for t in all_tasks if t.due_at and now.date() <= t.due_at.date() <= end]
        else: tasks = []
    else:
        tasks = []

    if not tasks:
        text = "Tasks: empty"
        kb = [InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh")]
        if is_edit:
            try: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
            except: pass
        else:
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
        return

    text = f"Tasks: {title} ({len(tasks)})\n\n"
    kb = []

    # Кнопка переключения режима выбора
    mode_btn_text = "✅ Normal Mode" if is_edit_mode else "✏️ Select Mode"
    kb.append([InlineKeyboardButton(text=mode_btn_text, callback_data="toggle_mode")])
    
    # Если режим выбора активен - кнопка действий
    if is_edit_mode:
        kb.append([InlineKeyboardButton(text="🗑 Delete Selected", callback_data="action_del")])

    for t in tasks[:20]:
        # Логика иконки
        if t.is_done:
            icon = "✅" # Выполнено
        elif is_edit_mode:
            # В режиме выбора - иконка не меняется, но добавим цифру в текст если выбрано
            # Но для простоты: в режиме выбора мы просто выделяем
            icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
        else:
            icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
            
        short = (t.title[:30] + "...") if len(t.title) > 30 else t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "No date"
        
        btn_text = f"{icon} {short}\n{due}"
        
        # Если режим выбора - добавляем цифру (нужно будет хранить выбранные ID)
        # Для простоты реализации "Клик = Выполнить", режим выбора пока просто показывает кнопку удаления
        
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
    await message.answer("Hi! Task planner ready.", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "Back")
async def go_back(message):
    await message.answer("Main menu:", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "Priority")
async def priority_menu(message):
    await message.answer("Choose priority:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda m: m.text == "Period")
async def period_menu(message):
    await message.answer("Choose period:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "All Tasks")
async def all_tasks(message):
    await show_task_list(message, "All", "all", None)

@dp.message(lambda m: m.text in ["Red Urgent", "Yellow Medium", "Green Light"])
async def filter_importance(message):
    p_map = {"Red Urgent": "red", "Yellow Medium": "yellow", "Green Light": "green"}
    await show_task_list(message, message.text, "priority", p_map[message.text])

@dp.message(lambda m: m.text in ["Today", "Tomorrow", "Week", "Month"])
async def filter_period(message):
    await show_task_list(message, message.text, "period", message.text)

# ================= ДОБАВЛЕНИЕ =================
@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "All Tasks", "Priority", "Period", "Back",
    "Red Urgent", "Yellow Medium", "Green Light",
    "Today", "Tomorrow", "Week", "Month"
])
async def handle_text(message):
    text = message.text.strip()
    priority = parse_priority(text)
    repeat = parse_repeat(text)
    clean = clean_title(text)
    due_at = parse_date(text)
    await task_service.create_task(clean, due_at, priority, repeat)
    await message.answer("Task added!", reply_markup=get_main_menu_keyboard())

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
    is_edit_mode = user_edit_mode.get(uid, False)

    if is_edit_mode:
        # В режиме выбора - пока просто алерт (можно доработать выделение позже)
        await callback.answer("Select mode active. Click Delete to remove.")
    else:
        # ОБЫЧНЫЙ РЕЖИМ: КЛИК = ВЫПОЛНЕНО
        await task_service.update_task(tid, is_done=True)
        await callback.answer("✅ Done!")
        
        # Обновляем список
        ctx = user_context.get(uid)
        if ctx:
            await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)

@dp.callback_query(lambda c: c.data == "action_del")
async def delete_selected(callback):
    # Заглушка для удаления. В будущем можно добавить логику выделения.
    await callback.answer("Select mode: Delete logic coming soon.")
