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
from services.ai_parser import parse_task_with_ai, make_naive, chat_with_ai, get_task_tips

logger = logging.getLogger(__name__)
user_context = {}
user_edit_mode = {}
tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# Настройки пагинации
ITEMS_PER_PAGE = 8

# ================= КЛАВИАТУРЫ =================
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Все задачи"), KeyboardButton(text="🤖 AI Чат")],
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

# ================= ОТРИСОВКА СПИСКА (С ПАГИНАЦИЕЙ И СЧЕТЧИКОМ) =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False):
    user_id = message.from_user.id
    
    # Инициализация контекста
    if user_id not in user_context:
        user_context[user_id] = {"offset": 0}
    
    # Сохраняем параметры фильтра, но НЕ сбрасываем offset, если он уже есть
    current_ctx = user_context[user_id]
    current_ctx.update({"title": title, "type": filter_type, "val": filter_val})
    
    offset = current_ctx.get("offset", 0)

    # Загрузка задач из БД
    if filter_type == "all": all_tasks = await task_service.get_all_tasks()
    elif filter_type == "priority":
        all_t = await task_service.get_all_tasks()
        all_tasks = [t for t in all_t if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Сегодня": all_tasks = await task_service.get_tasks_for_date(now.date())
        elif filter_val == "Завтра": all_tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1))
        elif filter_val == "📆 Неделя": all_tasks = await task_service.get_tasks_for_week(now.date())
        elif filter_val == "🗓️ Месяц":
            all_t = await task_service.get_all_tasks()
            end = now.date() + timedelta(days=30)
            all_tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
        else: all_tasks = []
    else: all_tasks = []

    total_tasks = len(all_tasks)
    
    if total_tasks == 0:
        text = "📋 Задач нет"
        kb = [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")]
        try:
            if is_edit: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
            else: await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
        except: pass
        return

    # 🔥 ВЫЧИСЛЯЕМ СТРАНИЦЫ
    total_pages = (total_tasks + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    current_page = (offset // ITEMS_PER_PAGE) + 1
    
    # Берем только задачи для текущей страницы
    page_tasks = all_tasks[offset : offset + ITEMS_PER_PAGE]

    # Формируем текст заголовка (Счетчик страниц!)
    text = f"📋 {title} (всего {total_tasks})\n📄 Страница {current_page} из {total_pages}\n\n"
    
    kb = []

    # ✅ УБРАЛИ КНОПКУ "РЕЖИМ ВЫБОРА" для чистоты интерфейса

    # Отрисовка задач на текущей странице
    for t in page_tasks:
        if t.is_done:
            icon = "✅"
            cb_data = f"done_{t.id}"
        else:
            icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
            cb_data = f"task_{t.id}"
            
        short = (t.title[:30] + "...") if len(t.title) > 30 else t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
        kb.append([InlineKeyboardButton(text=f"{icon} {short}\n🕐 {due}", callback_data=cb_data)])

    # 🔥 КНОПКИ НАВИГАЦИИ (Вперед/Назад)
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="page_prev"))
    
    if offset + ITEMS_PER_PAGE < total_tasks:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data="page_next"))
    
    if nav_row:
        kb.append(nav_row)

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    try:
        if is_edit: await message.edit_text(text, reply_markup=markup)
        else: await message.answer(text, reply_markup=markup)
    except TelegramBadRequest: pass

# ================= ОБРАБОТЧИКИ МЕНЮ =================
@dp.message(Command("start"))
async def cmd_start(message): await message.answer("👋 Привет! Я твой AI-планировщик.", reply_markup=get_main_menu_keyboard())
@dp.message(lambda m: m.text == "🔙 Назад")
async def go_back(message): await message.answer("🔙 Главное меню:", reply_markup=get_main_menu_keyboard())
@dp.message(lambda m: m.text == "🔥 Важность")
async def priority_menu(message): await message.answer("🔥 Выбери важность:", reply_markup=get_priority_menu_keyboard())
@dp.message(lambda m: m.text == "📅 Период")
async def period_menu(message): await message.answer("📅 Выбери период:", reply_markup=get_period_menu_keyboard())

@dp.message(lambda m: m.text == "📋 Все задачи")
async def all_tasks(message):
    uid = message.from_user.id
    user_context[uid] = {"title": "Все задачи", "type": "all", "val": None, "offset": 0}
    await show_task_list(message, "Все задачи", "all", None)

@dp.message(lambda m: m.text in ["🔴 Срочные", "🟡 Средние", "🟢 Лайтовые"])
async def filter_importance(message):
    uid = message.from_user.id
    p_map = {"🔴 Срочные": "red", "🟡 Средние": "yellow", "🟢 Лайтовые": "green"}
    user_context[uid] = {"title": message.text, "type": "priority", "val": p_map[message.text], "offset": 0}
    await show_task_list(message, message.text, "priority", p_map[message.text])

