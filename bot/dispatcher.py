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

# Initialize logger
logger = logging.getLogger(__name__)

# Хранилище для выбранных задач
selected_tasks = {}

tz = ZoneInfo(TZ)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- КЛАВИАТУРЫ ---
def get_main_menu_keyboard():
    """Главное меню бота"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Все задачи"), KeyboardButton(text="📅 Сегодня")],
            [KeyboardButton(text="📅 Завтра"), KeyboardButton(text="➕ Добавить")],
            [KeyboardButton(text="📆 Неделя"), KeyboardButton(text="⚙️ Меню")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_extended_menu_keyboard():
    """Расширенное меню"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Выполненные"), KeyboardButton(text="🗑 Удалить")],
            [KeyboardButton(text="⏰ Перенести"), KeyboardButton(text="📋 Все задачи")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_cancel_keyboard():
    """Кнопка отмены"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )
    return keyboard

# --- КОМАНДЫ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я твой умный список дел.\n\n"
        "<b>Как пользоваться:</b>\n"
        "• Используй кнопки внизу для навигации\n"
        "• Просто напиши задачу с датой: <i>Купить молоко завтра в 18:00</i>\n"
        "• Нажимай на задачи в списке, чтобы выделить их\n"
        "• Выбирай действия: Выполнить, Удалить, Перенести",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer(
        "⚙️ <b>Дополнительное меню:</b>\n"
        "Выбери действие:",
        reply_markup=get_extended_menu_keyboard(),
        parse_mode="HTML"
    )

@dp.message(lambda message: message.text == "🔙 Назад")
async def menu_back(message: types.Message):
    await message.answer(
        "🔙 Возврат к главному меню",
        reply_markup=get_main_menu_keyboard()
    )

@dp.message(lambda message: message.text == "⚙️ Меню")
async def show_extended_menu(message: types.Message):
    await message.answer(
        "⚙️ <b>Дополнительные функции:</b>",
        reply_markup=get_extended_menu_keyboard(),
        parse_mode="HTML"
    )

@dp.message(lambda message: message.text == "📋 Все задачи")
async def show_all_tasks(message: types.Message):
    await show_tasks_interactive(message)

@dp.message(lambda message: message.text == "📅 Сегодня")
async def show_today_tasks(message: types.Message):
    tasks = await task_service.get_tasks_for_date(datetime.now(tz).date())
    await show_tasks_interactive(message, custom_tasks=tasks, title="Задачи на сегодня")

@dp.message(lambda message: message.text == "📅 Завтра")
async def show_tomorrow_tasks(message: types.Message):
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    tasks = await task_service.get_tasks_for_date(tomorrow)
    await show_tasks_interactive(message, custom_tasks=tasks, title="Задачи на завтра")

@dp.message(lambda message: message.text == "📆 Неделя")
async def show_week_tasks(message: types.Message):
    tasks = await task_service.get_all_tasks()
    today = datetime.now(tz).date()
    week_end = today + timedelta(days=7)
    week_tasks = [t for t in tasks if t.due_at and today <= t.due_at.date() <= week_end]
    await show_tasks_interactive(message, custom_tasks=week_tasks, title="Задачи на неделю")

@dp.message(lambda message: message.text == "✅ Выполненные")
async def show_completed_tasks(message: types.Message):
    tasks = await task_service.get_all_tasks()
    completed = [t for t in tasks if t.is_done]
    await show_tasks_interactive(message, custom_tasks=completed, title="Выполненные задачи")

@dp.message(lambda message: message.text == "➕ Добавить")
async def start_add_task(message: types.Message):
    await message.answer(
        "📝 <b>Напиши задачу:</b>\n"
        "Примеры:\n"
        "• Купить молоко\n"
        "• Встреча завтра в 15:00\n"
        "• Позвонить врачу сегодня в 18:00\n\n"
        "Или нажми ❌ Отмена",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@dp.message(lambda message: message.text == "❌ Отмена")
async def cancel_action(message: types.Message):
    await message.answer(
        "❌ Отменено",
        reply_markup=get_main_menu_keyboard()
    )

@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    await process_task_creation(message, message.text.replace("/add ", "").strip())

# Обработчик текста для добавления задачи (когда нажата кнопка "Добавить")
@dp.message(lambda message: message.text and message.text not in [
    "📋 Все задачи", "📅 Сегодня", "📅 Завтра", "➕ Добавить", 
    "📆 Неделя", "⚙️ Меню", "✅ Выполненные", "🗑 Удалить", 
    "⏰ Перенести", "🔙 Назад", "❌ Отмена"
])
async def handle_task_input(message: types.Message):
    text = message.text.strip()
    await process_task_creation(message, text)

async def process_task_creation(message: types.Message, text: str):
    if not text:
        await message.answer("❌ Напиши текст задачи")
        return

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
        await message.answer(
            f"✅ Задача добавлена!\n"
            f"📝 {task.title}\n"
            f"🕐 {task.format_due()}",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        await message.answer(
            f"✅ Задача добавлена!\n"
            f"📝 {task.title}\n"
            f"⚠️ Не удалось распознать дату",
            reply_markup=get_main_menu_keyboard()
        )

# --- ИНТЕРАКТИВНЫЙ СПИСОК ЗАДАЧ ---
async def show_tasks_interactive(message, custom_tasks=None, title="Все задачи"):
    user_id = message.from_user.id
    
    if custom_tasks is not None:
        tasks = custom_tasks
    else:
        tasks = await task_service.get_all_tasks()
    
    if user_id not in selected_tasks:
        selected_tasks[user_id] = set()

    if not tasks:
        await message.answer(
            f"📋 {title}: список пуст",
            reply_markup=get_main_menu_keyboard()
        )
        return

    text = f"📋 <b>{title}:</b>\n\n"
    keyboard_buttons = []
    
    for t in tasks[:15]:
        is_selected = t.id in selected_tasks[user_id]
        status_icon = "✅" if is_selected else "⬜️"
        
        if t.is_done:
            status_icon = "🏁"
        
        short_title = (t.title[:30] + "...") if len(t.title) > 30 else t.title
        btn_text = f"{status_icon} {short_title}"
        
        if t.is_done:
            keyboard_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"noop_{t.id}")])
        else:
            keyboard_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_{t.id}")])

    if selected_tasks[user_id]:
        count = len(selected_tasks[user_id])
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"✔️ Выполнить ({count})", callback_data="action_done"),
            InlineKeyboardButton(text=f"🗑 Удалить ({count})", callback_data="action_del"),
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"⏰ Перенести ({count})", callback_data="action_postpone")
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

# --- ОБРАБОТЧИКИ КНОПОК ---
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
        
    await callback.answer()
    await callback.message.delete()
    await show_tasks_interactive(callback.message)

@dp.callback_query(lambda c: c.data.startswith("action_"))
async def process_mass_action(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    action = callback.data.replace("action_", "")
    
    if user_id not in selected_tasks or not selected_tasks[user_id]:
        await callback.answer("Сначала выберите задачи!")
        return
    
    task_ids = list(selected_tasks[user_id])
    count = len(task_ids)
    
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
        else:
            msg = "❌ Неизвестное действие"
    except Exception as e:
        msg = f"❌ Ошибка: {e}"

    selected_tasks[user_id].clear()
    await callback.answer(msg)
    await callback.message.delete()
    await show_tasks_interactive(callback.message)

@dp.callback_query(lambda c: c.data.startswith("noop_"))
async def noop_callback(callback: types.CallbackQuery):
    await callback.answer("Эта задача уже выполнена", show_alert=False)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def parse_date(text):
    """
    Parse date from text with Russian support.
    Returns: tuple (datetime | None, error_message | None)
    """
    now = datetime.now(tz)
    
    if "сегодня" in text.lower():
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            # Validate time
            if not (0 <= hour <= 23):
                return None, f"⚠️ Час должен быть от 0 до 23. Вы указали: {hour}"
            if not (0 <= minute <= 59):
                return None, f"⚠️ Минуты должны быть от 0 до 59. Вы указали: {minute}"
            
            due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return due_at, None
    
    elif "завтра" in text.lower():
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            # Validate time
            if not (0 <= hour <= 23):
                return None, f"⚠️ Час должен быть от 0 до 23. Вы указали: {hour}"
            if not (0 <= minute <= 59):
                return None, f"⚠️ Минуты должны быть от 0 до 59. Вы указали: {minute}"
            
            tomorrow = now + timedelta(days=1)
            due_at = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return due_at, None
    
    # Try dateparser as fallback
    try:
        parsed = dateparser.parse(text, settings={
            "TIMEZONE": TZ, 
            "RETURN_AS_TIMEZONE_AWARE": True, 
            "PREFER_DATES_FROM": "future",
        })
        if parsed and (parsed - now) > timedelta(hours=1):
            return parsed, None
    except Exception as e:
        logger.error(f"Dateparser error: {e}")
    
    # No date found, but no error either
    return None, None
