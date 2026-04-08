from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    due_at = Column(DateTime, nullable=True)
    is_done = Column(Boolean, default=False)
    priority = Column(String, default="none")  # red, yellow, green, none
    repeat_rule = Column(String, default="none")  # daily, weekly, monthly
    is_reminded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_archived = Column(Boolean, default=False)

# ================= 🔐 GOOGLE AUTH =================
class UserGoogleAuth(Base):
    """Хранит токены доступа к Google Calendar для каждого пользователя"""
    __tablename__ = "user_google_auth"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, nullable=False, index=True)  # Telegram user_id
    creds = Column(Text)  # JSON-строка с токенами (access + refresh)
    
    # 🔥 НОВОЕ ПОЛЕ: ID пользователя
    user_id = Column(String, nullable=True, index=True)  # Telegram user_id (строка)
