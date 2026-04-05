import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import dateparser

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    creds = None
    refresh_token = os.environ.get('GOOGLE_REFRESH_TOKEN')
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    
    if refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES
        )
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("No valid credentials found. Please authorize first.")
            
    return build('calendar', 'v3', credentials=creds)

async def create_google_event(task_title: str, due_date_str: str = None):
    try:
        service = get_calendar_service()
        
        start_date = datetime.now()
        if due_date_str:
            # Пытаемся распарсить дату (например "завтра в 14:00")
            parsed = dateparser.parse(due_date_str, settings={'RELATIVE_BASE': datetime.now()})
            if parsed:
                start_date = parsed
        
        end_date = start_date + timedelta(hours=1) # Событие на 1 час
        
        event = {
            'summary': task_title,
            'start': {
                'dateTime': start_date.isoformat(),
                'timeZone': 'Europe/Moscow',
            },
            'end': {
                'dateTime': end_date.isoformat(),
                'timeZone': 'Europe/Moscow',
            },
        }
        
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return created_event.get('htmlLink')
    except Exception as e:
        print(f"Google Calendar Error: {e}")
        return None
