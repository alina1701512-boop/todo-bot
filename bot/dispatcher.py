from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import dateparser
import re
import logging
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from config import TG_TOKEN, TZ
from services import task_service

logger = logging.getLogger(__name__)
selected_tasks = {}      # {user_id: {task_id, ...}}
user_context = {}        # {user_id: {"type": "priority", "val": "red"}} для обновления списка после действий
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

# ================= ПАРСИНГ =================

def parse_priority(text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ["красный", "срочно", "важно", "горит", "срочн", "критич"]): return "red"
    if any(w in text_lower for w in ["зеленый", "легко", "лайт", "обычн", "спокойн"]): return "green"
    return "none"

def parse_repeat(text: str) -> str:
    text_lower = text.lower()
    if "каждый день" in text_lower or "ежедневно" in text_lower: return "daily"
    if "каждую неделю" in text_lower or "еженедельно" in text_lower: return "weekly"
    if "каждый месяц" in text_lower or "ежемесячно" in text_lower: return "monthly"
    return "none"

def clean_title(text: str) -> str:
    words = ["красный", "срочно", "важно", "горит", "зеленый", "легко", "лайт", 
             "каждый день", "каждую неделю", "каждый месяц", "ежедневно", "еженедельно"]
    for w in words: text = text.lower().replace(w, "")
    return text.strip().title()

def parse_date(text):
    now = datetime.now(tz)
    if "сегодня" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0<=h<=23 and 0<=mi<=59: return now.replace(hour=h, minute=mi, second=0, microsecond=0)
    elif "завтра" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0<=h<=23 and 0<=mi<=59: return (now+timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
    try:
        p = dateparser.parse(text, settings={"TIMEZONE": TZ, "RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DATES_FROM": "future"})
        if p and (p-now)>timedelta(hours=1): return p
    except: pass
    return None

# ================= ОТОБРАЖЕНИЕ =================

async def show_task_list(message, tasks, title, save_context=True):
    user_id = message.from_user.id
    if user_id not in selected_tasks: selected_tasks[user_id] = set()
    
    if save_context:
        user_context[user_id] = {"title": title, "tasks": tasks}

    if not tasks:
        await message.answer(f"📋 {title}: пусто", reply_markup=get_main_menu_keyboard())
        return

    text = f"📋 <b>{title}:</b> (всего {len(tasks)})\n\n"
    kb = []
    
    for t in tasks[:15]:
        is_sel = t.id in selected_tasks[user_id]
        icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
        mark = "🔖 " if is_sel else ""
        short = (t.title[:25] + "...") if len(t.title) > 25 else t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
        btn_text = f"{mark}{icon} {short}\n🕐 {due}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_{t.id}" if not t.is_done else f"noop_{t.id}")])

    if selected_tasks[user_id]:
        cnt = len(selected_tasks[user_id])
        kb.append([
            InlineKeyboardButton(text=f"✔️ ({cnt})", callback_data="action_done"),
            InlineKeyboardButton(text=f"🗑 ({cnt})", callback_data="action_del"),
            InlineKeyboardButton(text=f"⏰ ({cnt})", callback_data="action_postpone")
        ])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

