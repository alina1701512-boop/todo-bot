import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
MSK_TZ = ZoneInfo("Europe/Moscow")

# =============================================================================
# 🚀 STARTUP
# =============================================================================
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application...")
    logger.info(f"📍 APP_HOST: {APP_HOST}")
    
    try:
        await init_db()  # ✅ Здесь добавятся колонки
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        raise
    
    try:
        webhook_url = f"{APP_HOST}/webhook/telegram"
        await bot.set_webhook(webhook_url, allowed_updates=dp.resolve_used_update_types())
        logger.info(f"🤖 Telegram webhook set")
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")

    # ⏰ ПЛАНИРОВЩИК
    scheduler.add_job(
        task_service.cleanup_old_tasks, 
        "cron", hour=0, minute=0, 
        timezone=MSK_TZ, 
        id="daily_cleanup", 
        replace_existing=True
    )
    
    async def check_reminders(): pass
    scheduler.add_job(check_reminders, "interval", minutes=5, id="check_reminders", replace_existing=True)
    
    scheduler.start()
    logger.info("⏰ Scheduler started: Cleanup at 00:00 MSK")

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
    return JSONResponse({"status": "ok"})

@app.get("/")
async def root():
    return {"status": "Todo Bot is running"}

@app.get("/health")
async def health():
    return {"status": "running", "db": "ok"}

@app.get("/auth/login")
async def auth_login(): return {"status": "auth"}
@app.get("/auth/callback")
async def auth_callback(request: Request): return {"status": "callback"}
