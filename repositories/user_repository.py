from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List

from core.models import User, Task, TestResult, TestTaskAssociation
from core.auth import get_password_hash


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).first()

    def get_all_users(self):
        return self.db.query(User).all()

    def get_teachers_by_ids(self, teacher_ids: List[int]):
        return self.db.query(User).filter(User.id.in_(teacher_ids)).all()

    def get_user_by_email(self, email: str):
        return self.db.query(User).filter(User.username == email).first()

    def create_user(self, username: str, password: str, role: str,
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
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user(self, user: User, update_data: dict):
        for field, value in update_data.items():
            setattr(user, field, value)
        try:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            return user
        except Exception as e:
            self.db.rollback()
            raise e

    def update_user_role(self, user: User, new_role: str):
        user.role = new_role
        self.db.commit()

    def update_password(self, user: User, new_password: str):
        user.hashed_password = get_password_hash(new_password)
        self.db.commit()

    def delete_user(self, user: User):
        self.db.delete(user)
        self.db.commit()

    def get_user_stats(self, user_id: int):
        task_points_expr = case(
            (Task.is_open_answer == True, 2),
            else_=1
        )

        test_max_points_sub = (
            self.db.query(
                TestTaskAssociation.test_id,
                func.sum(task_points_expr).label("max_total")
            )
            .join(Task, TestTaskAssociation.task_id == Task.id)
            .group_by(TestTaskAssociation.test_id)
            .subquery()
        )

        total_attempts = self.db.query(TestResult).filter(
            TestResult.user_id == user_id
        ).count()

        avg_percentage = self.db.query(
            func.avg(
                (TestResult.total_points * 100.0) / test_max_points_sub.c.max_total
            )
        ).join(
            test_max_points_sub,
            TestResult.test_id == test_max_points_sub.c.test_id
        ).filter(
            TestResult.user_id == user_id,
            test_max_points_sub.c.max_total > 0
        ).scalar() or 0

        return {
            "total_attempts": total_attempts,
            "avg_score": round(float(avg_percentage), 1)
        }