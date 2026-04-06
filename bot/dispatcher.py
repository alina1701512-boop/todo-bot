from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import dateparser
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import TG_TOKEN, TZ
from services import task_service
import logging

# Initialize logger for debugging
logger = logging.getLogger(__name__)

tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Я твой список дел.\n\n📝 Команды:\n/add <задача> [дата/время]\n/list - показать задачи\n/help - помощь")

@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    text = message.text.replace("/add ", "").strip()
    if not text or text == "/add":
        await message.answer("📝 Напиши задачу. Пример: `Купить молоко завтра в 18:00`")
        return

    parsed = dateparser.parse(text, settings={"TIMEZONE": TZ, "RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DATES_FROM": "future"})
    due_at = parsed if parsed and (parsed - datetime.now(tz)) > timedelta(hours=1) else None

    task = await task_service.create_task(text, due_at)

    # Google Calendar Integration
    try:
        from calendar_service import create_google_event
        event_link = await create_google_event(text, due_at.isoformat() if due_at else None)
        if event_link:
            logger.info(f"Google Calendar event created successfully: {event_link}")
    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}")

    await message.answer(f"✅ Задача добавлена!\n📝 {task.title}\n{task.format_due()}")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    tasks = await task_service.get_all_tasks()
    if not tasks:
        await message.answer("📋 Список дел пуст. Добавь первую задачу командой /add")
        return

    text = "📋 **Мои задачи:**\n\n"
    for t in tasks:
        status = "✅" if t.is_done else "⬜️"
        text += f"{status} `{t.id}`. {t.title}\n   {t.format_due()}\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✔️ {t.id}", callback_data=f"done_{t.id}"),
         InlineKeyboardButton(text=f"🗑 {t.id}", callback_data=f"del_{t.id}")]
        for t in tasks[:5]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data.startswith("done_") or c.data.startswith("del_"))
async def process_callback(callback: types.CallbackQuery):
    action, task_id = callback.data.split("_")
    task_id = int(task_id)

    if action == "done":
        await task_service.update_task(task_id, is_done=True)
        await callback.answer("✅ Отмечено")
    elif action == "del":
        await task_service.delete_task(task_id)
        await callback.answer("🗑 Удалено")

    await cmd_list(callback.message)
  # Handle any text message as a task (without /add command)
@dp.message(lambda message: message.text and not message.text.startswith('/'))
async def handle_text_as_task(message: types.Message):
    text = message.text.strip()
    
    # Manual parsing for Russian dates
    due_at = None
    now = datetime.now(tz)
    
    # Check for "сегодня" (today)
    if "сегодня" in text.lower():
        # Extract time like "14:00" or "18:00"
        import re
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            logger.info(f"Parsed 'сегодня': {due_at}")
    
    # Check for "завтра" (tomorrow)
    elif "завтра" in text.lower():
        import re
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            tomorrow = now + timedelta(days=1)
            due_at = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
            logger.info(f"Parsed 'завтра': {due_at}")
    
    # Try dateparser as fallback
    if not due_at:
        parsed = dateparser.parse(text, settings={
            "TIMEZONE": TZ, 
            "RETURN_AS_TIMEZONE_AWARE": True, 
            "PREFER_DATES_FROM": "future",
        })
        if parsed and (parsed - now) > timedelta(hours=1):
            due_at = parsed
            logger.info(f"Parsed by dateparser: {due_at}")
    
    # Create task
    task = await task_service.create_task(text, due_at)
    
    # Add to Google Calendar
    try:
        from calendar_service import create_google_event
        event_link = await create_google_event(text, due_at.isoformat() if due_at else None)
        if event_link:
            logger.info(f"Google Calendar event created: {event_link}")
    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}")
    
    # Send response
    if due_at:
        await message.answer(f"✅ Задача добавлена!\n📝 {task.title}\n {task.format_due()}")
    else:
        await message.answer(f"✅ Задача добавлена!\n📝 {task.title}\n⚠️ Не удалось распознать дату, задача без срока")
