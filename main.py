import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram.types import Update
from database import init_db
from config import TG_TOKEN, APP_HOST
from bot.dispatcher import dp, bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application...")
    logger.info(f"📍 APP_HOST: {APP_HOST}")
    
    try:
        await init_db()
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
    
    scheduler.add_job(check_reminders, "interval", minutes=5, replace_existing=True)
    scheduler.start()
    logger.info("⏰ Scheduler started")

async def check_reminders():
    pass

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
    
    # Получаем, что сказал пользователь
    user_command = data.get('request', {}).get('original_utterance', '').lower()
    
    response_text = "Я пока не поняла. Попробуй 'Добавь задачу [текст]' или 'Покажи список'."
    end_session = False

    try:
        # 1. КОМАНДА "ДОБАВЬ ЗАДАЧУ"
        if user_command.startswith("добавь"):
            # Убираем слово "добавь" и пробелы
            task_title = user_command.replace("добавь", "").strip()
            
            # Если есть слово "задачу", тоже убираем его для красоты
            task_title = task_title.replace("задачу", "").strip()
            
            if task_title:
                await task_service.create_task(task_title)
                response_text = f"Задача '{task_title}' добавлена!"
            else:
                response_text = "Какую задачу добавить?"

        # 2. КОМАНДА "ПОКАЖИ СПИСОК" (или "обнови список")
        elif "список" in user_command or "задачи" in user_command or "обнови" in user_command:
            tasks = await task_service.get_all_tasks()
            
            if not tasks:
                response_text = "Список дел пуст."
            else:
                # Собираем список текстом
                task_list = []
                for t in tasks[:5]: # Показываем только последние 5, чтобы Алиса не тараторила
                    status = "выполнено" if t.is_done else "в процессе"
                    task_list.append(f"{t.id}. {t.title}")
                
                response_text = "Вот твои текущие дела:\n" + "\n".join(task_list)
                
    except Exception as e:
        response_text = "Произошла ошибка при подключении к базе данных."

    # Формируем ответ для Алисы (JSON)
    return JSONResponse({
        "version": "1.0",
        "session": data.get("session", {}),
        "response": {
            "text": response_text,
            "tts": response_text,  # Текст для озвучки
            "end_session": end_session
        }
    })

@app.get("/")
async def root():
    return {"status": "Todo Bot is running", "version": "0.1.0"}

@app.get("/health")
async def health():
    return {"status": "running", "db": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"🌍 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
