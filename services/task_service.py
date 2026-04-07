from sqlalchemy import select, func
from database import async_session
from models import Task
from datetime import datetime, date, timedelta

async def create_task(title: str, due_at, priority: str = "none", repeat_rule: str = "none") -> Task:
    async with async_session() as session:
        task = Task(title=title, due_at=due_at, priority=priority, repeat_rule=repeat_rule)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

async def get_all_tasks():
    async with async_session() as session:
        stmt = select(Task).order_by(Task.is_done.asc(), Task.due_at.asc().nullslast())
        res = await session.execute(stmt)
        return res.scalars().all()

async def get_task_by_id(task_id: int):
    async with async_session() as session:
        res = await session.execute(select(Task).where(Task.id == task_id))
        return res.scalar_one_or_none()

async def get_tasks_for_date(target_date: date):
    async with async_session() as session:
        stmt = select(Task).where(func.date(Task.due_at) == target_date).order_by(Task.due_at)
        res = await session.execute(stmt)
        return res.scalars().all()

async def get_tasks_for_week(start_date: date):
    end_date = start_date + timedelta(days=7)
    async with async_session() as session:
        stmt = select(Task).where(
            func.date(Task.due_at) >= start_date,
            func.date(Task.due_at) <= end_date
        ).order_by(Task.due_at)
        res = await session.execute(stmt)
        return res.scalars().all()

async def update_task(task_id: int, **kwargs):
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task:
            for k, v in kwargs.items():
                setattr(task, k, v)
            await session.commit()
            await session.refresh(task)
        return task

async def delete_task(task_id: int):
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task:
            await session.delete(task)
            await session.commit()
            return True
    return False

# ❌ Временно отключаем cleanup_old_tasks, чтобы не было ошибок
async def cleanup_old_tasks():
    """Заглушка — функционал архивации вернём позже"""
    pass
