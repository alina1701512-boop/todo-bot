from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    due_at = Column(DateTime, nullable=True)
    is_done = Column(Boolean, default=False)
    priority = Column(String, default="none")
    repeat_rule = Column(String, default="none")
    is_reminded = Column(Boolean, default=False)
    
    # Новые поля для авто-очистки
    created_at = Column(DateTime, default=datetime.utcnow)
    is_archived = Column(Boolean, default=False)
