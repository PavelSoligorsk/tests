from sqlalchemy import select, func, delete
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from core.models import (
    Test, Task, TestResult, UserAnswer, TestAssignment, TestTaskAssociation
)


class TestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_available_tests(self):
        result = await self.db.execute(
            select(Test)
            .options(joinedload(Test.tasks))
            .where(
                Test.is_active == True,
                (Test.is_autocompile == True) | (Test.is_autocompile == None)
            )
        )
        return result.unique().scalars().all()
    
    async def get_test_by_id(self, test_id: int):
        result = await self.db.execute(
            select(Test)
            .options(joinedload(Test.tasks))
            .where(Test.id == test_id)
        )
        return result.unique().scalars().first()
    
    async def get_tests_by_ids(self, test_ids: List[int]):
        result = await self.db.execute(
            select(Test)
            .options(joinedload(Test.tasks))
            .where(Test.id.in_(test_ids))
        )
        return result.unique().scalars().all()
    
    async def create_test(self, test_data: dict, tasks: List[Task]):
        new_test = Test(**test_data)
        self.db.add(new_test)
        await self.db.flush()
        new_test.tasks = tasks
        await self.db.commit()
        # refresh() would expunge the lazy-loaded 'tasks' relationship,
        # causing greenlet_spawn errors during Pydantic serialization.
        # expire_on_commit=False already preserves object state after commit.
        return new_test
    
    async def deactivate_test(self, test_id: int):
        test = await self.get_test_by_id(test_id)
        if test:
            test.is_active = False
            await self.db.commit()
        return test
    
    async def get_test_with_tasks(self, test_id: int):
        result = await self.db.execute(
            select(Test)
            .options(joinedload(Test.tasks))
            .where(Test.id == test_id)
        )
        return result.unique().scalars().first()
    
    async def get_teacher_tests(self, teacher_id: int, role: str):
        """Получить тесты учителя или все для админа"""
        stmt = select(Test).options(joinedload(Test.tasks))
        
        if role == "teacher":
            stmt = stmt.where(Test.creator_id == teacher_id)
        
        stmt = stmt.order_by(Test.id.desc())
        result = await self.db.execute(stmt)
        return result.unique().scalars().all()

    async def update_test(self, test: Test, update_data: dict, tasks=None):
        """Обновить тест"""
        for field, value in update_data.items():
            setattr(test, field, value)
        
        if tasks is not None:
            test.tasks = tasks
        
        await self.db.commit()
        # refresh() would expunge the lazy-loaded 'tasks' relationship,
        # causing greenlet_spawn errors during Pydantic serialization.
        # Re-fetch with joinedload instead for a clean, fully-loaded object.
        return await self.get_test_with_tasks(test.id)

    async def delete_test_cascade(self, test_id: int):
        """Удалить тест и все связанные данные"""
        r = await self.db.execute(select(Test).where(Test.id == test_id))
        test = r.scalars().first()
        if not test:
            return None
        
        try:
            # 1. Сначала удаляем ответы пользователей
            r = await self.db.execute(
                select(TestResult.id).where(TestResult.test_id == test_id)
            )
            result_ids = [row[0] for row in r.all()]
            
            if result_ids:
                await self.db.execute(
                    delete(UserAnswer).where(UserAnswer.result_id.in_(result_ids))
                )
            
            # 2. Удаляем результаты
            await self.db.execute(
                delete(TestResult).where(TestResult.test_id == test_id)
            )
            
            # 3. Удаляем назначения
            await self.db.execute(
                delete(TestAssignment).where(TestAssignment.test_id == test_id)
            )
            
            # 4. Очищаем связи с задачами ПЕРЕД удалением теста
            test.tasks = []
            await self.db.flush()
            
            # 5. Удаляем сам тест
            await self.db.delete(test)
            await self.db.commit()
            return test
        except Exception as e:
            await self.db.rollback()
            raise e

    async def get_available_tests_meta(self):
        """Получить доступные тесты без загрузки заданий"""
        result = await self.db.execute(
            select(Test).options(
                joinedload(Test.tasks)
            ).where(
                Test.is_active == True,
                (Test.is_autocompile == True) | (Test.is_autocompile == None)
            )
        )
        return result.unique().scalars().all()

    async def check_test_owner(self, test_id: int, teacher_id: int):
        """Проверить владельца теста"""
        test = await self.get_test_by_id(test_id)
        if not test:
            return None
        if test.creator_id != teacher_id:
            return None
        return test

    async def calculate_test_max_points(self, test) -> int:
        """Вычислить максимальные баллы за тест"""
        if not test.tasks:
            return 0
        
        max_points = 0
        for task in test.tasks:
            if task.is_open_answer:
                max_points += 2
            else:
                if task.options and len(task.options) >= 2:
                    max_points += 1
                else:
                    max_points += 2
        return max_points
    
    async def get_ai_tests_by_user(self, user_id: int):
        """Получить AI-тесты, созданные пользователем"""
        result = await self.db.execute(
            select(Test).where(
                Test.creator_id == user_id,
                Test.is_ai_generated == True
            ).order_by(Test.id.desc())
        )
        return result.scalars().all()

    async def get_test_ids_by_creator(self, creator_id: int) -> List[int]:
        """Получить IDs всех тестов создателя"""
        r = await self.db.execute(
            select(Test.id).where(Test.creator_id == creator_id)
        )
        return [row[0] for row in r.all()]

    async def delete_tests_by_ids(self, test_ids: List[int]):
        """Удалить тесты по IDs"""
        r = await self.db.execute(
            select(TestResult.id).where(TestResult.test_id.in_(test_ids))
        )
        result_ids = [row[0] for row in r.all()]
        if result_ids:
            await self.db.execute(
                delete(UserAnswer).where(UserAnswer.result_id.in_(result_ids))
            )
            await self.db.execute(
                delete(TestResult).where(TestResult.id.in_(result_ids))
            )
        await self.db.execute(
            delete(TestTaskAssociation).where(TestTaskAssociation.test_id.in_(test_ids))
        )
        await self.db.execute(
            delete(TestAssignment).where(TestAssignment.test_id.in_(test_ids))
        )
        await self.db.execute(
            delete(Test).where(Test.id.in_(test_ids))
        )
