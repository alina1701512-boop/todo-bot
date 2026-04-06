from sqlalchemy import select, func
from database import async_session
from models import Task
from datetime import datetime, date

async def create_task(title: str, due_at: datetime | None = None) -> Task:
    async with async_session() as session:
        task = Task(title=title, due_at=due_at)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

async def get_all_tasks() -> list[Task]:
    async with async_session() as session:
        res = await session.execute(
            select(Task).order_by(
                Task.is_done.asc(), 
                Task.due_at.asc().nullslast()
            )
        )
        return list(res.scalars().all())

async def get_task_by_id(task_id: int) -> Task | None:
    """Get single task by ID"""
    async with async_session() as session:
        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

async def get_tasks_for_date(target_date: date) -> list[Task]:
    """Get tasks for specific date"""
    async with async_session() as session:
        stmt = select(Task).where(
            func.date(Task.due_at) == target_date
        ).order_by(Task.due_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())

async def update_task(task_id: int, **kwargs) -> Task | None:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task: 
            return None
        for k, v in kwargs.items():
            setattr(task, k, v)
        await session.commit()
        await session.refresh(task)
        return task

async def delete_task(task_id: int) -> bool:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task: 
            return False
        await session.delete(task)
        await session.commit()
        return True