# ================= ОБРАБОТЧИКИ МЕНЮ =================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Я твой умный планировщик.", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔙 Назад")
async def go_back(message: types.Message):
    await message.answer("🔙 Главное меню:", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔥 Важность")
async def priority_menu(message: types.Message):
    await message.answer("🔥 Выбери уровень важности:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda m: m.text == "📅 Период")
async def period_menu(message: types.Message):
    await message.answer("📅 Выбери период:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "📋 Все задачи")
async def all_tasks(message: types.Message):
    tasks = await task_service.get_all_tasks()
    await show_task_list(message, tasks, "Все задачи")

# Фильтры важности
@dp.message(lambda m: m.text in ["🔴 Срочные", "🟡 Средние", "🟢 Лайтовые"])
async def filter_importance(message: types.Message):
    p_map = {"🔴 Срочные": "red", "🟡 Средние": "yellow", "🟢 Лайтовые": "green"}
    priority = p_map[message.text]
    all_t = await task_service.get_all_tasks()
    filtered = [t for t in all_t if t.priority == priority]
    await show_task_list(message, filtered, message.text)

# Фильтры периода
@dp.message(lambda m: m.text in ["Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"])
async def filter_period(message: types.Message):
    now = datetime.now(tz)
    title = message.text
    
    if title == "Сегодня":
        tasks = await task_service.get_tasks_for_date(now.date())
    elif title == "Завтра":
        tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
    elif title == "📆 Неделя":
        tasks = await task_service.get_tasks_for_week(now.date())
    elif title == "🗓️ Месяц":
        all_t = await task_service.get_all_tasks()
        end = now.date() + timedelta(days=30)
        tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
    else: tasks = []
    
    await show_task_list(message, tasks, title)

# ================= ДОБАВЛЕНИЕ ЗАДАЧ =================

@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "📋 Все задачи", "🔥 Важность", "📅 Период", "🔙 Назад",
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые", 
    "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"
])
async def handle_text(message: types.Message):
    text = message.text.strip()
    priority = parse_priority(text)
    repeat = parse_repeat(text)
    clean = clean_title(text)
    due_at = parse_date(text)
    
    task = await task_service.create_task(clean, due_at, priority, repeat)
    
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(priority, "⚪️")
    due_str = due_at.strftime("%d.%m в %H:%M") if due_at else "Без срока"
    await message.answer(f"{emoji} Задача добавлена!\n📝 {task.title}\n🕐 {due_str}", reply_markup=get_main_menu_keyboard())

# ================= КОЛБЭККИ =================

@dp.callback_query(lambda c: c.data.startswith("toggle_"))
async def process_toggle(callback: types.CallbackQuery):
    uid = callback.from_user.id
    tid = int(callback.data.split("_")[1])
    if uid not in selected_tasks: selected_tasks[uid] = set()
    
    task = await task_service.get_task_by_id(tid)
    name = task.title[:30] if task else "Задача"
    
    if tid in selected_tasks[uid]:
        selected_tasks[uid].remove(tid)
        await callback.answer(f"⬜️ {name}", show_alert=False, cache_time=0)
    else:
        selected_tasks[uid].add(tid)
        await callback.answer(f"🔖 {name}", show_alert=False, cache_time=0)
    
    await callback.message.delete()
    # Возвращаем тот же список, где пользователь был
    ctx = user_context.get(uid)
    if ctx: await show_task_list(callback.message, ctx["tasks"], ctx["title"], save_context=False)

@dp.callback_query(lambda c: c.data.startswith("action_"))
async def process_action(callback: types.CallbackQuery):
    uid = callback.from_user.id
    act = callback.data.split("_")[1]
    
    if uid not in selected_tasks or not selected_tasks[uid]:
        await callback.answer("❌ Сначала выдели задачи!", show_alert=True)
        return
    
    tids = list(selected_tasks[uid])
    msg = ""
    try:
        if act == "done":
            for tid in tids:
                t = await task_service.get_task_by_id(tid)
                await task_service.update_task(tid, is_done=True)
                if t and t.repeat_rule != "none" and t.due_at:
                    delta = timedelta(days=1) if t.repeat_rule=="daily" else (timedelta(weeks=1) if t.repeat_rule=="weekly" else timedelta(days=30))
                    await task_service.create_task(t.title, t.due_at + delta, t.priority, t.repeat_rule)
            msg = f"✅ Выполнено: {len(tids)}"
        elif act == "del":
            for tid in tids: await task_service.delete_task(tid)
            msg = f"🗑 Удалено: {len(tids)}"
        elif act == "postpone":
            for tid in tids:
                t = await task_service.get_task_by_id(tid)
                if t and t.due_at: await task_service.update_task(tid, due_at=t.due_at+timedelta(days=1))
            msg = f"⏰ Перенесено: {len(tids)}"
    except Exception as e: msg = f"❌ {e}"
    
    selected_tasks[uid].clear()
    await callback.answer(msg)
    await callback.message.delete()
    
    ctx = user_context.get(uid)
    if ctx:
        # Перезагружаем список, чтобы убрать выполненные/удаленные
        if "все" in ctx["title"].lower(): tasks = await task_service.get_all_tasks()
        elif "срочн" in ctx["title"].lower(): tasks = [t for t in await task_service.get_all_tasks() if t.priority=="red"]
        elif "средн" in ctx["title"].lower(): tasks = [t for t in await task_service.get_all_tasks() if t.priority=="yellow"]
        elif "лайт" in ctx["title"].lower(): tasks = [t for t in await task_service.get_all_tasks() if t.priority=="green"]
        elif "сегодня" in ctx["title"].lower(): tasks = await task_service.get_tasks_for_date(datetime.now(tz).date())
        elif "завтра" in ctx["title"].lower(): tasks = await task_service.get_tasks_for_date(datetime.now(tz).date()+timedelta(days=1))
        elif "неделя" in ctx["title"].lower(): tasks = await task_service.get_tasks_for_week(datetime.now(tz).date())
        elif "месяц" in ctx["title"].lower(): 
            now = datetime.now(tz)
            all_t = await task_service.get_all_tasks()
            tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= now.date()+timedelta(days=30)]
        else: tasks = ctx["tasks"]
        
        await show_task_list(callback.message, tasks, ctx["title"], save_context=False)

@dp.callback_query(lambda c: c.data.startswith("noop_"))
async def noop(callback: types.CallbackQuery):
    await callback.answer("Задача уже выполнена", show_alert=False)
