import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Google Calendar Scopes
SCOPES = ['https://www.googleapis.com/auth/calendar']

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram.types import Update
from database import init_db
from config import TG_TOKEN, APP_HOST, TZ
from bot.dispatcher import dp, bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
scheduler = AsyncIOScheduler()

# =============================================================================
# 📦 ФУНКЦИИ НАПОМИНАНИЙ
# =============================================================================

async def send_daily_summary():
    """Ежедневно в 9:00 отправляет список задач на день"""
    try:
        from services import task_service
        
        tz = ZoneInfo(TZ)
        today_tasks = await task_service.get_tasks_for_date(datetime.now(tz).date())
        active = [t for t in today_tasks if not t.is_done]
        
        if not active:
            return
        
        text = "🌅 <b>Доброе утро! План на сегодня:</b>\n\n"
        for t in active[:10]:
            icon = "🔴" if t.priority=="red" else ("🟢" if t.priority=="green" else "🟡")
            time_str = t.due_at.strftime("%H:%M") if t.due_at else ""
            text += f"{icon} {t.title} {time_str}\n"
        
        # Получаем ID из переменной окружения
        user_id = os.environ.get('TELEGRAM_USER_ID')
        if user_id:
            await bot.send_message(chat_id=int(user_id), text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Daily summary error: {e}")

async def check_15h_reminders():
    """Проверяет задачи за 1.5 часа"""
    try:
        from services import task_service
        
        tz = ZoneInfo(TZ)
        now = datetime.now(tz)
        tasks = await task_service.get_all_tasks()
        
        for t in tasks:
            if t.due_at and not t.is_done and not t.is_reminded:
                diff = (t.due_at - now).total_seconds()
                if 0 < diff <= 5400:  # 1.5 часа = 5400 секунд
                    user_id = os.environ.get('TELEGRAM_USER_ID')
                    if user_id:
                        await bot.send_message(
                            chat_id=int(user_id),
                            text=f"⏰ <b>Напоминание:</b>\n{t.title}\n🕐 Осталось 1.5 часа",
                            parse_mode="HTML"
                        )
                    await task_service.update_task(t.id, is_reminded=True)
    except Exception as e:
        logger.error(f"Reminder check error: {e}")

def add_reminder_jobs(scheduler):
    """Добавляет джобы напоминаний"""
   # Напоминания временно отключены (нет колонок в БД)
# scheduler.add_job(send_daily_summary, "cron", hour=9, minute=0, id="daily_summary", timezone=TZ)
# scheduler.add_job(check_15h_reminders, "interval", minutes=10, id="reminders_15h")
    logger.info("✅ Reminder jobs added")

# =============================================================================
# 🚀 STARTUP
# =============================================================================

@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application...")
    logger.info(f"📍 APP_HOST: {APP_HOST}")
    
    try:
        await init_db()
        @app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application...")
    logger.info(f"📍 APP_HOST: {APP_HOST}")
    
    try:
        await init_db()
        logger.info("✅ Database initialized")
        
        # === ДОБАВЬТЕ ЭТИ 2 СТРОКИ ===
        from database import add_missing_columns
        await add_missing_columns()
        # =================================
        
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        raise
    
    try:
        webhook_url = f"{APP_HOST}/webhook/telegram"
        await bot.set_webhook(webhook_url, allowed_updates=dp.resolve_used_update_types())
        logger.info(f"🤖 Telegram webhook set: {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")

    # Добавляем джобы напоминаний (закомментировано)
    # add_reminder_jobs(scheduler)
    
    scheduler.add_job(check_reminders, "interval", minutes=5, replace_existing=True)
    scheduler.start()
    logger.info("⏰ Scheduler started")
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        raise
    
    try:
        webhook_url = f"{APP_HOST}/webhook/telegram"
        await bot.set_webhook(webhook_url, allowed_updates=dp.resolve_used_update_types())
        logger.info(f"🤖 Telegram webhook set: {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")

    # Добавляем джобы напоминаний
    add_reminder_jobs(scheduler)
    
    scheduler.add_job(check_reminders, "interval", minutes=5, replace_existing=True)
    scheduler.start()
    logger.info("⏰ Scheduler started")

async def check_reminders():
    pass

# =============================================================================
# 🔗 WEBHOOKS
# =============================================================================

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=500)
        
@app.post("/webhook/alice")
async def alice_webhook(request: Request):
    data = await request.json()
    
    user_command = data.get('request', {}).get('command', '')
    original_text = data.get('request', {}).get('original_utterance', '').lower()
    
    if not user_command:
        user_command = original_text

    response_text = "Я вас не поняла. Попробуйте: 'Добавь задачу ...' или 'Покажи список'."
    end_session = False

    try:
        if not user_command or "старт" in user_command or "привет" in user_command:
            response_text = "Привет! Я ваш планировщик. Скажите 'Добавь задачу', чтобы записать дело, или 'Покажи список', чтобы увидеть дела."

        elif "добавь" in user_command:
            task_title = user_command.replace("добавь", "").replace("задачу", "").replace("задание", "").strip()
            
            if task_title:
                from services import task_service
                await task_service.create_task(task_title)
                response_text = f"Поняла, записала: '{task_title}'."
            else:
                response_text = "Что именно добавить?"

        elif "список" in user_command or "задачи" in user_command or "дела" in user_command or "обнови" in user_command:
            from services import task_service
            tasks = await task_service.get_all_tasks()
            
            if not tasks:
                response_text = "Список пуст."
            else:
                task_list = []
                for t in tasks[:5]: 
                    task_list.append(f"{t.id}. {t.title}")
                response_text = "Вот список:\n" + "\n".join(task_list)
                
        elif "удали" in user_command or "сотри" in user_command:
             response_text = "Пока я умею только добавлять и показывать. Удалите задачу через Телеграм-бота."

    except Exception as e:
        response_text = "Ой, что-то сломалось на сервере. Попробуйте позже."

    return JSONResponse({
        "version": "1.0",
        "session": data.get("session", {}),
        "response": {
            "text": response_text,
            "tts": response_text,
            "end_session": end_session
        }
    })
    
@app.get("/")
async def root():
    return {"status": "Todo Bot is running", "version": "0.1.0"}

@app.get("/health")
async def health():
    return {"status": "running", "db": "ok"}

# =============================================================================
# 🔐 GOOGLE CALENDAR AUTH
# =============================================================================

@app.get("/auth/login")
async def auth_login():
    import secrets
    from urllib.parse import urlencode
    
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    redirect_uri = f"{os.environ.get('RENDER_EXTERNAL_URL')}/auth/callback"
    
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true'
    }
    
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
    return {"authorization_url": auth_url}

@app.get("/auth/callback")
async def auth_callback(request: Request):
    import httpx
    from urllib.parse import urlencode
    
    code = request.query_params.get('code')
    if not code:
        return {"error": "No code provided"}

    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = f"{os.environ.get('RENDER_EXTERNAL_URL')}/auth/callback"
    
    token_data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            'https://oauth2.googleapis.com/token',
            data=urlencode(token_data),
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
    
    if response.status_code != 200:
        return {"error": response.json()}
    
    tokens = response.json()
    refresh_token = tokens.get('refresh_token')
    
    if not refresh_token:
        return {"error": "No refresh token received"}
    
    return {
        "message": "Success! Copy this Refresh Token and add it to Render as GOOGLE_REFRESH_TOKEN",
        "refresh_token": refresh_token
    }
