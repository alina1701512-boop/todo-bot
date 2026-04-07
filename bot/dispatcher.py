from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramBadRequest
import re
import logging
import httpx  # ← Добавить сюда, рядом с другими импортами
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

ITEMS_PER_PAGE = 8

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

# ================= ОТРИСОВКА СПИСКА =================
async def show_task_list(message, title, filter_type, filter_val, is_edit=False, page_offset=0):
    user_id = message.from_user.id
    uid_str = str(user_id)  # 🔥 Приводим к строке для БД
    
    # Загрузка задач С ФИЛЬТРОМ ПО user_id
    if filter_type == "all": 
        all_tasks = await task_service.get_all_tasks(user_id=uid_str)
    elif filter_type == "priority":
        all_t = await task_service.get_all_tasks(user_id=uid_str)
        all_tasks = [t for t in all_t if t.priority == filter_val]
    elif filter_type == "period":
        now = datetime.now(tz)
        if filter_val == "Сегодня": 
            all_tasks = await task_service.get_tasks_for_date(now.date(), user_id=uid_str)
        elif filter_val == "Завтра": 
            all_tasks = await task_service.get_tasks_for_date(now.date() + timedelta(days=1), user_id=uid_str)
        elif filter_val == "📆 Неделя": 
            all_tasks = await task_service.get_tasks_for_week(now.date(), user_id=uid_str)
        elif filter_val == "🗓️ Месяц":
            all_t = await task_service.get_all_tasks(user_id=uid_str)
            end = now.date() + timedelta(days=30)
            all_tasks = [t for t in all_t if t.due_at and now.date() <= t.due_at.date() <= end]
        else: all_tasks = []
    else: all_tasks = []

    total = len(all_tasks)
    if page_offset >= total and total > 0: page_offset = ((total - 1) // ITEMS_PER_PAGE) * ITEMS_PER_PAGE
    if page_offset < 0: page_offset = 0
    
    user_context.setdefault(user_id, {})
    user_context[user_id].update({"title": title, "type": filter_type, "val": filter_val, "offset": page_offset})

    if total == 0:
        text = "📋 Задач нет"
        kb = [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")]
        try:
            if is_edit: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
            else: await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
        except: pass
        return

    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    current_page = (page_offset // ITEMS_PER_PAGE) + 1
    page_tasks = all_tasks[page_offset : page_offset + ITEMS_PER_PAGE]

    text = f"📋 {title} (всего {total})\n📄 Страница {current_page} из {total_pages}\n\n"
    kb = []
    for t in page_tasks:
        icon = "✅" if t.is_done else {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(t.priority, "⚪️")
        short = (t.title[:30] + "...") if len(t.title) > 30 else t.title
        due = t.due_at.strftime("%d.%m %H:%M") if t.due_at else "Без срока"
        cb = f"done_{t.id}" if t.is_done else f"task_{t.id}"
        kb.append([InlineKeyboardButton(text=f"{icon} {short}\n🕐 {due}", callback_data=cb)])

    nav = []
    if page_offset > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data="page_prev"))
    if page_offset + ITEMS_PER_PAGE < total: nav.append(InlineKeyboardButton(text="➡️", callback_data="page_next"))
    if nav: kb.append(nav)

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    try:
        if is_edit: await message.edit_text(text, reply_markup=markup)
        else: await message.answer(text, reply_markup=markup)
    except TelegramBadRequest as e:
        logger.error(f"❌ Edit failed: {e}")

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
    "🔴 Срочные", "🟡 Средние", "🟢 Лайтовые", "Сегодня", "Завтра", "📆 Неделя", "🗓️ Месяц"
])
async def handle_text(message):
    uid = message.from_user.id
    uid_str = str(uid)  # 🔥 Для БД
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

    # 🔥 Создаём задачу с user_id
    task = await task_service.create_task(title, due_at, priority, user_id=uid_str)
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(priority, "⚪️")
    due_str = due_at.strftime("%d.%m в %H:%M") if due_at else "Без срока"
    
    await message.answer(f"{emoji} Задача добавлена!\n📝 {task.title}\n🕐 {due_str}")
    
    ctx = user_context.get(uid)
    if ctx:
        await show_task_list(message, ctx["title"], ctx["type"], ctx["val"], is_edit=False, page_offset=0)

# ================= 📊 СТАТИСТИКА /stats =================
@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    uid_str = str(message.from_user.id)
    await message.answer("📊 **Готовлю статистику...**")
    
    stats = await task_service.get_task_stats(user_id=uid_str)
    completion = (stats['done'] / stats['total'] * 100) if stats['total'] > 0 else 0
    
    text = (f"📊 **Твоя статистика:**\n\n"
            f"📦 **Всего задач:** {stats['total']}\n"
            f"✅ **Выполнено:** {stats['done']}\n"
            f"⏳ **В работе:** {stats['pending']}\n"
            f"🔴 **Просрочено:** {stats['overdue']}\n\n"
            f"📈 **Прогресс:** {completion:.1f}%\n\n"
            f"**По приоритетам:**\n"
            f"🔴 Срочные: {stats['red']}\n"
            f"🟡 Средние: {stats['yellow']}\n"
            f"🟢 Лайтовые: {stats['green']}\n")
    
    await message.answer(text, parse_mode="Markdown")

# ================= 🎤 ОБРАБОТЧИК ГОЛОСОВЫХ СООБЩЕНИЙ =================
@dp.message(lambda m: m.voice)
async def handle_voice(message: types.Message):
    """Принимает голосовые сообщения, распознаёт и создаёт задачу."""
    uid = message.from_user.id
    await message.answer("🎧 Слушаю...")
    
    try:
        # 🔥 ПРАВИЛЬНЫЙ СПОСОБ: скачиваем файл через message.bot
        file = await message.bot.get_file(message.voice.file_id)
        file_path = file.file_path
        
        # Скачиваем контент через HTTPX
        async with httpx.AsyncClient() as client:
            download_url = f"https://api.telegram.org/file/bot{TG_TOKEN}/{file_path}"
            response = await client.get(download_url, timeout=30.0)
            audio_bytes = response.content
        
        # Отправляем в Whisper
        from services.ai_parser import transcribe_voice
        text = await transcribe_voice(audio_bytes)
        
        if text:
            # Создаём фейковое сообщение и передаём в handle_text
            fake_message = types.Message(
                message_id=message.message_id,
                from_user=message.from_user,
                date=message.date,
                chat=message.chat,
                text=text
            )
            await handle_text(fake_message)
        else:
            await message.answer("❌ Не удалось распознать речь. Попробуйте ещё раз или напишите текстом.")
            
    except Exception as e:
        logger.error(f"❌ Voice handler error: {e}")
        await message.answer("❌ Ошибка при обработке голоса. Попробуйте позже.")
        
# ================= КОЛБЭККИ =================
@dp.callback_query(lambda c: c.data == "refresh")
async def refresh_list(callback):
    ctx = user_context.get(callback.from_user.id)
    if ctx:
        ctx["ai_mode"] = False
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
    uid = callback.from_user.id
    tid = int(callback.data.split("_")[1])
    task = await task_service.get_task_by_id(tid)
    if task: await task_service.update_task(tid, is_done=not task.is_done)
    await callback.answer("")
    ctx = user_context.get(uid)
    if ctx:
        try:
            await show_task_list(callback.message, ctx["title"], ctx["type"], ctx["val"], is_edit=True, page_offset=ctx.get("offset", 0))
        except Exception as e:
            logger.error(f"❌ Edit failed: {e}")
