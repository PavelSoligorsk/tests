from sqlalchemy import select, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from core.models import User, TeacherStudent


class TeacherStudentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_teacher_students(self, teacher_id: int) -> List[User]:
        """Получить всех студентов учителя"""
        r = await self.db.execute(
            select(TeacherStudent.student_id).where(TeacherStudent.teacher_id == teacher_id)
        )
        student_ids_sub = r.all()
        student_ids = [s[0] for s in student_ids_sub]
        
        if not student_ids:
            return []
        
        r2 = await self.db.execute(
            select(User).where(
                User.role == "student",
                User.id.in_(student_ids)
            )
        )
        return r2.scalars().all()
    
    async def check_student_belongs_to_teacher(self, student_id: int, teacher_id: int) -> bool:
        """Проверить, привязан ли студент к учителю"""
        r = await self.db.execute(
            select(TeacherStudent).where(
                TeacherStudent.teacher_id == teacher_id,
                TeacherStudent.student_id == student_id
            )
        )
        link = r.scalars().first()
        return link is not None
    
    async def check_students_belong_to_teacher(self, student_ids: List[int], teacher_id: int) -> List[int]:
        """Проверить список студентов и вернуть тех, кто НЕ принадлежит учителю"""
        r = await self.db.execute(
            select(TeacherStudent.student_id).where(
                TeacherStudent.teacher_id == teacher_id,
                TeacherStudent.student_id.in_(student_ids)
            )
        )
        assigned = r.all()
        
        assigned_ids = {s[0] for s in assigned}
        return [uid for uid in student_ids if uid not in assigned_ids]
    
    async def get_students_by_ids(self, student_ids: List[int]) -> List[User]:
        """Получить студентов по ID с проверкой роли"""
        r = await self.db.execute(
            select(User).where(
                User.id.in_(student_ids),
                User.role == "student"
            )
        )
        return r.scalars().all()
    
    async def get_student_by_id(self, student_id: int) -> User:
        """Получить студента по ID"""
        r = await self.db.execute(
            select(User).where(
                User.id == student_id,
                User.role == "student"
            )
        )
        return r.scalars().first()
    
    async def get_all_links(self):
        """Получить все связи учитель-ученик"""
        r = await self.db.execute(select(TeacherStudent))
        return r.scalars().all()

    async def get_links_by_student_ids(self, student_ids: List[int]):
        """Получить связи для списка студентов"""
        r = await self.db.execute(
            select(TeacherStudent).where(TeacherStudent.student_id.in_(student_ids))
        )
        return r.scalars().all()

    async def delete_links_by_user(self, user_id: int):
        """Удалить все связи где пользователь учитель или ученик"""
        await self.db.execute(
            delete(TeacherStudent).where(
                or_(
                    TeacherStudent.teacher_id == user_id,
                    TeacherStudent.student_id == user_id
                )
            )
        )

    async def delete_link_by_student(self, student_id: int):
        """Удалить связь ученика с учителем"""
        r = await self.db.execute(
            select(TeacherStudent).where(TeacherStudent.student_id == student_id)
        )
        link = r.scalars().first()
        if link:
            await self.db.delete(link)
            return True
        return False

    async def create_link(self, teacher_id: int, student_id: int):
        """Создать связь учитель-ученик"""
        # Удаляем старую связь
        await self.db.execute(
            delete(TeacherStudent).where(TeacherStudent.student_id == student_id)
        )
        
        # Создаём новую
        new_link = TeacherStudent(
            teacher_id=teacher_id,
            student_id=student_id
        )
        self.db.add(new_link)
        return new_link