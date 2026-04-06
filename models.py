from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.orm import declarative_base
import enum

Base = declarative_base()

class Priority(str, enum.Enum):
    HIGH = "red"
    MEDIUM = "yellow"
    LOW = "green"

class RepeatRule(str, enum.Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    due_at = Column(DateTime, nullable=True)
    is_done = Column(Boolean, default=False)
    is_reminded = Column(Boolean, default=False)  # Чтобы не спамить напоминаниями
    priority = Column(String, default="yellow")    # red, yellow, green
    repeat_rule = Column(String, default="none")   # none, daily, weekly, monthly
