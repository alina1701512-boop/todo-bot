from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in environment variables")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    """Инициализация БД + добавление колонок"""
    async with engine.begin() as conn:
        # Создаём таблицы
        await conn.run_sync(Base.metadata.create_all)
        
        # Добавляем колонки, если их нет (надёжнее чем reset)
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMP"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE"))
            logger.info("✅ Database columns added successfully")
        except Exception as e:
            logger.warning(f"⚠️ Column update warning: {e}")

async def reset_database():
    """Полный сброс БД (если очень нужно)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    logger.info("🗑 Database reset complete")
