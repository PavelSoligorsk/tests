from sqlalchemy.orm import Session
import models
from typing import List

class TeacherStudentRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_teacher_students(self, teacher_id: int) -> List[models.User]:
        """Получить всех студентов учителя"""
        student_ids = self.db.query(models.TeacherStudent.student_id).filter(
            models.TeacherStudent.teacher_id == teacher_id
        ).subquery()
        
        return self.db.query(models.User).filter(
            models.User.role == "student",
            models.User.id.in_(student_ids)
        ).all()
    
    def check_student_belongs_to_teacher(self, student_id: int, teacher_id: int) -> bool:
        """Проверить, привязан ли студент к учителю"""
        link = self.db.query(models.TeacherStudent).filter(
            models.TeacherStudent.teacher_id == teacher_id,
            models.TeacherStudent.student_id == student_id
        ).first()
        return link is not None
    
    def check_students_belong_to_teacher(self, student_ids: List[int], teacher_id: int) -> List[int]:
        """Проверить список студентов и вернуть тех, кто НЕ принадлежит учителю"""
        assigned = self.db.query(models.TeacherStudent.student_id).filter(
            models.TeacherStudent.teacher_id == teacher_id,
            models.TeacherStudent.student_id.in_(student_ids)
        ).all()
        
        assigned_ids = {s[0] for s in assigned}
        return [uid for uid in student_ids if uid not in assigned_ids]
    
    def get_students_by_ids(self, student_ids: List[int]) -> List[models.User]:
        """Получить студентов по ID с проверкой роли"""
        return self.db.query(models.User).filter(
            models.User.id.in_(student_ids),
            models.User.role == "student"
        ).all()
    
    def get_student_by_id(self, student_id: int) -> models.User:
        """Получить студента по ID"""
        return self.db.query(models.User).filter(
            models.User.id == student_id,
            models.User.role == "student"
        ).first()
    
    def get_all_links(self):
        """Получить все связи учитель-ученик"""
        return self.db.query(models.TeacherStudent).all()

    def get_links_by_student_ids(self, student_ids: List[int]):
        """Получить связи для списка студентов"""
        return self.db.query(models.TeacherStudent).filter(
            models.TeacherStudent.student_id.in_(student_ids)
        ).all()

    def delete_links_by_user(self, user_id: int):
        """Удалить все связи где пользователь учитель или ученик"""
        self.db.query(models.TeacherStudent).filter(
            (models.TeacherStudent.teacher_id == user_id) |
            (models.TeacherStudent.student_id == user_id)
        ).delete(synchronize_session=False)

    def delete_link_by_student(self, student_id: int):
        """Удалить связь ученика с учителем"""
        link = self.db.query(models.TeacherStudent).filter(
            models.TeacherStudent.student_id == student_id
        ).first()
        if link:
            self.db.delete(link)
            return True
        return False

    def create_link(self, teacher_id: int, student_id: int):
        """Создать связь учитель-ученик"""
        # Удаляем старую связь
        self.db.query(models.TeacherStudent).filter(
            models.TeacherStudent.student_id == student_id
        ).delete()
        
        # Создаём новую
        new_link = models.TeacherStudent(
            teacher_id=teacher_id,
            student_id=student_id
        )
        self.db.add(new_link)
        return new_link