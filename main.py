import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from bot.dispatcher import dp, bot
from config import APP_HOST
from database import init_db
from services.task_service import archive_old_completed_tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import TZ
import httpx

logger = logging.getLogger(__name__)

# Создаём планировщик
scheduler = AsyncIOScheduler(timezone=TZ)

async def archive_tasks_job():
    """Задача для планировщика: архивирует выполненные задачи"""
    try:
        count = await archive_old_completed_tasks()
        if count > 0:
            logger.info(f"🗄️ Архивация: {count} выполненных задач перемещено в архив")
        else:
            logger.debug("🗄️ Архивация: нет задач для архивации")
    except Exception as e:
        logger.error(f"❌ Ошибка архивации: {e}")

async def self_ping():
    """Само-пинг для предотвращения засыпания на Render"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{APP_HOST}/health", timeout=10.0)
            logger.debug(f"💓 Self-ping: {response.status_code}")
    except Exception as e:
        logger.debug(f"💤 Self-ping failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting application...")
    logger.info(f"📍 APP_HOST: {APP_HOST}")
    
    await init_db()
    logger.info("✅ Database initialized")
    
    # Устанавливаем вебхук
    webhook_url = f"{APP_HOST}/webhook/telegram"
    await bot.set_webhook(webhook_url)
    logger.info(f"🤖 Telegram webhook set to {webhook_url}")
    
    # 🔥 ПЛАНИРОВЩИК АРХИВАЦИИ (каждый день в 00:00)
    scheduler.add_job(
        archive_tasks_job,
        trigger=CronTrigger(hour=0, minute=0, timezone=TZ),
        id="archive_completed_tasks",
        replace_existing=True
    )
    
    # 🔥 САМО-ПИНГ каждые 10 минут (чтобы Render не усыплял)
    scheduler.add_job(
        self_ping,
        trigger=CronTrigger(minute="*/10"),  # каждые 10 минут
        id="self_ping",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("⏰ Планировщик запущен:")
    logger.info("   - Архивация выполненных задач: каждый день в 00:00 MSK")
    logger.info("   - Само-пинг: каждые 10 минут (анти-сон)")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    scheduler.shutdown()
    await bot.delete_webhook()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Todo Bot is running"}

@app.get("/health")
async def health():
    """Эндпоинт для проверки работоспособности и анти-сна"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        await dp.feed_webhook_update(bot, update_data)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return JSONResponse(content={"status": "error"}, status_code=500)

# Добавим datetime для health check
from datetime import datetime
