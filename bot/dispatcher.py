from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import dateparser
import re
import logging
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from config import TG_TOKEN, TZ
from services import task_service

# Initialize logger
logger = logging.getLogger(__name__)

tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я твой умный список дел.\n\n"
        "<b>📝 Команды:</b>\n"
        "/add <задача> [дата/время] - добавить задачу\n"
        "/list - все задачи\n"
        "/today - задачи на сегодня\n"
        "/tomorrow - задачи на завтра\n"
        "/week - задачи на неделю\n"
        "/done <id> - выполнить задачу\n"
        "/delete <id> - удалить задачу\n"
        "/help - помощь\n\n"
        "💡 Или просто напиши текст с датой: 'Купить молоко завтра в 18:00'",
        parse_mode="HTML"
    )

@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    text = message.text.replace("/add ", "").strip()
    if not text or text == "/add":
        await message.answer("📝 Напиши задачу. Пример: `Купить молоко завтра в 18:00`")
        return

    due_at = parse_date(text)
    task = await task_service.create_task(text, due_at)

    # Google Calendar Integration
    try:
        from calendar_service import create_google_event
        event_link = await create_google_event(text, due_at.isoformat() if due_at else None)
        if event_link:
            logger.info(f"Google Calendar event created: {event_link}")
    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}")

    if due_at:
        await message.answer(f"✅ Задача добавлена!\n📝 {task.title}\n🕐 {task.format_due()}")
    else:
        await message.answer(f"✅ Задача добавлена!\n📝 {task.title}\n⚠️ Не удалось распознать дату")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    tasks = await task_service.get_all_tasks()
    await show_tasks(message, tasks, "Все задачи")

@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    tasks = await task_service.get_tasks_for_date(datetime.now(tz).date())
    await show_tasks(message, tasks, "Задачи на сегодня")

@dp.message(Command("tomorrow"))
async def cmd_tomorrow(message: types.Message):
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    tasks = await task_service.get_tasks_for_date(tomorrow)
    await show_tasks(message, tasks, "Задачи на завтра")

@dp.message(Command("week"))
async def cmd_week(message: types.Message):
    tasks = await task_service.get_all_tasks()
    today = datetime.now(tz).date()
    week_end = today + timedelta(days=7)
    
    week_tasks = [t for t in tasks if t.due_at and today <= t.due_at.date() <= week_end]
    await show_tasks(message, week_tasks, "Задачи на неделю")

async def show_tasks(message: types.Message, tasks, title):
    if not tasks:
        await message.answer(f"📋 {title}: список пуст")
        return

    text = f"📋 <b>{title}:</b>\n\n"
    for t in tasks[:10]:
        status = "✅" if t.is_done else "⬜️"
        safe_title = t.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text += f"{status} <code>{t.id}</code>. {safe_title}\n"
        if t.due_at:
            text += f"   🕐 {t.format_due()}\n"
        text += "\n"

    keyboard_buttons = []
    for t in tasks[:5]:
        if not t.is_done:
            keyboard_buttons.append([
                InlineKeyboardButton(text=f"✔️ {t.id}", callback_data=f"done_{t.id}"),
                InlineKeyboardButton(text=f"🗑 {t.id}", callback_data=f"del_{t.id}"),
                InlineKeyboardButton(text=f"⏰ {t.id}", callback_data=f"postpone_{t.id}")
            ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons) if keyboard_buttons else None
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("done"))
async def cmd_done(message: types.Message):
    try:
        task_id = int(message.text.replace("/done", "").strip())
        await task_service.update_task(task_id, is_done=True)
        await message.answer(f"✅ Задача #{task_id} выполнена!")
    except (ValueError, IndexError):
        await message.answer("❌ Укажите ID задачи. Пример: `/done 5`")

@dp.message(Command("delete"))
async def cmd_delete(message: types.Message):
    try:
        task_id = int(message.text.replace("/delete", "").strip())
        await task_service.delete_task(task_id)
        await message.answer(f"🗑 Задача #{task_id} удалена!")
    except (ValueError, IndexError):
        await message.answer("❌ Укажите ID задачи. Пример: `/delete 5`")

@dp.message(Command("postpone"))
async def cmd_postpone(message: types.Message):
    args = message.text.replace("/postpone", "").strip().split()
    if len(args) < 2:
        await message.answer("❌ Пример: `/postpone 5 завтра 15:00`")
        return
    
    try:
        task_id = int(args[0])
        date_text = " ".join(args[1:])
        due_at = parse_date(date_text)
        
        if not due_at:
            await message.answer("❌ Не удалось распознать дату")
            return
        
        await task_service.update_task(task_id, due_at=due_at)
        await message.answer(f"⏰ Задача #{task_id} перенесена")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(lambda c: c.data.startswith("done_") or c.data.startswith("del_") or c.data.startswith("postpone_"))
async def process_callback(callback: types.CallbackQuery):
    action, task_id = callback.data.split("_")
    task_id = int(task_id)

    if action == "done":
        await task_service.update_task(task_id, is_done=True)
        await callback.answer("✅ Отмечено")
    elif action == "del":
        await task_service.delete_task(task_id)
        await callback.answer("🗑 Удалено")
    elif action == "postpone":
        task = await task_service.get_task_by_id(task_id)
        if task and task.due_at:
            new_time = task.due_at + timedelta(days=1)
            await task_service.update_task(task_id, due_at=new_time)
            await callback.answer(f"⏰ Перенесено")
        else:
            await callback.answer("⏰ Перенесено на завтра")

    tasks = await task_service.get_all_tasks()
    await show_tasks(callback.message, tasks, "Все задачи")

@dp.message(lambda message: message.text and not message.text.startswith('/'))
async def handle_text_as_task(message: types.Message):
    text = message.text.strip()
    due_at = parse_date(text)
    
    task = await task_service.create_task(text, due_at)
    
    try:
        from calendar_service import create_google_event
        event_link = await create_google_event(text, due_at.isoformat() if due_at else None)
        if event_link:
            logger.info(f"Google Calendar event created: {event_link}")
    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}")
    
    if due_at:
        await message.answer(f"✅ Задача добавлена!\n📝 {task.title}\n🕐 {task.format_due()}")
    else:
        await message.answer(f"✅ Задача добавлена!\n📝 {task.title}\n⚠️ Не удалось распознать дату")

def parse_date(text):
    """Parse date from text with Russian support"""
    due_at = None
    now = datetime.now(tz)
    
    if "сегодня" in text.lower():
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    elif "завтра" in text.lower():
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            tomorrow = now + timedelta(days=1)
            due_at = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    if not due_at:
        parsed = dateparser.parse(text, settings={
            "TIMEZONE": TZ, 
            "RETURN_AS_TIMEZONE_AWARE": True, 
            "PREFER_DATES_FROM": "future",
        })
        if parsed and (parsed - now) > timedelta(hours=1):
            due_at = parsed
    
    return due_at
