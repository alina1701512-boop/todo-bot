import os
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
APP_HOST = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000").rstrip("/")
TZ = os.getenv("TZ", "Europe/Moscow")

# 🔥 Google Calendar
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
