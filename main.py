import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram.types import Update
from sqlalchemy import text

from database import init_db, async_session
from config import TG_TOKEN, APP_HOST, TZ
from bot.dispatcher import dp, bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services import task_service

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
scheduler = AsyncIOScheduler()
MSK_TZ = ZoneInfo("Europe/Moscow")

# 🔥 ФУНКЦИЯ МИГРАЦИИ (добавляет user_id, если нет)
async def migrate_add_user_id():
    """Добавляет поле user_id в таблицу tasks, если его нет."""
    try:
        async with async_session() as session:
            await session.execute(text("ALTER TABLE tasks ADD COLUMN user_id VARCHAR"))
            await session.commit()
            logger.info("✅ Migration: Added user_id column to tasks table")
    except Exception as e:
        # Если колонка уже есть — это нормально, просто логируем
        logger.info(f"ℹ️ Migration: user_id column likely already exists ({e})")
        async with async_session() as session:
            await session.rollback()

@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application...")
    logger.info(f"📍 APP_HOST: {APP_HOST}")
    
    # 1. Инициализация БД
    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        raise
    
    # 2. 🔥 Запуск миграции (добавит user_id для мультипользовательского режима)
    await migrate_add_user_id()
    
    # 3. Установка вебхука Telegram
    try:
        webhook_url = f"{APP_HOST}/webhook/telegram"
        await bot.set_webhook(webhook_url, allowed_updates=dp.resolve_used_update_types())
        logger.info(f"🤖 Telegram webhook set")
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")

    # ================= ПЛАНИРОВЩИК ЗАДАЧ =================
    
    # Задача 1: Ежедневная очистка в 00:00 МСК
    scheduler.add_job(
        task_service.cleanup_old_tasks, 
        "cron", 
        hour=0, 
        minute=0, 
        timezone=MSK_TZ, 
        id="daily_cleanup", 
        replace_existing=True
    )
    
    # Задача 2: 🔔 Напоминания каждые 15 минут
    # Важно: передаём экземпляр bot через args, чтобы функция могла отправлять сообщения
    scheduler.add_job(
        task_service.send_reminders, 
        "interval", 
        minutes=15, 
        args=[bot],  
        id="send_reminders", 
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("⏰ Scheduler started: Cleanup at 00:00 MSK, Reminders every 15 min")

@app.on_event("shutdown")
async def shutdown():
    """Корректно останавливает планировщик при выключении сервера."""
    logger.info("🛑 Shutting down scheduler...")
    scheduler.shutdown()

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=500)

@app.get("/")
async def root():
    return {"status": "Todo Bot is running"}

@app.get("/health")
async def health():
    return {"status": "running", "db": "ok"}
