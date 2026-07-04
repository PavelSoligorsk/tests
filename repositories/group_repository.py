from sqlalchemy.orm import Session, joinedload
import models
from typing import Optional, List

class GroupRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_group_by_id(self, group_id: int, teacher_id: Optional[int] = None):
        query = self.db.query(models.Group).options(
            joinedload(models.Group.students)
        ).filter(models.Group.id == group_id)
        
        if teacher_id:
            query = query.filter(models.Group.teacher_id == teacher_id)
        
        return query.first()
    
    def get_teacher_groups(self, teacher_id: int):
        return self.db.query(models.Group).options(
            joinedload(models.Group.students)
        ).filter(models.Group.teacher_id == teacher_id).all()
    
    def get_group_students(self, group_id: int) -> List[models.User]:
        group = self.get_group_by_id(group_id)
        return group.students if group else []
    
    def get_student_ids_by_group(self, group_id: int, teacher_id: int) -> List[int]:
        group = self.get_group_by_id(group_id, teacher_id)
        if not group:
            return []
        return [s.id for s in group.students]