from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from datetime import datetime

from core.models import Group, GroupStudent, TestAssignment, TeacherStudent, User


class GroupRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_group_by_id(self, group_id: int, teacher_id: Optional[int] = None):
        query = self.db.query(Group).options(
            joinedload(Group.students)
        ).filter(Group.id == group_id)
        
        if teacher_id:
            query = query.filter(Group.teacher_id == teacher_id)
        
        return query.first()
    
    def get_teacher_groups(self, teacher_id: int):
        return self.db.query(Group).options(
            joinedload(Group.students)
        ).filter(Group.teacher_id == teacher_id).all()
    
    def get_group_students(self, group_id: int) -> List[User]:
        group = self.get_group_by_id(group_id)
        return group.students if group else []
    
    def get_student_ids_by_group(self, group_id: int, teacher_id: int) -> List[int]:
        group = self.get_group_by_id(group_id, teacher_id)
        if not group:
            return []
        return [s.id for s in group.students]
    
    def remove_student(self, group: Group, student_id: int) -> bool:
        """Удалить студента из группы"""
        link = self.db.query(GroupStudent).filter(
            GroupStudent.group_id == group.id,
            GroupStudent.student_id == student_id
        ).first()
        
        if not link:
            return False
        
        self.db.delete(link)
        self.db.commit()
        return True
    
    def create_group(self, name: str, teacher_id: int, description: str = None):
        """Создать группу"""
        group = Group(
            name=name,
            description=description,
            teacher_id=teacher_id,
            created_at=datetime.utcnow()
        )
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "students_count": 0,
            "created_at": group.created_at,
            "students": []
        }

    def update_group(self, group: Group, name: str = None, description: str = None):
        """Обновить группу"""
        if name:
            group.name = name
        if description is not None:
            group.description = description
        
        self.db.commit()
        self.db.refresh(group)
        
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "students_count": len(group.students),
            "created_at": group.created_at
        }

    def delete_group(self, group: Group):
        """Удалить группу и все связи"""
        # Удаляем связи со студентами
        self.db.query(GroupStudent).filter(
            GroupStudent.group_id == group.id
        ).delete()
        
        # Удаляем назначения тестов
        self.db.query(TestAssignment).filter(
            TestAssignment.group_id == group.id
        ).delete()
        
        # Удаляем группу
        self.db.delete(group)
        self.db.commit()

    def add_students(self, group: Group, student_ids: List[int], teacher_id: int) -> int:
        """Добавить студентов в группу"""
        # Проверяем, что студенты принадлежат учителю
        teacher_students = self.db.query(TeacherStudent).filter(
            TeacherStudent.teacher_id == teacher_id,
            TeacherStudent.student_id.in_(student_ids)
        ).all()
        
        teacher_student_ids = {s.student_id for s in teacher_students}
        
        added = 0
        for student_id in student_ids:
            if student_id not in teacher_student_ids:
                continue
            
            existing = self.db.query(GroupStudent).filter(
                GroupStudent.group_id == group.id,
                GroupStudent.student_id == student_id
            ).first()
            
            if existing:
                continue
            
            self.db.add(GroupStudent(
                group_id=group.id,
                student_id=student_id
            ))
            added += 1
        
        self.db.commit()
        return added

    def get_group_by_name(self, name: str, teacher_id: int):
        """Найти группу по имени"""
        return self.db.query(Group).filter(
            Group.teacher_id == teacher_id,
            Group.name == name
        ).first()

    def delete_groups_by_teacher(self, teacher_id: int):
        """Удалить все группы учителя"""
        group_ids = self.db.query(Group.id).filter(
            Group.teacher_id == teacher_id
        ).all()
        group_ids = [g[0] for g in group_ids]
        
        if group_ids:
            self.db.query(GroupStudent).filter(
                GroupStudent.group_id.in_(group_ids)
            ).delete(synchronize_session=False)
            
            self.db.query(TestAssignment).filter(
                TestAssignment.group_id.in_(group_ids)
            ).update({"group_id": None}, synchronize_session=False)
            
            self.db.query(Group).filter(
                Group.teacher_id == teacher_id
            ).delete(synchronize_session=False)

    def delete_student_from_all_groups(self, student_id: int):
        """Удалить студента из всех групп"""
        self.db.query(GroupStudent).filter(
            GroupStudent.student_id == student_id
        ).delete(synchronize_session=False)