from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in environment variables")

# Convert postgres:// to postgresql+asyncpg:// for async support
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    """Инициализация БД + добавление недостающих колонок"""
    async with engine.begin() as conn:
        # Создаём таблицы (если не существуют)
        await conn.run_sync(Base.metadata.create_all)
        
        # Пробуем добавить колонки (игнорируем ошибки если уже есть)
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'yellow'"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS repeat_rule VARCHAR(20) DEFAULT 'none'"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_reminded BOOLEAN DEFAULT FALSE"))
            logger.info("✅ Database columns updated")
        except Exception as e:
            logger.warning(f"⚠️ Could not add columns (may already exist): {e}")

async def reset_database():
    """Полный сброс БД - удалит ВСЕ данные и пересоздаст таблицы!"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    logger.info("🗑 Database reset complete")
