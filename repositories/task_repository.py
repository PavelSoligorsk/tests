from sqlalchemy import select, func, or_, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from core.models import (
    Task, TestTaskAssociation, UserAnswer
)


class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_task_by_id(self, task_id: int):
        result = await self.db.execute(select(Task).where(Task.id == task_id))
        return result.scalars().first()
    
    async def get_tasks_by_ids(self, task_ids: List[int]):
        result = await self.db.execute(select(Task).where(Task.id.in_(task_ids)))
        return result.scalars().all()
    
    async def get_tasks_by_topics(self, topics: List[str], sections_map: dict, difficulties: List[int], limit: int = 300):
        conditions = []
        for topic, sections in sections_map.items():
            if sections:
                conditions.append(
                    and_(
                        Task.topic == topic,
                        Task.section.in_(sections)
                    )
                )
            else:
                conditions.append(Task.topic == topic)
        
        if conditions:
            result = await self.db.execute(
                select(Task).where(
                    or_(*conditions),
                    Task.difficulty.in_(difficulties)
                ).limit(limit)
            )
            return result.scalars().all()
        return []
    
    async def get_random_tasks(self, count: int, task_type: Optional[bool] = None, difficulties: List[int] = None):
        stmt = select(Task)
        
        if task_type is not None:
            stmt = stmt.where(Task.is_open_answer == task_type)
        
        if difficulties:
            stmt = stmt.where(Task.difficulty.in_(difficulties))
        
        stmt = stmt.order_by(func.random()).limit(count)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_tasks_by_keywords(self, keywords: List[str], difficulties: List[int], limit: int = 300):
        like_conditions = [Task.topic.ilike(f"%{word}%") for word in keywords]
        result = await self.db.execute(
            select(Task).where(
                or_(*like_conditions),
                Task.difficulty.in_(difficulties)
            ).limit(limit)
        )
        return result.scalars().all()
    
    async def get_tasks_structure(self):
        result = await self.db.execute(
            select(Task.topic, Task.section)
            .where(Task.topic != None)
            .distinct()
        )
        return result.all()
    
    async def get_tasks_by_test_id(self, test_id: int):
        result = await self.db.execute(
            select(Task)
            .join(TestTaskAssociation)
            .where(TestTaskAssociation.test_id == test_id)
            .order_by(Task.topic_number)
        )
        return result.scalars().all()
    
    async def get_filtered_tasks(self, task_class=None, topic=None, topic_number=None, section=None):
        """Получить задания с фильтрацией"""
        stmt = select(Task).order_by(
            Task.task_class,
            Task.topic_number,
            Task.is_open_answer.asc(),
            Task.difficulty.asc()
        )
        
        if task_class is not None:
            stmt = stmt.where(Task.task_class == str(task_class))
        if topic:
            stmt = stmt.where(Task.topic == topic)
        if topic_number:
            stmt = stmt.where(Task.topic_number == topic_number)
        if section:
            stmt = stmt.where(Task.section == section)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_all_tasks_ordered(self):
        """Получить все задания с сортировкой"""
        result = await self.db.execute(
            select(Task).order_by(
                Task.task_class,
                Task.topic_number,
                Task.is_open_answer.asc(),
                Task.difficulty.asc()
            )
        )
        return result.scalars().all()
    
    async def get_all_tasks(self):
        """Получить все задания"""
        result = await self.db.execute(select(Task))
        return result.scalars().all()

    async def create_task(self, task_data: dict):
        """Создать задание"""
        new_task = Task(**task_data)
        self.db.add(new_task)
        await self.db.commit()
        await self.db.refresh(new_task)
        return new_task

    async def update_task(self, task: Task, update_data: dict):
        """Обновить задание"""
        for key, value in update_data.items():
            setattr(task, key, value)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def delete_task(self, task_id: int):
        """Удалить задание и связанные данные"""
        try:
            await self.db.execute(
                delete(UserAnswer).where(UserAnswer.task_id == task_id)
            )
            
            await self.db.execute(
                delete(TestTaskAssociation).where(TestTaskAssociation.task_id == task_id)
            )
            
            task = await self.get_task_by_id(task_id)
            if task:
                await self.db.delete(task)
                await self.db.commit()
            return True
        except Exception as e:
            await self.db.rollback()
            raise e

    async def get_active_categories(self):
        """Получить уникальные пары класс-тема"""
        result = await self.db.execute(
            select(Task.task_class, Task.topic_number).distinct()
        )
        return result.all()

    async def get_all_tasks_dict(self):
        """Получить словарь {id: task}"""
        result = await self.db.execute(select(Task))
        tasks = result.scalars().all()
        return {task.id: task for task in tasks}

    async def get_tasks_by_class_and_topic(self, task_class, topic_number):
        """Получить задания по классу и теме"""
        result = await self.db.execute(
            select(Task).where(
                Task.task_class == task_class,
                Task.topic_number == topic_number
            ).order_by(
                Task.is_open_answer.asc(),
                Task.difficulty.asc()
            )
        )
        return result.scalars().all()
    
    async def get_tasks_by_topic_and_section(self, topic: str, section: str):
        """Получить задания по теме и разделу, обрабатывая NULL-значения."""
        stmt = select(Task)

        # Обработка темы
        if topic == "Без темы":
            # Ищем задания, у которых topic IS NULL или пустая строка
            stmt = stmt.where(
                (Task.topic.is_(None)) | (Task.topic == '')
            )
        else:
            stmt = stmt.where(Task.topic == topic)

        # Обработка раздела
        if section == "Без раздела":
            stmt = stmt.where(
                (Task.section.is_(None)) | (Task.section == '')
            )
        else:
            stmt = stmt.where(Task.section == section)

        stmt = stmt.order_by(
            Task.is_open_answer.asc(),
            Task.difficulty.asc()
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()