import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, TZ, APP_HOST
from database import async_session
from models import UserGoogleAuth
from sqlalchemy import select, delete

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']

async def get_auth_url(user_id: str) -> str:
    """Генерирует ссылку для авторизации"""
    from urllib.parse import urlencode
    
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': f"{APP_HOST}/callback",
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
    }
    
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

async def save_code(user_id: str, code: str) -> bool:
    """Сохраняет токен после получения кода"""
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [f"{APP_HOST}/callback"]
                }
            },
            scopes=SCOPES,
            redirect_uri=f"{APP_HOST}/callback"
        )
        
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # 🔥 Правильно сохраняем токен
        creds_info = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': list(creds.scopes)
        }
        
        async with async_session() as session:
            result = await session.execute(
                select(UserGoogleAuth).where(UserGoogleAuth.user_id == str(user_id))
            )
            user_auth = result.scalar_one_or_none()
            
            if not user_auth:
                user_auth = UserGoogleAuth(user_id=str(user_id))
                session.add(user_auth)
            
            user_auth.creds = json.dumps(creds_info)
            await session.commit()
            
        logger.info(f"✅ Google auth saved for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save Google auth: {e}")
        return False

async def _get_creds_from_db(user_id: str):
    """Получает и обновляет токен из БД"""
    async with async_session() as session:
        result = await session.execute(
            select(UserGoogleAuth).where(UserGoogleAuth.user_id == str(user_id))
        )
        user_auth = result.scalar_one_or_none()
        
        if not user_auth or not user_auth.creds:
            return None
        
        try:
            creds_info = json.loads(user_auth.creds)
            
            # 🔥 ФИКС: если после loads() получили строку (старый формат) — парсим ещё раз
            if isinstance(creds_info, str):
                creds_info = json.loads(creds_info)
            
            creds = Credentials.from_authorized_user_info(creds_info, SCOPES)
            
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Обновляем токен в БД
                updated_info = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': list(creds.scopes) if creds.scopes else []
                }
                user_auth.creds = json.dumps(updated_info)
                await session.commit()
                logger.info(f"🔄 Token refreshed for user {user_id}")
            
            return creds
        except Exception as e:
            logger.error(f"❌ Token error for user {user_id}: {e}")
            return None

async def disconnect_google(user_id: str) -> bool:
    """Отключает Google аккаунт"""
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
    """Синхронизирует задачу с Google Calendar"""
    creds = await _get_creds_from_db(user_id)
    if not creds:
        logger.warning(f"⚠️ No valid Google creds for user {user_id}")
        return None

    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        
        if task.due_at:
            event_time = task.due_at
            if event_time.hour == 0 and event_time.minute == 0:
                event_time = event_time.replace(hour=12, minute=0)
        else:
            event_time = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)
            logger.info(f"📅 Task '{task.title}' has no date, scheduling for today 12:00")
        
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
