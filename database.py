from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import DATABASE_URL

# Настраиваем движок базы данных
# connect_args={"ssl": "require"} нужно для Neon.tech
engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": "require"})

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
