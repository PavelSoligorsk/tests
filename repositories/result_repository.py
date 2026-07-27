from sqlalchemy import select, delete
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import datetime

from core.models import TestResult, UserAnswer, Task, Test


class ResultRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_result(self, test_id: int, user_id: int, total_points: int = 0):
        new_result = TestResult(
            test_id=test_id,
            user_id=user_id,
            total_points=total_points
        )
        self.db.add(new_result)
        await self.db.flush()
        return new_result
    
    async def save_answer(self, result_id: int, task_id: int, user_answer: str, is_correct: bool, points: int):
        answer = UserAnswer(
            result_id=result_id,
            task_id=task_id,
            user_text_answer=user_answer,
            is_correct=is_correct,
            points_earned=points
        )
        self.db.add(answer)
        return answer
    
    async def update_result_points(self, result_id: int, total_points: int):
        result = await self.get_result_by_id(result_id)
        if result:
            result.total_points = total_points
            result.completed_at = datetime.datetime.utcnow()
            await self.db.commit()
        return result
    
    async def get_result_by_id(self, result_id: int):
        """Получить результат со всеми необходимыми связями"""
        r = await self.db.execute(
            select(TestResult)
            .options(
                selectinload(TestResult.test).selectinload(Test.tasks),  # Загружаем тест и его задачи
                selectinload(TestResult.answers).selectinload(UserAnswer.task),  # Загружаем ответы и их задачи
                selectinload(TestResult.user)  # Загружаем пользователя
            )
            .where(TestResult.id == result_id)
        )
        return r.unique().scalars().first()
    
    async def get_user_history(self, user_id: int):
        r = await self.db.execute(
            select(TestResult)
            .options(joinedload(TestResult.test))
            .where(TestResult.user_id == user_id)
            .order_by(TestResult.completed_at.desc())
        )
        return r.unique().scalars().all()
    
    async def get_user_answers_for_result(self, result_id: int):
        r = await self.db.execute(
            select(UserAnswer).where(UserAnswer.result_id == result_id)
        )
        return r.scalars().all()
    
    async def get_user_results_for_topic(self, user_id: int, topic_number: int):
        r = await self.db.execute(
            select(TestResult).where(TestResult.user_id == user_id)
        )
        results = r.scalars().all()
        
        result_ids = [r_.id for r_ in results]
        
        if result_ids:
            r2 = await self.db.execute(
                select(UserAnswer)
                .join(Task)
                .where(
                    UserAnswer.result_id.in_(result_ids),
                    Task.topic_number == topic_number
                )
            )
            return r2.scalars().all()
        return []
    
    async def has_incomplete_attempt(self, user_id: int, test_id: int) -> bool:
        """Проверить, есть ли незавершённая попытка (result без completed_at)"""
        r = await self.db.execute(
            select(TestResult).where(
                TestResult.user_id == user_id,
                TestResult.test_id == test_id,
                TestResult.completed_at == None
            )
        )
        result = r.scalars().first()
        return result is not None

    async def get_incomplete_result(self, user_id: int, test_id: int):
        """Получить незавершённый TestResult (completed_at IS NULL)"""
        r = await self.db.execute(
            select(TestResult).options(
                selectinload(TestResult.test).selectinload(Test.tasks),
                selectinload(TestResult.answers),
            ).where(
                TestResult.user_id == user_id,
                TestResult.test_id == test_id,
                TestResult.completed_at == None
            )
        )
        return r.unique().scalars().first()

    async def get_incomplete_ai_results(self, user_id: int):
        """Получить все незавершённые TestResult для AI-тестов пользователя"""
        r = await self.db.execute(
            select(TestResult).options(
                selectinload(TestResult.test).selectinload(Test.tasks),
            ).join(Test, TestResult.test_id == Test.id).where(
                TestResult.user_id == user_id,
                TestResult.completed_at == None,
                Test.is_ai_generated == True,
                Test.is_active == True,
            ).order_by(TestResult.id.desc())
        )
        return r.unique().scalars().all()

    async def get_result_ids_by_user(self, user_id: int) -> List[int]:
        """Получить IDs всех результатов пользователя"""
        r = await self.db.execute(
            select(TestResult.id).where(TestResult.user_id == user_id)
        )
        return [row[0] for row in r.all()]

    async def delete_answers_by_result_ids(self, result_ids: List[int]):
        """Удалить ответы по IDs результатов"""
        await self.db.execute(
            delete(UserAnswer).where(UserAnswer.result_id.in_(result_ids))
        )

    async def delete_results_by_user(self, user_id: int):
        """Удалить все результаты пользователя"""
        await self.db.execute(
            delete(TestResult).where(TestResult.user_id == user_id)
        )
