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
selected_tasks = {}
tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- КЛАВИАТУРЫ ---
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Все задачи"), KeyboardButton(text="📅 Сегодня")],
        [KeyboardButton(text="📅 Завтра"), KeyboardButton(text="➕ Добавить")],
        [KeyboardButton(text="🔴 Срочные"), KeyboardButton(text="🟡 Средние")],
        [KeyboardButton(text="📆 Неделя"), KeyboardButton(text="⚙️ Меню")]
    ], resize_keyboard=True)

def get_priority_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔴 Важные сегодня"), KeyboardButton(text="🟢 Важные завтра")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

# --- ПАРСИНГ ПРИОРИТЕТОВ ---
def parse_priority(text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ["красный", "срочно", "важно", "горит", "срочн", "критич"]):
        return "red"
    if any(w in text_lower for w in ["зеленый", "легко", "лайт", "обычн", "спокойн"]):
        return "green"
    return "yellow"

def parse_repeat(text: str) -> str:
    text_lower = text.lower()
    if "каждый день" in text_lower or "ежедневно" in text_lower: return "daily"
    if "каждую неделю" in text_lower or "еженедельно" in text_lower: return "weekly"
    if "каждый месяц" in text_lower or "ежемесячно" in text_lower: return "monthly"
    return "none"

def clean_title(text: str) -> str:
    words_to_remove = ["красный", "срочно", "важно", "горит", "зеленый", "легко", "лайт", 
                       "каждый день", "каждую неделю", "каждый месяц", "ежедневно", "еженедельно"]
    for w in words_to_remove:
        text = text.lower().replace(w, "")
    return text.strip().title()

