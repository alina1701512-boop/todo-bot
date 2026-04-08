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

async def migrate_add_user_id():
    """Добавляет поле user_id в таблицу tasks, если его нет."""
    from sqlalchemy import text
    try:
        async with async_session() as session:
            await session.execute(text("ALTER TABLE tasks ADD COLUMN user_id VARCHAR"))
            await session.commit()
            logger.info("✅ Migration: Added user_id column to tasks table")
    except Exception as e:
        logger.info(f"ℹ️ Migration: user_id column likely already exists ({e})")
        async with async_session() as session:
            await session.rollback()

# ================= 🔐 MIGRATION: GOOGLE AUTH TABLE =================
async def migrate_create_google_auth_table():
    """Создаёт таблицу user_google_auth, если её нет."""
    from sqlalchemy import text
    
    try:
        async with async_session() as session:
            # Создаём таблицу вручную, если не существует
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS user_google_auth (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR UNIQUE NOT NULL,
                    creds TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_user_google_auth_user_id ON user_google_auth (user_id);
            """))
            await session.commit()
            logger.info("✅ Migration: Table 'user_google_auth' created or already exists")
    except Exception as e:
        logger.error(f"❌ Migration error: {e}")
        async with async_session() as session:
            await session.rollback()
