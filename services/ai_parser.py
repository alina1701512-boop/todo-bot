import httpx
import os
import logging
import json
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "qwen/qwen-2.5-72b-instruct:free"  # Бесплатная Qwen

tz = ZoneInfo(os.environ.get("TZ", "Europe/Moscow"))

async def parse_task_with_ai(text: str) -> dict:
    """Отправляет текст в Qwen и возвращает структуру задачи"""
    if not API_KEY:
        logger.warning("OPENROUTER_API_KEY not set")
        return None

    # Получаем текущую дату для контекста
    now = datetime.now(tz)
    
    prompt = f"""
Ты — ассистент для создания задач. Текущая дата: {now.strftime('%d.%m.%Y %H:%M')}

Извлеки из текста:
1. title (название задачи, кратко)
2. priority ("red", "yellow", "green" или "none")
3. due_at (дата и время в формате "YYYY-MM-DDTHH:MM:SS" или null)

Правила:
- "красный/срочно/важно/горит" → red
- "зеленый/легко/лайт" → green  
- иначе → yellow
- Если время не указано, ставь 23:59
- Если дата не ясна, ставь null

Верни ТОЛЬКО JSON:
{{"title": "...", "priority": "...", "due_at": "2026-04-08T18:00:00" или null}}

Текст: "{text}"
"""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("RENDER_EXTERNAL_URL", "http://localhost"),
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, json=data, headers=headers, timeout=15.0)
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Очищаем от markdown
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            parsed = json.loads(content.strip())
            return parsed

    except Exception as e:
        logger.error(f"AI Error: {e}")
        return None
