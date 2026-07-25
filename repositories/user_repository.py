from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from core.models import User, Task, TestResult, TestTaskAssociation
from core.auth import get_password_hash


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_id(self, user_id: int):
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

    async def get_all_users(self):
        result = await self.db.execute(select(User))
        return result.scalars().all()

    async def get_teachers_by_ids(self, teacher_ids: List[int]):
        result = await self.db.execute(select(User).where(User.id.in_(teacher_ids)))
        return result.scalars().all()

    async def get_users_by_ids(self, user_ids: List[int]):
        """Получить пользователей по списку ID"""
        result = await self.db.execute(select(User).where(User.id.in_(user_ids)))
        return result.scalars().all()

    async def get_user_by_email(self, email: str):
        result = await self.db.execute(select(User).where(User.username == email))
        return result.scalars().first()

    async def create_user(self, username: str, password: str, role: str,
                    first_name: str = None, last_name: str = None,
                    phone: str = None, tg_username: str = None):
        user = User(
            username=username,
            hashed_password=get_password_hash(password),
            role=role,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            tg_username=tg_username
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user(self, user: User, update_data: dict):
        for field, value in update_data.items():
            setattr(user, field, value)
        try:
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except Exception as e:
            await self.db.rollback()
            raise e

    async def update_user_role(self, user: User, new_role: str):
        user.role = new_role
        await self.db.commit()

    async def update_password(self, user: User, new_password: str):
        user.hashed_password = get_password_hash(new_password)
        await self.db.commit()

    async def delete_user(self, user: User):
        await self.db.delete(user)
        await self.db.commit()

    async def get_user_stats(self, user_id: int):
        task_points_expr = case(
            (Task.is_open_answer == True, 2),
            else_=1
        )

        test_max_points_sub = (
            select(
                TestTaskAssociation.test_id,
                func.sum(task_points_expr).label("max_total")
            )
            .join(Task, TestTaskAssociation.task_id == Task.id)
            .group_by(TestTaskAssociation.test_id)
            .subquery()
        )

        total_attempts_result = await self.db.execute(
            select(func.count()).select_from(TestResult).where(TestResult.user_id == user_id)
        )
        total_attempts = total_attempts_result.scalar()

        avg_percentage_result = await self.db.execute(
            select(
                func.avg(
                    (TestResult.total_points * 100.0) / test_max_points_sub.c.max_total
                )
            )
            .select_from(TestResult)
            .join(
                test_max_points_sub,
                TestResult.test_id == test_max_points_sub.c.test_id
            )
            .where(
                TestResult.user_id == user_id,
                test_max_points_sub.c.max_total > 0
            )
        )
        avg_percentage = avg_percentage_result.scalar() or 0

        return {
            "total_attempts": total_attempts,
            "avg_score": round(float(avg_percentage), 1)
        }