from sqlalchemy import select, func
from database import async_session
from models import Task
from datetime import datetime, date, timedelta
import logging

logger = logging.getLogger(__name__)

# ================= СОЗДАНИЕ =================
async def create_task(title: str, due_at, priority: str = "none", repeat_rule: str = "none", user_id: str = None) -> Task:
    async with async_session() as session:
        task = Task(
            title=title, 
            due_at=due_at, 
            priority=priority, 
            repeat_rule=repeat_rule,
            created_at=datetime.utcnow(),
            user_id=str(user_id) if user_id else None
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        
        # Авто-синхронизация с Google Calendar
        if user_id:
            try:
                from services.google_calendar import sync_task_to_calendar
                await sync_task_to_calendar(user_id, task)
            except ImportError:
                logger.warning("⚠️ google_calendar module not found, skipping sync")
            except Exception as e:
                logger.error(f"❌ Calendar sync failed: {e}")
        
        return task

# ================= ПОЛУЧЕНИЕ =================
async def get_all_tasks(user_id: str = None):
    async with async_session() as session:
        stmt = select(Task).where(Task.is_archived == False)
        if user_id:
            stmt = stmt.where(Task.user_id == str(user_id))
        stmt = stmt.order_by(Task.is_done.asc(), Task.due_at.asc().nullslast())
        res = await session.execute(stmt)
        return res.scalars().all()

async def get_task_by_id(task_id: int):  # 🔥 ЭТА ФУНКЦИЯ БЫЛА УТЕРЯНА — ВОЗВРАЩАЕМ
    async with async_session() as session:
        res = await session.execute(select(Task).where(Task.id == task_id))
        return res.scalar_one_or_none()

async def get_tasks_for_date(target_date: date, user_id: str = None):
    async with async_session() as session:
        stmt = select(Task).where(
            Task.is_archived == False,
            func.date(Task.due_at) == target_date
        )
        if user_id:
            stmt = stmt.where(Task.user_id == str(user_id))
        stmt = stmt.order_by(Task.due_at)
        res = await session.execute(stmt)
        return res.scalars().all()

async def get_tasks_for_week(start_date: date, user_id: str = None):
    end_date = start_date + timedelta(days=7)
    async with async_session() as session:
        stmt = select(Task).where(
            Task.is_archived == False,
            func.date(Task.due_at) >= start_date,
            func.date(Task.due_at) <= end_date
        )
        if user_id:
            stmt = stmt.where(Task.user_id == str(user_id))
        stmt = stmt.order_by(Task.due_at)
        res = await session.execute(stmt)
        return res.scalars().all()

# ================= ОБНОВЛЕНИЕ / УДАЛЕНИЕ =================
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

# ================= ОЧИСТКА =================
async def cleanup_old_tasks():
    async with async_session() as session:
        stmt = select(Task).where(Task.is_archived == False)
        res = await session.execute(stmt)
        tasks = res.scalars().all()
        
        now = datetime.utcnow()
        moved_count = 0
        archived_count = 0
        
        for t in tasks:
            age = now - t.created_at
            
            if t.is_done:
                t.is_archived = True
                archived_count += 1
                continue

            if t.due_at and t.due_at < now:
                tomorrow = now.date() + timedelta(days=1)
                t.due_at = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59)
                moved_count += 1

            if age.days > 30 and t.priority != "red":
                t.is_archived = True
                archived_count += 1
                
        await session.commit()
        logger.info(f"🧹 Cleanup done: Moved {moved_count}, Archived {archived_count}")

# ================= СТАТИСТИКА =================
async def get_task_stats(user_id: str = None) -> dict:
    async with async_session() as session:
        now = datetime.utcnow()
        base_conditions = [Task.is_archived == False]
        if user_id:
            base_conditions.append(Task.user_id == str(user_id))
        
        total = await session.scalar(select(func.count(Task.id)).where(*base_conditions))
        done = await session.scalar(select(func.count(Task.id)).where(*base_conditions, Task.is_done == True))
        pending = (total or 0) - (done or 0)
        
        overdue_conditions = base_conditions + [Task.is_done == False, Task.due_at < now, Task.due_at.isnot(None)]
        overdue = await session.scalar(select(func.count(Task.id)).where(*overdue_conditions))
        
        priorities = await session.execute(
            select(Task.priority, func.count(Task.id)).where(*base_conditions).group_by(Task.priority)
        )
        p_counts = dict(priorities.all())
        
        return {
            "total": total or 0,
            "done": done or 0,
            "pending": pending,
            "overdue": overdue or 0,
            "red": p_counts.get("red", 0),
            "yellow": p_counts.get("yellow", 0),
            "green": p_counts.get("green", 0),
            "none": p_counts.get("none", 0)
        }

# ================= НАПОМИНАНИЯ =================
async def send_reminders(bot):
    now = datetime.utcnow()
    one_hour_later = now + timedelta(hours=1)
    fifteen_min_later = now + timedelta(minutes=15)
    
    async with async_session() as session:
        stmt_1h = select(Task).where(
            Task.is_done == False,
            Task.is_archived == False,
            Task.is_reminded == False,
            Task.due_at <= one_hour_later,
            Task.due_at > now,
            Task.user_id.isnot(None)
        )
        res_1h = await session.execute(stmt_1h)
        tasks_1h = res_1h.scalars().all()
        
        stmt_15m = select(Task).where(
            Task.is_done == False,
            Task.is_archived == False,
            Task.is_reminded == False,
            Task.due_at <= fifteen_min_later,
            Task.due_at > now,
            Task.user_id.isnot(None)
        )
        res_15m = await session.execute(stmt_15m)
        tasks_15m = res_15m.scalars().all()
        
        all_to_remind = tasks_1h + tasks_15m
        
        for task in all_to_remind:
            try:
                time_left = "⏳ Осталось ~1 час" if task in tasks_1h else "⏳ Осталось ~15 минут"
                await bot.send_message(
                    chat_id=int(task.user_id),
                    text=f"🔔 **Напоминание!**\n\n📝 {task.title}\n🕐 Дедлайн: {task.due_at.strftime('%d.%m в %H:%M')}\n{time_left}",
                    parse_mode="Markdown"
                )
                task.is_reminded = True
                await session.commit()
            except Exception as e:
                logger.error(f"❌ Reminder failed for task {task.id}: {e}")
                await session.rollback()
