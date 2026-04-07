import httpx
import os
import logging
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

API_URL = "https://api.groq.com/openai/v1/chat/completions"
API_KEY = os.environ.get("GROQ_API_KEY")
MODEL = "llama-3.1-8b-instant"
tz = ZoneInfo(os.environ.get("TZ", "Europe/Moscow"))

def make_naive(dt: datetime) -> datetime:
    if dt and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

async def _call_groq(prompt: str, temperature: float = 0.1) -> str:
    if not API_KEY:
        logger.warning("⚠️ GROQ_API_KEY not set")
        return None

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": 500}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, json=data, headers=headers, timeout=20.0)
            if response.status_code in [401, 403, 404]:
                logger.error(f"❌ Groq Auth/Config Error: {response.status_code} {response.text[:100]}")
                return None
            response.raise_for_status()
            return response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"❌ Groq Error: {e}")
        return None

async def parse_task_with_ai(text: str) -> dict:
    if not API_KEY: return None
    now = datetime.now(tz)

    # 🔥 ДИНАМИЧЕСКИЙ ПРОМПТ С ТОЧНЫМИ ДАТАМИ
    prompt = f"""Ты — ассистент для создания задач. ТЕКУЩАЯ ДАТА И ВРЕМЯ: {now.strftime('%Y-%m-%d %H:%M')}

Извлеки из текста СТРОГО JSON:
{{"title": "название", "priority": "red/yellow/green/none", "due_at": "YYYY-MM-DDTHH:MM:SS" или null}}

📅 ПРАВИЛА ДАТ (применяй строго):
- "сегодня" → {now.strftime('%Y-%m-%d')}
- "завтра" → {(now + timedelta(days=1)).strftime('%Y-%m-%d')}
- "послезавтра" → {(now + timedelta(days=2)).strftime('%Y-%m-%d')}
- "на днях" → {(now + timedelta(days=3)).strftime('%Y-%m-%d')}
- "в конце месяца" → {now.replace(day=28).strftime('%Y-%m-%d')}
- "в начале месяца" → {now.replace(day=5).strftime('%Y-%m-%d')}
- "в середине месяца" → {now.replace(day=15).strftime('%Y-%m-%d')}
- "через N дней" → вычисли дату от сегодня
- Время "в HH:MM" → подставь. Иначе → 23:59.
- Неясно → null.

🎯 ПРИОРИТЕТ: красный/срочно/важно → red | зеленый/легко → green | иначе → yellow

Текст: "{text}"
Верни ТОЛЬКО JSON.
"""
    content = await _call_groq(prompt, temperature=0.1)
    if not content: return None

    try:
        if "```" in content:
            content = content.split("```")[1].strip()
            if content.startswith("json"): content = content[4:]
        parsed = json.loads(content)
        if parsed.get("due_at"):
            try: parsed["due_at"] = make_naive(datetime.fromisoformat(parsed["due_at"]))
            except: parsed["due_at"] = None
        return parsed
    except Exception as e:
        logger.error(f"📉 JSON Parse Failed: {e}")
        return None

async def chat_with_ai(user_text: str) -> str:
    if not API_KEY: return None
    return await _call_groq(user_text, temperature=0.7)

# ================= 🎤 ГОЛОСОВАЯ ТРАНСКРИБАЦИЯ (Whisper) =================
async def transcribe_voice(audio_bytes: bytes) -> str:
    """
    Отправляет аудио в Groq Whisper и возвращает распознанный текст.
    """
    if not API_KEY:
        logger.warning("⚠️ GROQ_API_KEY not set for transcription")
        return None

    # Groq Whisper API endpoint
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
    }
    
    # Формируем multipart/form-data запрос
    data = {
        "model": "distil-whisper-large-v3-en",  # Поддерживает русский!
        "language": "ru",  # Явно указываем русский для точности
    }
    
    files = {
        "file": ("voice.ogg", audio_bytes, "audio/ogg"),
    }

    try:
        logger.info("🎤 Sending voice to Groq Whisper...")
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=data, files=files, timeout=30.0)
            
            if response.status_code != 200:
                logger.error(f"❌ Whisper Error {response.status_code}: {response.text[:200]}")
                return None
                
            result = response.json()
            text = result.get("text", "").strip()
            logger.info(f"✅ Transcribed: {text}")
            return text
            
    except Exception as e:
        logger.error(f"❌ Transcription Error: {e}")
        return None
