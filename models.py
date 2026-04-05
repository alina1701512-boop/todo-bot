from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base
from zoneinfo import ZoneInfo
from config import TZ

tz = ZoneInfo(TZ)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(300), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=True)
    is_done = Column(Boolean, default=False)
    calendar_event_id = Column(String(255), nullable=True)
    yougile_task_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def format_due(self):
        if not self.due_at:
            return "📅 Без срока"
        local = self.due_at.astimezone(tz)
        return f"📅 {local.strftime('%d.%m в %H:%M')}"
