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
    # Parse incoming JSON data from Yandex Dialogs
    data = await request.json()
    
    # Extract user input
    user_command = data.get('request', {}).get('command', '')
    original_text = data.get('request', {}).get('original_utterance', '').lower()
    
    # Fallback to original utterance if command field is empty
    if not user_command:
        user_command = original_text

    # Default response if no conditions match
    response_text = "Я вас не поняла. Попробуйте: 'Добавь задачу ...' или 'Покажи список'."
    end_session = False

    try:
        # 1. Handle Greeting or Start command
        if not user_command or "старт" in user_command or "привет" in user_command:
            response_text = "Привет! Я ваш планировщик. Скажите 'Добавь задачу', чтобы записать дело, или 'Покажи список', чтобы увидеть дела."

        # 2. Handle Add Task command
        elif "добавь" in user_command:
            # Remove keywords to isolate the actual task description
            task_title = user_command.replace("добавь", "").replace("задачу", "").replace("задание", "").strip()
            
            if task_title:
                await task_service.create_task(task_title)
                response_text = f"Поняла, записала: '{task_title}'."
            else:
                response_text = "Что именно добавить?"

        # 3. Handle Show List command
        elif "список" in user_command or "задачи" in user_command or "дела" in user_command or "обнови" in user_command:
            tasks = await task_service.get_all_tasks()
            
            if not tasks:
                response_text = "Список пуст."
            else:
                task_list = []
                # Limit to 5 items to keep the voice response short
                for t in tasks[:5]: 
                    task_list.append(f"{t.id}. {t.title}")
                
                response_text = "Вот список:\n" + "\n".join(task_list)
                
        # 4. Handle Delete command (currently unsupported via voice)
        elif "удали" in user_command or "сотри" in user_command:
             response_text = "Пока я умею только добавлять и показывать. Удалите задачу через Телеграм-бота."

    except Exception as e:
        # Catch any database or runtime errors
        response_text = "Ой, что-то сломалось на сервере. Попробуйте позже."

    # Return structured JSON response expected by Yandex Dialogs
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"🌍 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
