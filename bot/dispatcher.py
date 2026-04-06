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

# ❗ ВАЖНО: Теперь храним СПИСКИ (order matters), а не наборы (sets)
selected_tasks = {}  # {user_id: [task_id_1, task_id_2, ...]}
user_context = {}    # {user_id: {"title": str, "tasks": list}}

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
    """Возвращает эмодзи цифры 1️⃣, 2️⃣... для индекса (0-based)"""
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    if index < len(emojis):
        return emojis[index]
    return str(index + 1) + "."

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
    for w in words:
        text = text.lower().replace(w, "")
    return text.strip().title()

def parse_date(text):
    now = datetime.now(tz)
    if "today" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return now.replace(hour=h, minute=mi, second=0, microsecond=0)
    elif "tomorrow" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
    try:
        p = dateparser.parse(text, settings={"TIMEZONE": TZ, "RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DATES_FROM": "future"})
        if p and (p - now) > timedelta(hours=1): return p
    except: pass
    return None

# ================= ОТОБРАЖЕНИЕ =================

async def show_task_list(message, tasks, title, save_context=True, is_edit=False):
    user_id = message.from_user.id
    # Инициализируем список для пользователя
    if user_id not in selected_tasks:
        selected_tasks[user_id] = []
    
    if save_context:
        user_context[user_id] = {"title": title, "tasks": tasks}

    if not tasks:
        text = "Tasks: empty"
        if is_edit:
            try: await message.edit_text(text, reply_markup=None)
            except TelegramBadRequest: pass
        else:
            await message.answer(text, reply_markup=get_main_menu_keyboard())
        return

    text = "Tasks: " + title + " (total " + str(len(tasks)) + ")\n\n"
    kb = []
    
    for t in tasks[:15]:
        current_list = selected_tasks[user_id]
        is_selected = t.id in current_list
        
        # 1. ПРИОРИТЕТ ИЛИ ГАЛОЧКА (если выполнено)
        if t.is_done:
            icon = "✅"  # Зеленая галочка для выполненных
        elif is_selected:
            # Если выделено - показываем цифру выбора
            idx = current_list.index(t.id)
            icon = get_selection_emoji(idx)
        else:
            # Иначе - приоритет
            if t.priority == "red": icon = "🔴"
            elif t.priority == "yellow": icon = "🟡"
            elif t.priority == "green": icon = "🟢"
            else: icon = "⚪️"
        
        short_title = t.title[:30] + "..." if len(t.title) > 30 else t.title
        if t.due_at:
            due_str = t.due_at.strftime("%d.%m %H:%M")
        else:
            due_str = "No date"
        
        btn_text = icon + " " + short_title + "\n" + due_str
            
        if t.is_done:
            cb_data = "noop_" + str(t.id)
        else:
            cb_data = "toggle_" + str(t.id)
            
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    # Кнопки действий — только если есть выделенные (цифры)
    if current_list:
        cnt = len(current_list)
        kb.append([
            InlineKeyboardButton(text="Done (" + str(cnt) + ")", callback_data="action_done"),
            InlineKeyboardButton(text="Del (" + str(cnt) + ")", callback_data="action_del"),
            InlineKeyboardButton(text="Later (" + str(cnt) + ")", callback_data="action_postpone")
        ])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)

    try:
        if is_edit:
            await message.edit_text(text, reply_markup=markup)
        else:
            await message.answer(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.warning("Edit error: " + str(e))

# ================= ОБРАБОТЧИКИ МЕНЮ =================

@dp.message(Command("start"))
async def cmd_start(message):
    await message.answer("Hi! I am your task planner.", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "Back")
async def go_back(message):
    await message.answer("Main menu:", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "Priority")
async def priority_menu(message):
    await message.answer("Choose priority level:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda m: m.text == "Period")
async def period_menu(message):
    await message.answer("Choose period:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "All Tasks")
async def all_tasks(message):
    tasks = await task_service.get_all_tasks()
    await show_task_list(message, tasks, "All")

@dp.message(lambda m: m.text in ["Red Urgent", "Yellow Medium", "Green Light"])
async def filter_importance(message):
    p_map = {"Red Urgent": "red", "Yellow Medium": "yellow", "Green Light": "green"}
    priority = p_map[message.text]
    all_t = await task_service.get_all_tasks()
    filtered = [t for t in all_t if t.priority == priority]
    await show_task_list(message, filtered, message.text)

@dp.message(lambda m: m.text in ["Today", "Tomorrow", "Week", "Month"])
async def filter_period(message):
    now = datetime.now(tz)
    title = message.text
    
    if title == "Today": tasks = await task_service.get_tasks_for_date(now.date())
    elif title == "Tomorrow": tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
    elif title == "Week": tasks = await task_service.get_tasks_for_week(now.date())
    elif title == "Month":
        all_t = await task_service.get_all_tasks()
        end = now.date() + timedelta(days=30)
        tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
    else: tasks = []
    
    await show_task_list(message, tasks, title)

# ================= ДОБАВЛЕНИЕ ЗАДАЧ =================

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
    
    task = await task_service.create_task(clean, due_at, priority, repeat)
    
    if priority == "red": emoji = "🔴"
    elif priority == "yellow": emoji = "🟡"
    elif priority == "green": emoji = "🟢"
    else: emoji = "⚪️"
    
    due_str = due_at.strftime("%d.%m at %H:%M") if due_at else "No date"
    reply = emoji + " Task added!\n" + task.title + "\n" + due_str
    await message.answer(reply, reply_markup=get_main_menu_keyboard())

# ================= КОЛБЭККИ (ВЫДЕЛЕНИЕ) =================

@dp.callback_query(lambda c: c.data.startswith("toggle_"))
async def process_toggle(callback):
    uid = callback.from_user.id
    tid = int(callback.data.split("_")[1])
    
    if uid not in selected_tasks:
        selected_tasks[uid] = []
    
    current_list = selected_tasks[uid]
    
    # Логика добавления в конец списка или удаления
    if tid in current_list:
        current_list.remove(tid) # Убираем, остальные сдвигаются (1️⃣, 2️⃣ меняются)
    else:
        current_list.append(tid) # Добавляем в конец (становится новой цифрой)
        
    await callback.answer("")
    
    ctx = user_context.get(uid)
    if ctx:
        # Обновляем сообщение, чтобы показать новые цифры
        await show_task_list(callback.message, ctx["tasks"], ctx["title"], save_context=False, is_edit=True)

@dp.callback_query(lambda c: c.data.startswith("action_"))
async def process_action(callback):
    uid = callback.from_user.id
    act = callback.data.split("_")[1]
    
    if uid not in selected_tasks or not selected_tasks[uid]:
        await callback.answer("Select tasks first!", show_alert=True)
        return
    
    tids = list(selected_tasks[uid]) # Копия списка ID
    msg = ""
    try:
        if act == "done":
            for tid in tids:
                t = await task_service.get_task_by_id(tid)
                await task_service.update_task(tid, is_done=True)
                if t and t.repeat_rule != "none" and t.due_at:
                    if t.repeat_rule == "daily": delta = timedelta(days=1)
                    elif t.repeat_rule == "weekly": delta = timedelta(weeks=1)
                    else: delta = timedelta(days=30)
                    await task_service.create_task(t.title, t.due_at + delta, t.priority, t.repeat_rule)
            msg = "Done: " + str(len(tids))
        elif act == "del":
            for tid in tids: await task_service.delete_task(tid)
            msg = "Deleted: " + str(len(tids))
        elif act == "postpone":
            for tid in tids:
                t = await task_service.get_task_by_id(tid)
                if t and t.due_at: await task_service.update_task(tid, due_at=t.due_at+timedelta(days=1))
            msg = "Postponed: " + str(len(tids))
    except Exception as e:
        msg = "Error: " + str(e)
    
    selected_tasks[uid].clear() # Очищаем выбор
    await callback.answer(msg)
    
    # Обновляем список (перезагружаем данные, чтобы убрать выполненные/удаленные)
    ctx = user_context.get(uid)
    if ctx:
        title = ctx["title"]
        if "All" in title: tasks = await task_service.get_all_tasks()
        elif "Red" in title: tasks = [t for t in await task_service.get_all_tasks() if t.priority=="red"]
        elif "Yellow" in title: tasks = [t for t in await task_service.get_all_tasks() if t.priority=="yellow"]
        elif "Green" in title: tasks = [t for t in await task_service.get_all_tasks() if t.priority=="green"]
        elif "Today" in title: tasks = await task_service.get_tasks_for_date(datetime.now(tz).date())
        elif "Tomorrow" in title: tasks = await task_service.get_tasks_for_date(datetime.now(tz).date()+timedelta(days=1))
        elif "Week" in title: tasks = await task_service.get_tasks_for_week(datetime.now(tz).date())
        elif "Month" in title: 
            now = datetime.now(tz)
            all_t = await task_service.get_all_tasks()
            tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= now.date()+timedelta(days=30)]
        else: tasks = []
        
        await show_task_list(callback.message, tasks, title, save_context=True, is_edit=True)

@dp.callback_query(lambda c: c.data.startswith("noop_"))
async def noop(callback):
    await callback.answer("Task already done", show_alert=False)
