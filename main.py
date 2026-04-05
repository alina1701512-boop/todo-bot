import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram.types import Update
from database import init_db
from config import TG_TOKEN, APP_HOST
from bot.dispatcher import dp, bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging

logging.basicConfig(level=logging.INFO)
app = FastAPI()
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup():
    await init_db()
    webhook_url = f"{APP_HOST}/webhook/telegram"
    await bot.set_webhook(webhook_url, allowed_updates=dp.resolve_used_update_types())
    logging.info(f"🤖 TG webhook: {webhook_url}")

    scheduler.add_job(check_reminders, "interval", minutes=5, replace_existing=True)
    scheduler.start()
    logging.info("⏰ Scheduler запущен")

async def check_reminders():
    pass  # Логика напоминаний будет добавлена позже

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return JSONResponse({"status": "ok"})

@app.post("/webhook/alice")
async def alice_webhook(request: Request):
    return JSONResponse({
        "version": "1.0", "session": {}, 
        "response": {"text": "Синхронизация с Алисой в разработке 🛠️", "end_session": False}
    })

@app.get("/health")
async def health():
    return {"status": "running", "db": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
