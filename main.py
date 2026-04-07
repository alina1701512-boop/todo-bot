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
from services import task_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
scheduler = AsyncIOScheduler()

# =============================================================================
# 📦 ФУНКЦИИ НАПОМИНАНИЙ (заглушки)
# =============================================================================
async def send_daily_summary():
    pass

async def check_15h_reminders():
    pass

def add_reminder_jobs(scheduler):
    scheduler.add_job(send_daily_summary, "cron", hour=9, minute=0, id="daily_summary", timezone=TZ)
    scheduler.add_job(check_15h_reminders, "interval", minutes=10, id="reminders_15h")
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
        logger.info("✅ Database initialized")
        
        # === ⚠️ РАСКОММЕНТИРОВАНО ДЛЯ СБРОСА БД (ТОЛЬКО ОДИН РАЗ!) ===
        # После первого успешного деплоя ЗАКОММЕНТИРУЙТЕ эти 3 строки обратно!
        from database import reset_database
        await reset_database()
        logger.info("🗑 Database reset - new columns added!")
        # ================================================================
        
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        raise
    
    try:
        webhook_url = f"{APP_HOST}/webhook/telegram"
        await bot.set_webhook(webhook_url, allowed_updates=dp.resolve_used_update_types())
        logger.info(f"🤖 Telegram webhook set: {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")

    # ⚙️ НАСТРОЙКА ПЛАНИРОВЩИКА
    scheduler.add_job(check_reminders, "interval", minutes=5, id="check_reminders", replace_existing=True)
    scheduler.add_job(task_service.cleanup_old_tasks, "cron", hour=0, minute=5, id="daily_cleanup", timezone=TZ, replace_existing=True)
    
    scheduler.start()
    logger.info("⏰ Scheduler started: reminders + daily cleanup")

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
    if not user_command: user_command = original_text

    response_text = "Я вас не поняла. Попробуйте: 'Добавь задачу ...' или 'Покажи список'."
    end_session = False

    try:
        if not user_command or "старт" in user_command or "привет" in user_command:
            response_text = "Привет! Я ваш планировщик."
        elif "добавь" in user_command:
            task_title = user_command.replace("добавь", "").replace("задачу", "").replace("задание", "").strip()
            if task_title:
                await task_service.create_task(task_title)
                response_text = f"Поняла, записала: '{task_title}'."
            else:
                response_text = "Что именно добавить?"
        elif "список" in user_command or "задачи" in user_command:
            tasks = await task_service.get_all_tasks()
            if not tasks: response_text = "Список пуст."
            else: response_text = "Вот список:\n" + "\n".join([f"{t.id}. {t.title}" for t in tasks[:5]])
        elif "удали" in user_command:
             response_text = "Удалите задачу через Телеграм-бота."
    except Exception as e:
        response_text = "Ой, что-то сломалось на сервере. Попробуйте позже."

    return JSONResponse({
        "version": "1.0",
        "session": data.get("session", {}),
        "response": {"text": response_text, "tts": response_text, "end_session": end_session}
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
        'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
        'scope': ' '.join(SCOPES), 'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true'
    }
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
    return {"authorization_url": auth_url}

@app.get("/auth/callback")
async def auth_callback(request: Request):
    import httpx
    from urllib.parse import urlencode
    code = request.query_params.get('code')
    if not code: return {"error": "No code provided"}
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = f"{os.environ.get('RENDER_EXTERNAL_URL')}/auth/callback"
    token_data = {'code': code, 'client_id': client_id, 'client_secret': client_secret, 'redirect_uri': redirect_uri, 'grant_type': 'authorization_code'}
    async with httpx.AsyncClient() as client:
        response = await client.post('https://oauth2.googleapis.com/token', data=urlencode(token_data), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if response.status_code != 200: return {"error": response.json()}
    tokens = response.json()
    refresh_token = tokens.get('refresh_token')
    if not refresh_token: return {"error": "No refresh token received"}
    return {"message": "Success! Copy this Refresh Token and add it to Render as GOOGLE_REFRESH_TOKEN", "refresh_token": refresh_token}
