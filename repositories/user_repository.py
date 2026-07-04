from sqlalchemy.orm import Session
from sqlalchemy import func, case
import models

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