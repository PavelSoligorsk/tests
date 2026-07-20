from sqlalchemy.orm import Session
from sqlalchemy import func, case, distinct
from datetime import datetime, timedelta
from typing import List, Optional

from core.models import TestResult, TestTaskAssociation, UserAnswer, Task, User, TeacherStudent


class StatsRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_user_results(self, user_id: int, start_date: Optional[datetime] = None):
        """Получить результаты пользователя за период"""
        query = self.db.query(TestResult).filter(
            TestResult.user_id == user_id
        )
        if start_date:
            query = query.filter(TestResult.completed_at >= start_date)
        return query.order_by(TestResult.completed_at.desc()).all()
    
    def get_unique_tasks_count(self, test_ids: List[int]) -> int:
        """Количество уникальных задач в тестах"""
        if not test_ids:
            return 0
        return self.db.query(
            func.count(distinct(TestTaskAssociation.task_id))
        ).filter(
            TestTaskAssociation.test_id.in_(test_ids)
        ).scalar() or 0
    
    def get_user_answers_by_results(self, result_ids: List[int]):
        """Получить ответы пользователя по ID результатов"""
        if not result_ids:
            return []
        return self.db.query(UserAnswer).filter(
            UserAnswer.result_id.in_(result_ids)
        ).all()
    
    def get_test_max_points(self, test_ids: List[int]) -> dict:
        """Получить максимальные баллы для тестов"""
        if not test_ids:
            return {}
        
        task_points_expr = case(
            (Task.is_open_answer == True, 2),
            else_=1
        )
        
        result = self.db.query(
            TestTaskAssociation.test_id,
            func.sum(task_points_expr).label("max_total")
        ).join(
            Task, TestTaskAssociation.task_id == Task.id
        ).filter(
            TestTaskAssociation.test_id.in_(test_ids)
        ).group_by(
            TestTaskAssociation.test_id
        ).all()
        
        return {test_id: max_total for test_id, max_total in result}
    
    def get_test_tasks(self, test_id: int) -> List[int]:
        """Получить ID задач теста"""
        tasks = self.db.query(TestTaskAssociation.task_id).filter(
            TestTaskAssociation.test_id == test_id
        ).all()
        return [t[0] for t in tasks]
    
    def get_topics_with_counts(self, test_ids: List[int]):
        """Получить темы/разделы с количеством уникальных задач"""
        if not test_ids:
            return []
        
        return self.db.query(
            Task.topic,
            Task.section,
            func.count(distinct(Task.id)).label("total_unique")
        ).join(
            TestTaskAssociation, Task.id == TestTaskAssociation.task_id
        ).filter(
            TestTaskAssociation.test_id.in_(test_ids)
        ).group_by(
            Task.topic,
            Task.section
        ).all()
    
    def get_difficulty_counts(self, test_ids: List[int]):
        """Получить сложность с количеством уникальных задач"""
        if not test_ids:
            return []
        
        return self.db.query(
            Task.difficulty,
            func.count(distinct(Task.id)).label("total_unique")
        ).join(
            TestTaskAssociation, Task.id == TestTaskAssociation.task_id
        ).filter(
            TestTaskAssociation.test_id.in_(test_ids)
        ).group_by(
            Task.difficulty
        ).all()
    
    def get_task_by_id(self, task_id: int):
        """Получить задачу по ID"""
        return self.db.query(Task).filter(Task.id == task_id).first()
    
    def get_user_by_id(self, user_id: int):
        """Получить пользователя по ID"""
        return self.db.query(User).filter(User.id == user_id).first()
    
    def check_teacher_student_link(self, teacher_id: int, student_id: int) -> bool:
        """Проверить связь учитель-ученик"""
        link = self.db.query(TeacherStudent).filter(
            TeacherStudent.teacher_id == teacher_id,
            TeacherStudent.student_id == student_id
        ).first()
        return link is not None