@dp.message(lambda m: m.text in ["Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"])
async def filter_period(message):
    uid = message.from_user.id
    user_context[uid] = {"title": message.text, "type": "period", "val": message.text, "offset": 0}
    await show_task_list(message, message.text, "period", message.text)

# ================= AI ЧАТ =================
@dp.message(lambda m: m.text == "🤖 AI Чат" or m.text.startswith("/ai "))
async def chat_with_ai_handler(message: types.Message):
    user_text = message.text.replace("🤖 AI Чат", "").replace("/ai", "").strip()
    if not user_text:
        await message.answer("✏️ Напиши вопрос после /ai\nНапример: /ai Придумай 3 идеи для ужина")
        return
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    reply = await chat_with_ai(user_text)
    await message.answer(reply or "❌ Не удалось получить ответ. Попробуй позже.")

# ================= СТАТИСТИКА =================
@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    stats = await task_service.get_task_stats()
    text = (f"📊 **Твоя статистика:**\n\n"
            f"📦 Всего задач: {stats['total']}\n"
            f"✅ Выполнено: {stats['done']}\n"
            f"⏳ В работе: {stats['pending']}\n"
            f"🔴 Просрочено: {stats['overdue']}\n\n"
            f" По приоритетам:\n"
            f"🔴 Срочные: {stats['red']} | 🟡 Средние: {stats['yellow']} | 🟢 Лайтовые: {stats['green']}")
    await message.answer(text, parse_mode="Markdown")

# ================= ДОБАВЛЕНИЕ ЗАДАЧ =================
@dp.message(lambda m: m.text and not m.text.startswith('/') and m.text not in [
    "📋 Все задачи", "🔥 Важность", "📅 Период", "🔙 Назад", "🤖 AI Чат",
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые", "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"
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
    
    tips = await get_task_tips(task.title, due_str, priority)
    if tips:
        await message.answer(f"💡 **AI совет:** {tips}", parse_mode="Markdown")
    
    # Сброс страницы на 0 при добавлении
    ctx = user_context.get(message.from_user.id)
    if ctx:
        ctx["offset"] = 0 
        class FakeMsg:
            def __init__(self, uid): self.from_user = types.User(id=uid, is_bot=False, first_name="U")
            async def answer(self, t, r=None): pass
        await show_task_list(FakeMsg(message.from_user.id), ctx["title"], ctx["type"], ctx["val"], is_edit=False)

# ================= КОЛБЭККИ =================
@dp.callback_query(lambda c: c.data == "refresh")
async def refresh_list(callback):
    ctx = user_context.get(callback.from_user.id)
    if ctx: 
        ctx["offset"] = 0 
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)
    await callback.answer()

# 🔥 ОБРАБОТЧИКИ ПАГИНАЦИИ (ИСПРАВЛЕНО)
@dp.callback_query(lambda c: c.data == "page_next")
async def page_next(callback: types.CallbackQuery):
    uid = callback.from_user.id
    ctx = user_context.get(uid)
    if ctx:
        # Увеличиваем offset
        current_offset = ctx.get("offset", 0)
        ctx["offset"] = current_offset + ITEMS_PER_PAGE
        # Принудительно обновляем экран
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "page_prev")
async def page_prev(callback: types.CallbackQuery):
    uid = callback.from_user.id
    ctx = user_context.get(uid)
    if ctx:
        # Уменьшаем offset, но не меньше 0
        current_offset = ctx.get("offset", 0)
        ctx["offset"] = max(0, current_offset - ITEMS_PER_PAGE)
        # Принудительно обновляем экран
        await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("task_"))
async def handle_task_click(callback: types.CallbackQuery):
    uid = callback.from_user.id
    tid = int(callback.data.split("_")[1])
    task = await task_service.get_task_by_id(tid)
    if task:
        await task_service.update_task(tid, is_done=not task.is_done)
    await callback.answer("")
    ctx = user_context.get(uid)
    if ctx:
        try:
            await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)
        except Exception as e:
            logger.warning(f"Edit failed: {e}")

@dp.callback_query(lambda c: c.data.startswith("done_"))
async def handle_done_click(callback: types.CallbackQuery):
    uid = callback.from_user.id
    tid = int(callback.data.split("_")[1])
    task = await task_service.get_task_by_id(tid)
    if task:
        await task_service.update_task(tid, is_done=False)
    await callback.answer("")
    ctx = user_context.get(uid)
    if ctx:
        try:
            await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True)
        except Exception as e:
            logger.warning(f"Edit failed: {e}")
