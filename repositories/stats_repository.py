from sqlalchemy import select, func, case, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import List, Optional

from core.models import TestResult, TestTaskAssociation, UserAnswer, Task, User, TeacherStudent


class StatsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_results(self, user_id: int, start_date: Optional[datetime] = None):
        """Получить результаты пользователя за период"""
        stmt = select(TestResult).where(TestResult.user_id == user_id)
        if start_date:
            stmt = stmt.where(TestResult.completed_at >= start_date)
        stmt = stmt.order_by(TestResult.completed_at.desc())
        r = await self.db.execute(stmt)
        return r.scalars().all()
    
    async def get_unique_tasks_count(self, test_ids: List[int]) -> int:
        """Количество уникальных задач в тестах"""
        if not test_ids:
            return 0
        r = await self.db.execute(
            select(func.count(distinct(TestTaskAssociation.task_id)))
            .where(TestTaskAssociation.test_id.in_(test_ids))
        )
        return r.scalar() or 0
    
    async def get_user_answers_by_results(self, result_ids: List[int]):
        """Получить ответы пользователя по ID результатов"""
        if not result_ids:
            return []
        r = await self.db.execute(
            select(UserAnswer).where(UserAnswer.result_id.in_(result_ids))
        )
        return r.scalars().all()
    
    async def get_test_max_points(self, test_ids: List[int]) -> dict:
        """Получить максимальные баллы для тестов"""
        if not test_ids:
            return {}
        
        task_points_expr = case(
            (Task.is_open_answer == True, 2),
            else_=1
        )
        
        r = await self.db.execute(
            select(
                TestTaskAssociation.test_id,
                func.sum(task_points_expr).label("max_total")
            )
            .join(Task, TestTaskAssociation.task_id == Task.id)
            .where(TestTaskAssociation.test_id.in_(test_ids))
            .group_by(TestTaskAssociation.test_id)
        )
        result = r.all()
        
        return {test_id: max_total for test_id, max_total in result}
    
    async def get_test_tasks(self, test_id: int) -> List[int]:
        """Получить ID задач теста"""
        r = await self.db.execute(
            select(TestTaskAssociation.task_id).where(TestTaskAssociation.test_id == test_id)
        )
        return [t[0] for t in r.all()]
    
    async def get_topics_with_counts(self, test_ids: List[int]):
        """Получить темы/разделы с количеством уникальных задач"""
        if not test_ids:
            return []
        
        r = await self.db.execute(
            select(
                Task.topic,
                Task.section,
                func.count(distinct(Task.id)).label("total_unique")
            )
            .join(TestTaskAssociation, Task.id == TestTaskAssociation.task_id)
            .where(TestTaskAssociation.test_id.in_(test_ids))
            .group_by(Task.topic, Task.section)
        )
        return r.all()
    
    async def get_difficulty_counts(self, test_ids: List[int]):
        """Получить сложность с количеством уникальных задач"""
        if not test_ids:
            return []
        
        r = await self.db.execute(
            select(
                Task.difficulty,
                func.count(distinct(Task.id)).label("total_unique")
            )
            .join(TestTaskAssociation, Task.id == TestTaskAssociation.task_id)
            .where(TestTaskAssociation.test_id.in_(test_ids))
            .group_by(Task.difficulty)
        )
        return r.all()
    
    async def get_task_by_id(self, task_id: int):
        """Получить задачу по ID"""
        r = await self.db.execute(select(Task).where(Task.id == task_id))
        return r.scalars().first()
    
    async def get_user_by_id(self, user_id: int):
        """Получить пользователя по ID"""
        r = await self.db.execute(select(User).where(User.id == user_id))
        return r.scalars().first()
    
    async def check_teacher_student_link(self, teacher_id: int, student_id: int) -> bool:
        """Проверить связь учитель-ученик"""
        r = await self.db.execute(
            select(TeacherStudent).where(
                TeacherStudent.teacher_id == teacher_id,
                TeacherStudent.student_id == student_id
            )
        )
        link = r.scalars().first()
        return link is not None