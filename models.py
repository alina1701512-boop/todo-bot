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

from sqlalchemy import text

async def add_missing_columns():
    """Добавляет недостающие колонки в таблицу tasks"""
    try:
        async with engine.begin() as conn:
            # Проверяем и добавляем колонки
            await conn.execute(text("""
                ALTER TABLE tasks 
                ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'yellow',
                ADD COLUMN IF NOT EXISTS repeat_rule VARCHAR(20) DEFAULT 'none',
                ADD COLUMN IF NOT EXISTS is_reminded BOOLEAN DEFAULT FALSE
            """))
            logger.info("✅ Added missing columns to tasks table")
    except Exception as e:
        logger.error(f"❌ Error adding columns: {e}")
