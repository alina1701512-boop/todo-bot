import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram.types import Update
from sqlalchemy import text

# 🔥 Добавили новую функцию миграции в импорт
from database import init_db, async_session, migrate_add_user_id, migrate_create_google_auth_table
from config import TG_TOKEN, APP_HOST, TZ
from bot.dispatcher import dp, bot
from services import task_service

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ================= НАПОМИНАНИЯ ВРЕМЕННО ОТКЛЮЧЕНЫ =================
# Планировщик пока не запускаем
# scheduler = AsyncIOScheduler()
# MSK_TZ = ZoneInfo("Europe/Moscow")

# 🔥 ФУНКЦИЯ МИГРАЦИИ (добавляет user_id, если нет)
async def migrate_add_user_id():
    """Добавляет поле user_id в таблицу tasks, если его нет."""
    try:
        async with async_session() as session:
            await session.execute(text("ALTER TABLE tasks ADD COLUMN user_id VARCHAR"))
            await session.commit()
            logger.info("✅ Migration: Added user_id column to tasks table")
    except Exception as e:
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
    
    # 2. 🔥 Миграции
    await migrate_add_user_id()
    await migrate_create_google_auth_table()
    
    # 3. Установка вебхука Telegram
    try:
        webhook_url = f"{APP_HOST}/webhook/telegram"
        await bot.set_webhook(webhook_url, allowed_updates=dp.resolve_used_update_types())
        logger.info(f"🤖 Telegram webhook set to {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")

    # ================= ПЛАНИРОВЩИК ЗАДАЧ (ВРЕМЕННО ОТКЛЮЧЕН) =================
    # Напоминания отключены для отладки
    logger.info("⏰ Reminders are DISABLED (temporarily)")

@app.on_event("shutdown")
async def shutdown():
    """Корректно останавливает сервер."""
    logger.info("🛑 Shutting down...")
    await bot.session.close()

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

# ================= 📅 GOOGLE OAUTH CALLBACK =================
@app.get("/callback")
async def google_oauth_callback(request: Request):
    """Принимает код от Google после авторизации"""
    from urllib.parse import parse_qs, urlparse
    
    query_params = parse_qs(urlparse(str(request.url)).query)
    code = query_params.get("code", [None])[0]
    error = query_params.get("error", [None])[0]
    
    if error:
        return f"""
        <html>
            <body style="font-family: Arial; padding: 40px; text-align: center;">
                <h1 style="color: #d32f2f;">❌ Ошибка авторизации</h1>
                <p>Error: {error}</p>
                <p>Попробуй ещё раз: <code>/connect_google</code></p>
            </body>
        </html>
        """
    
    if code:
        return f"""
        <html>
            <body style="font-family: Arial; padding: 40px; text-align: center; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px;">
                    <h1 style="color: #388e3c;">✅ Авторизация успешна!</h1>
                    <p style="color: #666; margin: 20px 0;">Скопируй этот код и отправь боту в Telegram:</p>
                    <div style="background: #e3f2fd; padding: 15px; border-radius: 4px; margin: 20px 0; font-family: monospace; font-size: 14px; word-break: break-all;">
                        /connect_google {code}
                    </div>
                    <p style="color: #999; font-size: 14px;">Или просто скопируй код:</p>
                    <div style="background: #f5f5f5; padding: 15px; border-radius: 4px; margin: 20px 0; font-family: monospace; font-size: 12px; word-break: break-all;">
                        {code}
                    </div>
                </div>
            </body>
        </html>
        """
    
    return "<html><body><h1>No code received</h1></body></html>"
