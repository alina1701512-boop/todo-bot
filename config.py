import os
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
APP_HOST = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000").rstrip("/")
TZ = os.getenv("TZ", "Europe/Moscow")
