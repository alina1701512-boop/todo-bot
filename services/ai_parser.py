import httpx
import os
import logging
import json
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_API_KEY")

# 🔥 Более стабильная бесплатная модель
MODEL = "google/gemma-2-2b-it:free"  # или "mistralai/mistral-7b-instruct:free"

tz = ZoneInfo(os.environ.get("TZ", "Europe/Moscow"))

def make_naive(dt: datetime) -> datetime:
    if dt and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

async def _call_qwen(prompt: str, temperature: float = 0.1) -> str:
    if not API_KEY:
        logger.warning("⚠️ OPENROUTER_API_KEY not set")
        return None

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("RENDER_EXTERNAL_URL", "http://localhost"),
        "X-Title": "TodoBot",  # Требуется OpenRouter
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }

    try:
        logger.info(f"🤖 AI Request to {MODEL}: {prompt[:100]}...")
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, json=data, headers=headers, timeout=20.0)
            
            if response.status_code == 404:
                logger.error(f"❌ 404 Error — проверь ключ и модель. Response: {response.text[:200]}")
                return None
                
            response.raise_for_status()
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info(f"✅ AI Response: {content[:100]}...")
            return content.strip()
            
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP Error {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"❌ AI Error: {type(e).__name__}: {e}")
        return None

async def parse_task_with_ai(text: str) -> dict:
    if not API_KEY:
        return None

    now = datetime.now(tz)
    
    prompt = f"""Ты — ассистент для создания задач. Текущая дата: {now.strftime('%d.%m.%Y %H:%M')}

Извлеки из текста СТРОГО в формате JSON:
{{"title": "название", "priority": "red/yellow/green/none", "due_at": "YYYY-MM-DDTHH:MM:SS" или null}}

Правила:
- "красный/срочно/важно/горит" → red
- "зеленый/легко/лайт" → green  
- иначе → yellow
- Если время не указано → 23:59
- Если дата не ясна → null

Текст: "{text}"
Верни ТОЛЬКО JSON без комментариев.
"""
    
    content = await _call_qwen(prompt, temperature=0.1)
    if not content:
        logger.warning("🔄 AI returned empty, falling back to local parser")
        return None

    try:
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        parsed = json.loads(content.strip())
        
        if parsed.get("due_at"):
            try:
                dt = datetime.fromisoformat(parsed["due_at"])
                parsed["due_at"] = make_naive(dt)
            except:
                parsed["due_at"] = None
        
        logger.info(f"✅ AI Parsed: {parsed}")
        return parsed
    except Exception as e:
        logger.error(f"📉 JSON Parse Failed: {e} | Raw: {content[:200]}")
        return None

async def chat_with_ai(user_text: str) -> str:
    if not API_KEY:
        return None
    
    system = "Ты — полезный ассистент. Отвечай кратко, по делу, на русском."
    
    content = await _call_qwen(user_text, temperature=0.7)
    return content
