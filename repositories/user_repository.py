from sqlalchemy.orm import Session
from sqlalchemy import func, case
import models
from typing import List  # ← ДОБАВИТЬ В НАЧАЛО ФАЙЛА

class UserRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_user_by_id(self, user_id: int):
        return self.db.query(models.User).filter(models.User.id == user_id).first()
    
    def update_user(self, user: models.User, update_data: dict):
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
    
    def get_user_stats(self, user_id: int):
        task_points_expr = case(
            (models.Task.is_open_answer == True, 2),
            else_=1
        )
        
        test_max_points_sub = (
            self.db.query(
                models.TestTaskAssociation.test_id,
                func.sum(task_points_expr).label("max_total")
            )
            .join(models.Task, models.TestTaskAssociation.task_id == models.Task.id)
            .group_by(models.TestTaskAssociation.test_id)
            .subquery()
        )
        
        total_attempts = self.db.query(models.TestResult).filter(
            models.TestResult.user_id == user_id
        ).count()
        
        avg_percentage = self.db.query(
            func.avg(
                (models.TestResult.total_points * 100.0) / test_max_points_sub.c.max_total
            )
        ).join(
            test_max_points_sub,
            models.TestResult.test_id == test_max_points_sub.c.test_id
        ).filter(
            models.TestResult.user_id == user_id,
            test_max_points_sub.c.max_total > 0
        ).scalar() or 0
        
        return {
            "total_attempts": total_attempts,
            "avg_score": round(float(avg_percentage), 1)
        }
    
    def get_all_users(self):
        """Получить всех пользователей"""
        return self.db.query(models.User).all()

    def get_user_by_id(self, user_id: int):
        """Получить пользователя по ID"""
        return self.db.query(models.User).filter(models.User.id == user_id).first()

    def get_teachers_by_ids(self, teacher_ids: List[int]):
        """Получить учителей по ID"""
        return self.db.query(models.User).filter(
            models.User.id.in_(teacher_ids)
        ).all()

    def update_user_role(self, user: models.User, new_role: str):
        """Обновить роль пользователя"""
        user.role = new_role
        self.db.commit()

    def delete_user(self, user: models.User):
        """Удалить пользователя"""
        self.db.delete(user)
        self.db.commit()

    def get_user_by_email(self, email: str):
        """Найти пользователя по email (username)"""
        return self.db.query(models.User).filter(
            models.User.username == email
        ).first()