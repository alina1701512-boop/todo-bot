from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

# Создаём движок с пулом соединений
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # 🔥 ВАЖНО: проверяет соединение перед использованием
    pool_recycle=1800,   # 🔥 Пересоздаёт соединения каждые 30 минут
)

async_session = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

Base = declarative_base()

async def init_db():
    """Создаёт таблицы, если их нет"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database initialized")
