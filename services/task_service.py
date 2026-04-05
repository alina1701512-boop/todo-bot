from sqlalchemy import select
from database import async_session
from models import Task
from datetime import datetime

async def create_task(title: str, due_at: datetime | None = None) -> Task:
    async with async_session() as session:
        task = Task(title=title, due_at=due_at)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

async def get_all_tasks() -> list[Task]:
    async with async_session() as session:
        res = await session.execute(select(Task).order_by(Task.is_done.asc(), Task.due_at.asc().nullslast()))
        return list(res.scalars().all())

async def update_task(task_id: int, **kwargs) -> Task | None:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task: return None
        for k, v in kwargs.items():
            setattr(task, k, v)
        await session.commit()
        await session.refresh(task)
        return task

async def delete_task(task_id: int) -> bool:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task: return False
        await session.delete(task)
        await session.commit()
        return True
