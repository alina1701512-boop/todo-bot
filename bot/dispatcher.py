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
selected_tasks = {}      # {user_id: {task_id, ...}}
user_context = {}        # {user_id: {"title": str, "tasks": list}}
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

async def show_task_list(message, tasks, title, save_context=True, is_edit=False):
    user_id = message.from_user.id
    if user_id not in selected_tasks: selected_tasks[user_id] = set()
    
    if save_context:
        user_context[user_id] = {"title": title, "tasks": tasks}

    if not tasks:
        text = f"📋 {title}: пусто"
        if is_edit:
            try: await message.edit_text(text, reply_markup=None)
            except TelegramBadRequest: pass
        else:
            await message.answer(text, reply_markup=get_main_menu_keyboard())
        return

    text = f"📋 <b>{title}:</b> (всего {len(tasks)})\n\n"
    kb = []
    
    for t in tasks[:15]:
        is_sel = t.id in selected_tasks[user_id]
        icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
        
        # ✅ ЗАКЛАДКА ПОЯВЛЯЕТСЯ ПРЯМО НА КНОПКЕ
        if is_sel:
            btn_text = f"🔖 {t.title[:30]}{'...' if len(t.title)>30 else ''}\n🕐 {t.due_at.strftime('%d.%m %H:%M') if t.due_at else 'Без срока'}"
        else:
            btn_text = f"{icon} {t.title[:30]}{'...' if len(t.title)>30 else ''}\n🕐 {t.due_at.strftime('%d.%m %H:%M') if t.due_at else 'Без срока'}"
            
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_{t.id}" if not t.is_done else f"noop_{t.id}")])

    # ✅ КНОПКИ ДЕЙСТВИЙ ПОЯВЛЯЮТСЯ ТОЛЬКО ЕСЛИ ЕСТЬ ВЫДЕЛЕННЫЕ
    if selected_tasks[user_id]:
        cnt = len(selected_tasks[user_id])
        kb.append([
            InlineKeyboardButton(text=f"✔️ Выполнить ({cnt})", callback_data="action_done"),
            InlineKeyboardButton(text=f"🗑 Удалить ({cnt})", callback_data="action_del"),
            InlineKeyboardButton(text=f"⏰ Перенести ({cnt})", callback_data="action_postpone")
        ])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)

    try:
        if is_edit:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.warning(f"Edit error: {e}")

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

@dp.message(lambda m: m.text in ["🔴 Срочные", "🟡 Средние", "🟢 Лайтовые"])
async def filter_importance(message: types.Message):
    p_map = {"🔴 Срочные": "red", "🟡 Средние": "yellow", "🟢 Лайтовые": "green"}
    priority = p_map[message.text]
    all_t = await task_service.get_all_tasks()
    filtered = [t for t in all_t if t.priority == priority]
    await show_task_list(message, filtered, message.text)

@dp.message(lambda m: m.text in ["Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"])
async def filter_period(message: types.Message):
    now = datetime.now(tz)
    title = message.text
    
    if title == "Сегодня": tasks = await task_service.get_tasks_for_date(now.date())
    elif title == "Завтра": tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
    elif title == "📆 Неделя": tasks = await task_service.get_tasks_for_week(now.date())
    elif title == "🗓️ Месяц":
        all_t = await task_service.get_all_tasks()
        end = now.date() + timedelta(days=30)
        tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
    else: tasks = []
    
    await show_task_list(message, tasks, title)

# ================= ДОБАВЛЕНИЕ ЗАДАЧ =================

@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "📋 Все
