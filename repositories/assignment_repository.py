from sqlalchemy.orm import Session
import models
from datetime import datetime

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