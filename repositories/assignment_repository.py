from sqlalchemy.orm import Session
import models
from datetime import datetime
from sqlalchemy import func  # <-- ДОБАВИТЬ ЭТУ СТРОКУы

class AssignmentRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_user_assignments(self, user_id: int):
        return self.db.query(models.TestAssignment)\
            .filter(models.TestAssignment.user_id == user_id)\
            .order_by(models.TestAssignment.assigned_at.desc())\
            .all()
    
    def get_assignment(self, test_id: int, user_id: int):
        return self.db.query(models.TestAssignment)\
            .filter(
                models.TestAssignment.test_id == test_id,
                models.TestAssignment.user_id == user_id,
                models.TestAssignment.is_completed == False
            ).first()
    
    def check_deadline(self, assignment) -> bool:
        if assignment.due_date and assignment.due_date < datetime.utcnow():
            return False
        return True
    
    def get_test_assignments(self, test_id: int):
        """Получить все назначения для теста"""
        return self.db.query(models.TestAssignment)\
            .filter(models.TestAssignment.test_id == test_id)\
            .order_by(models.TestAssignment.assigned_at.desc())\
            .all()

    def get_assignment_by_id(self, assignment_id: int):
        """Получить назначение по ID"""
        return self.db.query(models.TestAssignment)\
            .filter(models.TestAssignment.id == assignment_id)\
            .first()

    def check_existing_assignment(self, test_id: int, user_id: int):
        """Проверить дубликат назначения"""
        return self.db.query(models.TestAssignment)\
            .filter(
                models.TestAssignment.test_id == test_id,
                models.TestAssignment.user_id == user_id
            ).first()

    def create_assignment(self, test_id: int, user_id: int, 
                        due_date=None, group_id=None):
        """Создать одно назначение"""
        assignment = models.TestAssignment(
            test_id=test_id,
            user_id=user_id,
            due_date=due_date,
            group_id=group_id,
            assigned_at=datetime.utcnow()
        )
        self.db.add(assignment)
        return assignment

    def delete_assignment_by_obj(self, assignment):
        """Удалить назначение"""
        self.db.delete(assignment)
        self.db.commit()

    def get_latest_results_for_test(self, test_id: int):
        """Последние результаты всех студентов по тесту"""
        subq = self.db.query(
            models.TestResult.user_id,
            func.max(models.TestResult.completed_at).label('max_completed_at')
        ).filter(models.TestResult.test_id == test_id)\
        .group_by(models.TestResult.user_id).subquery()
        
        return self.db.query(models.TestResult).join(
            subq,
            (models.TestResult.user_id == subq.c.user_id) &
            (models.TestResult.completed_at == subq.c.max_completed_at)
        ).all()

    def get_latest_results_for_student(self, student_id: int):
        """Последние результаты студента по всем тестам"""
        subq = self.db.query(
            models.TestResult.test_id,
            func.max(models.TestResult.completed_at).label('max_completed_at')
        ).filter(models.TestResult.user_id == student_id)\
        .group_by(models.TestResult.test_id).subquery()
        
        return self.db.query(models.TestResult).join(
            subq,
            (models.TestResult.test_id == subq.c.test_id) &
            (models.TestResult.completed_at == subq.c.max_completed_at)
        ).all()