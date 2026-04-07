from sqlalchemy import select, func
from database import async_session
from models import Task
from datetime import datetime, date, timedelta, timezone

async def create_task(title: str, due_at, priority: str = "none", repeat_rule: str = "none") -> Task:
    async with async_session() as session:
        task = Task(
            title=title, 
            due_at=due_at, 
            priority=priority, 
            repeat_rule=repeat_rule,
            created_at=datetime.utcnow() # Запоминаем дату создания
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

async def get_all_tasks():
    async with async_session() as session:
        # ✅ Показываем только те, которые НЕ скрыты (is_archived=False)
        stmt = select(Task).where(Task.is_archived == False).order_by(Task.is_done.asc(), Task.due_at.asc().nullslast())
        res = await session.execute(stmt)
        return res.scalars().all()

async def get_task_by_id(task_id: int):
    async with async_session() as session:
        res = await session.execute(select(Task).where(Task.id == task_id))
        return res.scalar_one_or_none()

async def get_tasks_for_date(target_date: date):
    async with async_session() as session:
        stmt = select(Task).where(
            Task.is_archived == False,
            func.date(Task.due_at) == target_date
        ).order_by(Task.due_at)
        res = await session.execute(stmt)
        return res.scalars().all()

async def get_tasks_for_week(start_date: date):
    end_date = start_date + timedelta(days=7)
    async with async_session() as session:
        stmt = select(Task).where(
            Task.is_archived == False,
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

#  АВТОМАТИЧЕСКАЯ ОЧИСТКА (Запускается в 00:00 МСК)
async def cleanup_old_tasks():
    """
    1. Выполненные задачи -> Скрывает (is_archived=True)
    2. Просроченные задачи -> Переносит на завтра
    3. Красные задачи старше 30 дней -> Скрывает
    4. Остальные задачи старше 30 дней -> Скрывает (чтобы база не пухла)
    """
    async with async_session() as session:
        # Берем все активные задачи
        stmt = select(Task).where(Task.is_archived == False)
        res = await session.execute(stmt)
        tasks = res.scalars().all()
        
        now = datetime.utcnow()
        moved_count = 0
        archived_count = 0
        
        for t in tasks:
            age = now - t.created_at
            
            # 1. Если выполнена -> Скрыть
            if t.is_done:
                t.is_archived = True
                archived_count += 1
                continue

            # 2. Если просрочена (дата меньше текущего момента)
            if t.due_at and t.due_at < now:
                # Переносим на завтра (в конец дня)
                tomorrow = now.date() + timedelta(days=1)
                t.due_at = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59)
                moved_count += 1

                # 3. Проверка возраста для Красных и остальных
