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

# Хранилище для выбранных задач: {user_id: {task_id, task_id...}}
selected_tasks = {}

tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я твой умный список дел.\n\n"
        "<b>📝 Как управлять:</b>\n"
        "1. Просто напиши задачу с датой: <i>Купить молоко завтра в 18:00</i>\n"
        "2. Нажми на /list, чтобы увидеть список.\n"
        "3. Нажимай на задачи, чтобы выделить их (✅).\n"
        "4. Внизу нажми 'Выполнить' или 'Удалить'.",
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
    await show_tasks_interactive(message)

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

# --- ГЛАВНАЯ ФУНКЦИЯ ОТОБРАЖЕНИЯ СПИСКА ---
async def show_tasks_interactive(message_or_callback, is_callback=False):
    # Определяем, что пришло (сообщение или колбэк)
    if is_callback:
        user_id = message_or_callback.from_user.id
        target_message = message_or_callback.message
    else:
        user_id = message_or_callback.from_user.id
        target_message = message_or_callback

    tasks = await task_service.get_all_tasks()
    
    # Инициализируем список выбранных для этого юзера
    if user_id not in selected_tasks:
        selected_tasks[user_id] = set()

    if not tasks:
        text = "📋 Список пуст. Добавь задачу!"
        keyboard = None
    else:
        text = "📋 <b>Нажми на задачи, чтобы выделить их:</b>\n\n"
        keyboard_buttons = []
        
        # Отображаем последние 15 задач, чтобы не превысить лимиты телеграм
        for t in tasks[:15]:
            is_selected = t.id in selected_tasks[user_id]
            status_icon = "✅" if is_selected else "⬜️"
            
            # Обрезаем текст, если слишком длинный, чтобы кнопка влезла
            short_title = (t.title[:25] + "...") if len(t.title) > 25 else t.title
            btn_text = f"{status_icon} {short_title}"
            
            # Если задача выполнена, делаем её неактивной
            if t.is_done:
                btn_text = f"🏁 {short_title}"
                keyboard_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"noop_{t.id}")])
            else:
                keyboard_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_{t.id}")])

        # Добавляем кнопки действий внизу
        if selected_tasks[user_id]:
            count = len(selected_tasks[user_id])
            action_row = [
                InlineKeyboardButton(text=f"✔️ Выполнить ({count})", callback_data="action_done"),
                InlineKeyboardButton(text=f"🗑 Удалить ({count})", callback_data="action_del"),
                InlineKeyboardButton(text=f"⏰ Перенести ({count})", callback_data="action_postpone")
            ]
            keyboard_buttons.append(action_row)
        else:
             # Если ничего не выбрано, показываем неактивные кнопки действий или скрываем их
             # Для экономии места скроем, пока не выбрано
             pass

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    # Если это колбэк (нажатие кнопки), мы редактируем сообщение
    if is_callback:
        try:
            await target_message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass # Игнорируем ошибку если текст не изменился
    else:
        await target_message.answer(text, reply_markup=keyboard, parse_mode="HTML")

# --- ОБРАБОТЧИК ВЫБОРА ЗАДАЧИ (ГАЛОЧКА) ---
@dp.callback_query(lambda c: c.data.startswith("toggle_"))
async def process_toggle(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    task_id = int(callback.data.replace("toggle_", ""))
    
    if user_id not in selected_tasks:
        selected_tasks[user_id] = set()
        
    if task_id in selected_tasks[user_id]:
        selected_tasks[user_id].remove(task_id)
    else:
        selected_tasks[user_id].add(task_id)
        
    await callback.answer("Выбор изменен")
    await show_tasks_interactive(callback, is_callback=True)

# --- ОБРАБОТЧИК МАССОВЫХ ДЕЙСТВИЙ ---
@dp.callback_query(lambda c: c.data.startswith("action_"))
async def process_mass_action(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    action = callback.data.replace("action_", "")
    
    if user_id not in selected_tasks or not selected_tasks[user_id]:
        await callback.answer("Сначала выберите задачи!")
        return
    
    task_ids = list(selected_tasks[user_id])
    count = len(task_ids)
    
    msg = ""
    
    try:
        if action == "done":
            for tid in task_ids:
                await task_service.update_task(tid, is_done=True)
            msg = f"✅ Выполнено задач: {count}"
            
        elif action == "del":
            for tid in task_ids:
                await task_service.delete_task(tid)
            msg = f"🗑 Удалено задач: {count}"
            
        elif action == "postpone":
            for tid in task_ids:
                task = await task_service.get_task_by_id(tid)
                if task and task.due_at:
                    new_time = task.due_at + timedelta(days=1)
                    await task_service.update_task(tid, due_at=new_time)
                elif task:
                    new_time = datetime.now(tz) + timedelta(days=1)
                    await task_service.update_task(tid, due_at=new_time)
            msg = f"⏰ Перенесено задач: {count}"
    except Exception as e:
        msg = f"Ошибка: {e}"

    # Очищаем выбор после действия
    selected_tasks[user_id].clear()
    
    await callback.answer(msg)
    await show_tasks_interactive(callback, is_callback=True)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def parse_date(text):
    """Parse date from text with Russian support"""
    due_at = None
    now = datetime.now(tz)
    
    # Check for "сегодня" (today)
    if "сегодня" in text.lower():
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # Check for "завтра" (tomorrow)
    elif "завтра" in text.lower():
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            tomorrow = now + timedelta(days=1)
            due_at = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # Try dateparser as fallback
    if not due_at:
        parsed = dateparser.parse(text, settings={
            "TIMEZONE": TZ, 
            "RETURN_AS_TIMEZONE_AWARE": True, 
            "PREFER_DATES_FROM": "future",
        })
        if parsed and (parsed - now) > timedelta(hours=1):
            due_at = parsed
    
    return due_at
