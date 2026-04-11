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

logger = logging.getLogger(__name__)
user_context = {}
tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

ITEMS_PER_PAGE = 10

# ================= КЛАВИАТУРЫ =================
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Все задачи")],
        [KeyboardButton(text="🤖 AI Чат")],
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
        priority_order = {"red": 0, "yellow": 1, "green": 2, "none": 3}.get(task.priority, 3)
    
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

# ================= ОТРИСОВКА СПИСКА =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False, page_offset=0):
    user_id = message.from_user.id
    
    # Получаем задачи
    if filter_type == "all": 
        all_tasks = await task_service.get_all_tasks()
    elif filter_type == "priority":
        all_t = await task_service.get_all_tasks()
        all_tasks = [t for t in all_t if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Сегодня": 
            all_tasks = await task_service.get_tasks_for_date(now.date())
        elif filter_val == "Завтра": 
            all_tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
        elif filter_val == "📆 Неделя": 
            all_tasks = await task_service.get_tasks_for_week(now.date())
        elif filter_val == "🗓️ Месяц":
            all_t = await task_service.get_all_tasks()
            end = now.date() + timedelta(days=30)
            all_tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
        else: 
            all_tasks = []
    else: 
        all_tasks = []
    
    # Фильтруем по пользователю
    uid_str = str(user_id)
    all_tasks = [t for t in all_tasks if t.user_id is None or str(t.user_id) == uid_str]
    
    # Разделяем на активные и выполненные
    active_tasks = [t for t in all_tasks if not t.is_done]
    completed_tasks = [t for t in all_tasks if t.is_done]
    
    # Сортируем активные
    sorted_active = sort_tasks_by_priority_and_time(active_tasks)
    
    # Объединяем
    all_tasks = sorted_active + completed_tasks
    total = len(all_tasks)
    
    # Корректируем offset
    if page_offset >= total and total > 0: 
        page_offset = ((total - 1) // ITEMS_PER_PAGE) * ITEMS_PER_PAGE
    if page_offset < 0: 
        page_offset = 0
    
    # Сохраняем контекст
    user_context.setdefault(user_id, {})
    user_context[user_id].update({
        "title": title, 
        "type": filter_type, 
        "val": filter_val, 
        "offset": page_offset
    })

    if total == 0:
        text = "📋 Задач нет"
        kb = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")]]
        markup = InlineKeyboardMarkup(inline_keyboard=kb)
    else:
        total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        current_page = (page_offset // ITEMS_PER_PAGE) + 1
        page_tasks = all_tasks[page_offset : page_offset + ITEMS_PER_PAGE]

        active_count = len(active_tasks)
        completed_count = len(completed_tasks)
        text = f"{title}\n📊 Активных: {active_count} | ✅ Выполнено: {completed_count}\n📄 Страница {current_page} из {total_pages}\n\n"
        
        kb = []
        for t in page_tasks:
            if t.is_done:
                icon = "✅"
            else:
                icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
            
            task_text = t.title
            due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
            cb = f"done_{t.id}" if t.is_done else f"task_{t.id}"
            
            kb.append([InlineKeyboardButton(text=f"{icon} {task_text} | 🕐 {due}", callback_data=cb)])
        
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
        if "message is not modified" not in str(e):
            logger.error(f"❌ Edit failed: {e}")
    except Exception as e:
        logger.error(f"❌ Error in show_task_list: {e}")

# ================= ОБРАБОТЧИКИ МЕНЮ =================
@dp.message(Command("start"))
async def cmd_start(message): 
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await message.answer("👋 Привет! Я твой AI-планировщик.", reply_markup=get_main_menu_keyboard())

@dp.message(lambda m: m.text == "🔙 Назад")
async def go_back(message): 
    user_context.setdefault(message.from_user.id, {})["ai_mode"] = False
    await message.answer("🔙 Главное меню:", reply_markup=get_main_menu_keyboard())

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
    await show_task_list(message, "📋 Все задачи", "all", None, page_offset=0)

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
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые", "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"
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

# ================= КОЛБЭККИ =================
@dp.callback_query(lambda c: c.data == "refresh")
async def refresh_list(callback):
    ctx = user_context.get(callback.from_user.id)
    if ctx:
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True, page_offset=0)
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
        if not task:
            await callback.answer("❌ Задача не найдена", show_alert=True)
            return
        
        if task.user_id is not None and str(task.user_id) != str(uid):
            await callback.answer("❌ Это не твоя задача!", show_alert=True)
            return
        
        await task_service.update_task(tid, is_done=not task.is_done)
        await callback.answer()
        
        ctx = user_context.get(uid, {})
        title = ctx.get("title", "📋 Все задачи")
        filter_type = ctx.get("type", "all")
        filter_val = ctx.get("val")
        
        await show_task_list(callback.message, title, filter_type, filter_val, is_edit=True, page_offset=0)
            
    except Exception as e:
        logger.error(f"❌ handle_task_click error: {e}")
        await show_task_list(callback.message, "📋 Все задачи", "all", None, is_edit=True, page_offset=0)
        await callback.answer("⚠️ Ошибка", show_alert=True)