# --- КОМАНДЫ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = "👋 Привет! Я твой умный планировщик.\n\n"
    text += "<b>Примеры:</b>\n"
    text += "- Купить молоко красный завтра 18:00\n"
    text += "- Позвонить врачу зеленый каждый день\n"
    text += "- Отчёт важно каждую неделю в 10:00"
    
    await message.answer(text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

@dp.message(lambda message: message.text == "⚙️ Меню")
async def show_extended_menu(message: types.Message):
    await message.answer("⚙️ Фильтры по важности:", reply_markup=get_priority_menu_keyboard())

@dp.message(lambda message: message.text == "🔙 Назад")
async def menu_back(message: types.Message):
    await message.answer("🔙 Главное меню", reply_markup=get_main_menu_keyboard())

@dp.message(lambda message: message.text in ["📋 Все задачи", "📅 Сегодня", "📅 Завтра", "📆 Неделя", 
                                            "🔴 Срочные", "🟡 Средние", "🔴 Важные сегодня", "🟢 Важные завтра"])
async def handle_menu_buttons(message: types.Message):
    text = message.text
    now = datetime.now(tz)
    
    if text == "📋 Все задачи": await show_tasks_interactive(message)
    elif text == "📅 Сегодня": await show_tasks_interactive(message, custom_tasks=await task_service.get_tasks_for_date(now.date()), title="Сегодня")
    elif text == "📅 Завтра": await show_tasks_interactive(message, custom_tasks=await task_service.get_tasks_for_date(now.date()+timedelta(days=1)), title="Завтра")
    elif text == "📆 Неделя": await show_tasks_interactive(message, custom_tasks=await task_service.get_tasks_for_week(now.date()), title="Неделя")
    elif text == "🔴 Срочные": await show_tasks_interactive(message, custom_tasks=await task_service.get_all_tasks(), title="Срочные", priority_filter="red")
    elif text == "🟡 Средние": await show_tasks_interactive(message, custom_tasks=await task_service.get_all_tasks(), title="Средние", priority_filter="yellow")
    elif text == "🔴 Важные сегодня": await show_tasks_interactive(message, custom_tasks=await task_service.get_tasks_for_date(now.date(), "red"), title="Важные сегодня")
    elif text == "🟢 Важные завтра": await show_tasks_interactive(message, custom_tasks=await task_service.get_tasks_for_date(now.date()+timedelta(days=1), "red"), title="Важные завтра")

@dp.message(lambda message: message.text == "➕ Добавить")
async def start_add_task(message: types.Message):
    await message.answer("📝 Напиши задачу.\nПример: <i>Купить хлеб красный завтра 18:00</i>", reply_markup=get_cancel_keyboard(), parse_mode="HTML")

@dp.message(lambda message: message.text == "❌ Отмена")
async def cancel_action(message: types.Message):
    await message.answer("❌ Отменено", reply_markup=get_main_menu_keyboard())

# --- ОБРАБОТКА ТЕКСТА (ДОБАВЛЕНИЕ) ---
@dp.message(lambda message: message.text and not message.text.startswith('/') and message.text not in [
    "📋 Все задачи", "📅 Сегодня", "📅 Завтра", "➕ Добавить", "📆 Неделя", "⚙️ Меню", 
    "🔴 Срочные", "🟡 Средние", "🔴 Важные сегодня", "🟢 Важные завтра", "🔙 Назад", "❌ Отмена"
])
async def handle_task_input(message: types.Message):
    text = message.text.strip()
    priority = parse_priority(text)
    repeat = parse_repeat(text)
    clean = clean_title(text)
    
    due_at = parse_date(text)
    task = await task_service.create_task(clean, due_at, priority, repeat)
    
    # Google Calendar (временно отключено для скорости)
    # try:
    #     from calendar_service import create_google_event
    #     await create_google_event(clean, due_at.isoformat() if due_at else None)
    # except: pass

    emoji = "🔴" if priority=="red" else ("🟡" if priority=="yellow" else "🟢")
    # ✅ ИСПРАВЛЕНО: используем due_at.strftime() вместо task.format_due()
    due_str = due_at.strftime("%d.%m в %H:%M") if due_at else "Без срока"
    await message.answer(f"{emoji} Задача добавлена!\n📝 {task.title}\n🕐 {due_str}", reply_markup=get_main_menu_keyboard())

# --- ИНТЕРАКТИВНЫЙ СПИСОК ---
async def show_tasks_interactive(message, custom_tasks=None, title="Задачи", priority_filter=None):
    user_id = message.from_user.id
    if user_id not in selected_tasks: selected_tasks[user_id] = set()
    
    tasks = custom_tasks if custom_tasks is not None else await task_service.get_all_tasks()
    if priority_filter:
        tasks = [t for t in tasks if t.priority == priority_filter and not t.is_done]

    if not tasks:
        await message.answer(f"📋 {title}: пусто", reply_markup=get_main_menu_keyboard())
        return

    text = f"📋 <b>{title}:</b>\n\n"
    kb = []
    for t in tasks[:15]:
        icon = "🏁" if t.is_done else ("🔴" if t.priority=="red" else ("🟢" if t.priority=="green" else "🟡"))
        sel = "✅" if t.id in selected_tasks[user_id] else "⬜️"
        short = (t.title[:25]+"...") if len(t.title)>25 else t.title
        
        # Форматируем дату для отображения
        if t.due_at:
            due_display = t.due_at.strftime("%d.%m %H:%M")
        else:
            due_display = "Без срока"
        
        kb.append([InlineKeyboardButton(text=f"{sel} {icon} {short}\n🕐 {due_display}", callback_data=f"toggle_{t.id}" if not t.is_done else f"noop_{t.id}")])

    if selected_tasks[user_id]:
        cnt = len(selected_tasks[user_id])
        kb.append([
            InlineKeyboardButton(text=f"✔️ ({cnt})", callback_data="action_done"),
            InlineKeyboardButton(text=f"🗑 ({cnt})", callback_data="action_del"),
            InlineKeyboardButton(text=f"⏰ ({cnt})", callback_data="action_postpone")
        ])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

# --- КОЛБЭККИ ---
@dp.callback_query(lambda c: c.data.startswith("toggle_"))
async def process_toggle(callback: types.CallbackQuery):
    uid = callback.from_user.id
    tid = int(callback.data.split("_")[1])
    if uid not in selected_tasks: selected_tasks[uid] = set()
    if tid in selected_tasks[uid]: selected_tasks[uid].remove(tid)
    else: selected_tasks[uid].add(tid)
    await callback.answer()
    await callback.message.delete()
    await show_tasks_interactive(callback.message)

@dp.callback_query(lambda c: c.data.startswith("action_"))
async def process_mass_action(callback: types.CallbackQuery):
    uid = callback.from_user.id
    act = callback.data.split("_")[1]
    if uid not in selected_tasks or not selected_tasks[uid]:
        await callback.answer("Выберите задачи!"); return
    
    tids = list(selected_tasks[uid])
    msg = ""
    try:
        if act == "done":
            for tid in tids:
                t = await task_service.get_task_by_id(tid)
                await task_service.update_task(tid, is_done=True)
                # Повторяющиеся задачи
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
    await show_tasks_interactive(callback.message)

@dp.callback_query(lambda c: c.data.startswith("noop_"))
async def noop(callback: types.CallbackQuery):
    await callback.answer("Задача выполнена", show_alert=False)

# --- УТИЛИТЫ ---
def parse_date(text):
    """Parse date - возвращает naive datetime для совместимости с БД"""
    now = datetime.now()  # ✅ Naive datetime (без timezone)
    
    if "сегодня" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0<=h<=23 and 0<=mi<=59:
                return now.replace(hour=h, minute=mi, second=0, microsecond=0)
    elif "завтра" in text.lower():
        m = re.search(r'(\d{1,2}):(\d{2})', text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0<=h<=23 and 0<=mi<=59:
                return (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
    
    try:
        # ✅ RETURN_AS_TIMEZONE_AWARE: False — возвращает naive datetime
        p = dateparser.parse(text, settings={
            "TIMEZONE": TZ, 
            "RETURN_AS_TIMEZONE_AWARE": False, 
            "PREFER_DATES_FROM": "future"
        })
        if p and (p - now) > timedelta(hours=1):
            return p
    except: 
        pass
    return None
