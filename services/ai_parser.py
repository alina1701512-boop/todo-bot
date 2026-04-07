import httpx
import os
import logging
import json
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "qwen/qwen-2.5-72b-instruct:free"
tz = ZoneInfo(os.environ.get("TZ", "Europe/Moscow"))

def make_naive(dt: datetime) -> datetime:
    if dt and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

async def _call_qwen(prompt: str, temperature: float = 0.1, system_prompt: str = None) -> str:
    if not API_KEY:
        logger.error("❌ OPENROUTER_API_KEY IS MISSING!")
        return None
    
    # ✅ Логируем начало ключа для проверки
    if API_KEY:
        key_preview = API_KEY[:10] + "..." if len(API_KEY) > 10 else API_KEY
        logger.info(f"🔑 Using API Key: {key_preview}")
    else:
        logger.error("🔑 API Key is empty!")

    # ... остальной код

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("RENDER_EXTERNAL_URL", "http://localhost"),
    }

    data = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    try:
        logger.info(f"🤖 AI Request: {prompt[:80]}...")
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, json=data, headers=headers, timeout=15.0)
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            logger.info(f"🤖 AI Response: {content[:80]}...")
            return content
    except Exception as e:
        logger.error(f"🤖 AI Error: {e}")
        return None

async def parse_task_with_ai(text: str) -> dict:
    # 🔥 УЛУЧШЕННЫЙ ПРОМПТ
    prompt = f"""
Извлеки из текста задачи СТРОГО JSON:
{{"title": "название", "priority": "red/yellow/green/none", "due_at": "YYYY-MM-DDTHH:MM:SS"}}

📅 ПРАВИЛА ДАТ:
- "сегодня" → текущая дата, время 23:59
- "завтра" → завтра, время 23:59
- "послезавтра" → +2 дня
- "на днях" → +3 дня
- "в конце месяца" → 28 число текущего месяца
- "в начале месяца" → 5 число текущего/следующего
- "в середине месяца" → 15 число
- "в выходные" → ближайшая суббота
- "через N дней/недель" → посчитай
- Если время указано (18:00), подставь его
- Если дата не ясна → null

🎯 ПРИОРИТЕТ:
- красный/срочно/важно/горит → red
- зеленый/легко/лайт → green
- иначе → yellow

Текст: "{text}"
Верни ТОЛЬКО JSON без комментариев.
"""
    content = await _call_qwen(prompt, temperature=0.1)
    if not content: return None

    try:
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"): content = content[4:]
        parsed = json.loads(content.strip())

        if parsed.get("due_at"):
            try:
                dt = datetime.fromisoformat(parsed["due_at"])
                parsed["due_at"] = make_naive(dt)
            except: parsed["due_at"] = None

        logger.info(f"✅ AI Parsed: {parsed}")
        return parsed
    except Exception as e:
        logger.error(f"📉 AI Parse Failed: {e} | Raw: {content}")
        return None

async def chat_with_ai(user_text: str) -> str:
    system = "Ты — полезный ассистент планировщика. Отвечай кратко, по делу, на русском. Не выдумывай факты."
    return await _call_qwen(user_text, temperature=0.7, system_prompt=system)

async def get_task_tips(title: str, due_at_str: str, priority: str) -> str:
    prompt = f"""Задача: "{title}"
Дата: {due_at_str or 'Не указана'}
Приоритет: {priority}

Дай 1 короткий совет (до 20 слов) на русском. Например: "⏰ Добавь напоминание", "📌 Разбей на шаги", "📅 Дата реалистична?".
"""
    return await _call_qwen(prompt, temperature=0.6)
