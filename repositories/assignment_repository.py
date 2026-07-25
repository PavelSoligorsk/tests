from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from core.models import TestAssignment, TestResult


class AssignmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_assignments(self, user_id: int):
        r = await self.db.execute(
            select(TestAssignment)
            .where(TestAssignment.user_id == user_id)
            .order_by(TestAssignment.assigned_at.desc())
        )
        return r.scalars().all()
    
    async def get_assignment(self, test_id: int, user_id: int):
        r = await self.db.execute(
            select(TestAssignment)
            .where(
                TestAssignment.test_id == test_id,
                TestAssignment.user_id == user_id,
                TestAssignment.is_completed == False
            )
        )
        return r.scalars().first()
    
    async def check_deadline(self, assignment) -> bool:
        if assignment.due_date and assignment.due_date < datetime.utcnow():
            return False
        return True
    
    async def get_test_assignments(self, test_id: int):
        """Получить все назначения для теста"""
        r = await self.db.execute(
            select(TestAssignment)
            .where(TestAssignment.test_id == test_id)
            .order_by(TestAssignment.assigned_at.desc())
        )
        return r.scalars().all()

    async def get_assignment_by_id(self, assignment_id: int):
        """Получить назначение по ID"""
        r = await self.db.execute(
            select(TestAssignment).where(TestAssignment.id == assignment_id)
        )
        return r.scalars().first()

    async def check_existing_assignment(self, test_id: int, user_id: int):
        """Проверить дубликат назначения"""
        r = await self.db.execute(
            select(TestAssignment)
            .where(
                TestAssignment.test_id == test_id,
                TestAssignment.user_id == user_id
            )
        )
        return r.scalars().first()

    async def create_assignment(self, test_id: int, user_id: int, 
                        due_date=None, group_id=None):
        """Создать одно назначение"""
        assignment = TestAssignment(
            test_id=test_id,
            user_id=user_id,
            due_date=due_date,
            group_id=group_id,
            assigned_at=datetime.utcnow()
        )
        self.db.add(assignment)
        return assignment

    async def delete_assignment_by_obj(self, assignment):
        """Удалить назначение"""
        await self.db.delete(assignment)
        await self.db.commit()

    async def get_latest_results_for_test(self, test_id: int):
        """Последние результаты всех студентов по тесту"""
        subq = (
            select(
                TestResult.user_id,
                func.max(TestResult.completed_at).label('max_completed_at')
            )
            .where(TestResult.test_id == test_id)
            .group_by(TestResult.user_id)
            .subquery()
        )
        
        r = await self.db.execute(
            select(TestResult).join(
                subq,
                and_(
                    TestResult.user_id == subq.c.user_id,
                    TestResult.completed_at == subq.c.max_completed_at
                )
            )
        )
        return r.scalars().all()

    async def get_latest_results_for_student(self, student_id: int):
        """Последние результаты студента по всем тестам"""
        subq = (
            select(
                TestResult.test_id,
                func.max(TestResult.completed_at).label('max_completed_at')
            )
            .where(TestResult.user_id == student_id)
            .group_by(TestResult.test_id)
            .subquery()
        )
        
        r = await self.db.execute(
            select(TestResult).join(
                subq,
                and_(
                    TestResult.test_id == subq.c.test_id,
                    TestResult.completed_at == subq.c.max_completed_at
                )
            )
        )
        return r.scalars().all()

    async def delete_assignments_by_user(self, user_id: int):
        """Удалить все назначения пользователя"""
        await self.db.execute(
            delete(TestAssignment).where(TestAssignment.user_id == user_id)
        )
