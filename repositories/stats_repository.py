from sqlalchemy.orm import Session
from sqlalchemy import func, case, distinct
import models
from datetime import datetime, timedelta
from typing import List, Optional

class StatsRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_user_results(self, user_id: int, start_date: Optional[datetime] = None):
        """Получить результаты пользователя за период"""
        query = self.db.query(models.TestResult).filter(
            models.TestResult.user_id == user_id
        )
        if start_date:
            query = query.filter(models.TestResult.completed_at >= start_date)
        return query.order_by(models.TestResult.completed_at.desc()).all()
    
    def get_unique_tasks_count(self, test_ids: List[int]) -> int:
        """Количество уникальных задач в тестах"""
        if not test_ids:
            return 0
        return self.db.query(
            func.count(distinct(models.TestTaskAssociation.task_id))
        ).filter(
            models.TestTaskAssociation.test_id.in_(test_ids)
        ).scalar() or 0
    
    def get_user_answers_by_results(self, result_ids: List[int]):
        """Получить ответы пользователя по ID результатов"""
        if not result_ids:
            return []
        return self.db.query(models.UserAnswer).filter(
            models.UserAnswer.result_id.in_(result_ids)
        ).all()
    
    def get_test_max_points(self, test_ids: List[int]) -> dict:
        """Получить максимальные баллы для тестов"""
        if not test_ids:
            return {}
        
        task_points_expr = case(
            (models.Task.is_open_answer == True, 2),
            else_=1
        )
        
        result = self.db.query(
            models.TestTaskAssociation.test_id,
            func.sum(task_points_expr).label("max_total")
        ).join(
            models.Task, models.TestTaskAssociation.task_id == models.Task.id
        ).filter(
            models.TestTaskAssociation.test_id.in_(test_ids)
        ).group_by(
            models.TestTaskAssociation.test_id
        ).all()
        
        return {test_id: max_total for test_id, max_total in result}
    
    def get_test_tasks(self, test_id: int) -> List[int]:
        """Получить ID задач теста"""
        tasks = self.db.query(models.TestTaskAssociation.task_id).filter(
            models.TestTaskAssociation.test_id == test_id
        ).all()
        return [t[0] for t in tasks]
    
    def get_topics_with_counts(self, test_ids: List[int]):
        """Получить темы/разделы с количеством уникальных задач"""
        if not test_ids:
            return []
        
        return self.db.query(
            models.Task.topic,
            models.Task.section,
            func.count(distinct(models.Task.id)).label("total_unique")
        ).join(
            models.TestTaskAssociation, models.Task.id == models.TestTaskAssociation.task_id
        ).filter(
            models.TestTaskAssociation.test_id.in_(test_ids)
        ).group_by(
            models.Task.topic,
            models.Task.section
        ).all()
    
    def get_difficulty_counts(self, test_ids: List[int]):
        """Получить сложность с количеством уникальных задач"""
        if not test_ids:
            return []
        
        return self.db.query(
            models.Task.difficulty,
            func.count(distinct(models.Task.id)).label("total_unique")
        ).join(
            models.TestTaskAssociation, models.Task.id == models.TestTaskAssociation.task_id
        ).filter(
            models.TestTaskAssociation.test_id.in_(test_ids)
        ).group_by(
            models.Task.difficulty
        ).all()
    
    def get_task_by_id(self, task_id: int):
        """Получить задачу по ID"""
        return self.db.query(models.Task).filter(models.Task.id == task_id).first()
    
    def get_user_by_id(self, user_id: int):
        """Получить пользователя по ID"""
        return self.db.query(models.User).filter(models.User.id == user_id).first()
    
    def check_teacher_student_link(self, teacher_id: int, student_id: int) -> bool:
        """Проверить связь учитель-ученик"""
        link = self.db.query(models.TeacherStudent).filter(
            models.TeacherStudent.teacher_id == teacher_id,
            models.TeacherStudent.student_id == student_id
        ).first()
        return link is not None