import os
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from database import async_session
from models import UserGoogleAuth
from sqlalchemy import select, delete

logger = logging.getLogger(__name__)

# Настройки
SCOPES = ['https://www.googleapis.com/auth/calendar']
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Moscow"))

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def _get_flow():
    """Создаёт OAuth flow для авторизации"""
    return InstalledAppFlow.from_client_config(
        {
            "installed": {  # Важно: используем "installed" для OAuth out-of-band
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]
            }
        },
        SCOPES
    )

async def _get_creds_from_db(user_id: str):
    """Получает и обновляет токен из базы данных"""
    async with async_session() as session:
        result = await session.execute(
            select(UserGoogleAuth).where(UserGoogleAuth.user_id == str(user_id))
        )
        user_auth = result.scalar_one_or_none()
        
        if not user_auth:
            return None
        
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(user_auth.creds), SCOPES
            )
            
            # Авто-обновление токена если истёк
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Сохраняем обновлённый токен
                user_auth.creds = json.dumps(creds.to_json())
                await session.commit()
                logger.info(f"🔄 Token refreshed for user {user_id}")
            
            return creds
        except Exception as e:
            logger.error(f"❌ Token error for user {user_id}: {e}")
            return None

# ================= ОСНОВНЫЕ ФУНКЦИИ =================

async def get_auth_url(user_id: str) -> str:
    """Генерирует ссылку для авторизации пользователя"""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("Google credentials not configured")
    
    flow = _get_flow()
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'  # Всегда запрашивать согласие, чтобы получить refresh_token
    )
    return auth_url

async def save_code(user_id: str, code: str) -> bool:
    """Сохраняет токен после получения кода от пользователя"""
    try:
        flow = _get_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        async with async_session() as session:
            # Проверяем, есть ли запись
            result = await session.execute(
                select(UserGoogleAuth).where(UserGoogleAuth.user_id == str(user_id))
            )
            user_auth = result.scalar_one_or_none()
            
            if not user_auth:
                user_auth = UserGoogleAuth(user_id=str(user_id))
                session.add(user_auth)
            
            # Сохраняем токен как JSON
            user_auth.creds = json.dumps(creds.to_json())
            await session.commit()
            
        logger.info(f"✅ Google auth saved for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save Google auth: {e}")
        return False

async def disconnect_google(user_id: str) -> bool:
    """Удаляет привязку к Google аккаунту"""
    try:
        async with async_session() as session:
            stmt = delete(UserGoogleAuth).where(UserGoogleAuth.user_id == str(user_id))
            await session.execute(stmt)
            await session.commit()
        logger.info(f"🗑️ Google auth disconnected for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to disconnect Google: {e}")
        return False

async def sync_task_to_calendar(user_id: str, task) -> str | None:
    """
    Синхронизирует задачу с Google Calendar.
    Если у задачи нет даты (due_at=None) → ставит на сегодня в 12:00.
    Возвращает ссылку на событие или None при ошибке.
    """
    creds = await _get_creds_from_db(user_id)
    if not creds:
        logger.warning(f"⚠️ No valid Google creds for user {user_id}")
        return None

    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        
        # 🔥 ЛОГИКА ДАТЫ: если нет due_at → сегодня в 12:00
        if task.due_at:
            event_time = task.due_at
            # Если в дате нет времени, ставим 12:00
            if event_time.hour == 0 and event_time.minute == 0:
                event_time = event_time.replace(hour=12, minute=0)
        else:
            # Нет даты → сегодня в 12:00
            event_time = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)
            logger.info(f"📅 Task '{task.title}' has no date, scheduling for today 12:00")
        
        # Формируем событие
        event = {
            'summary': task.title,
            'description': f"🤖 Создано в Telegram-боте\nПриоритет: {task.priority}",
            'start': {
                'dateTime': event_time.isoformat(),
                'timeZone': str(TZ),
            },
            'end': {
                'dateTime': (event_time + timedelta(hours=1)).isoformat(),
                'timeZone': str(TZ),
            },
        }
        
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        html_link = created_event.get('htmlLink')
        logger.info(f"✅ Event synced: {task.title} → {html_link}")
        return html_link
        
    except Exception as e:
        logger.error(f"❌ Calendar sync error: {e}")
        return None
