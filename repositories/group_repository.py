from sqlalchemy import select, delete, update
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime

from core.models import Group, GroupStudent, TestAssignment, TeacherStudent, User


class GroupRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_group_by_id(self, group_id: int, teacher_id: Optional[int] = None):
        stmt = select(Group).options(
            joinedload(Group.students)
        ).where(Group.id == group_id)
        
        if teacher_id:
            stmt = stmt.where(Group.teacher_id == teacher_id)
        
        r = await self.db.execute(stmt)
        return r.unique().scalars().first()
    
    async def get_teacher_groups(self, teacher_id: int):
        r = await self.db.execute(
            select(Group).options(
                joinedload(Group.students)
            ).where(Group.teacher_id == teacher_id)
        )
        return r.unique().scalars().all()
    
    async def get_group_students(self, group_id: int) -> List[User]:
        group = await self.get_group_by_id(group_id)
        return group.students if group else []
    
    async def get_student_ids_by_group(self, group_id: int, teacher_id: int) -> List[int]:
        group = await self.get_group_by_id(group_id, teacher_id)
        if not group:
            return []
        return [s.id for s in group.students]
    
    async def remove_student(self, group: Group, student_id: int) -> bool:
        """Удалить студента из группы"""
        r = await self.db.execute(
            select(GroupStudent).where(
                GroupStudent.group_id == group.id,
                GroupStudent.student_id == student_id
            )
        )
        link = r.scalars().first()
        
        if not link:
            return False
        
        await self.db.delete(link)
        await self.db.commit()
        return True
    
    async def create_group(self, name: str, teacher_id: int, description: str = None):
        """Создать группу"""
        group = Group(
            name=name,
            description=description,
            teacher_id=teacher_id,
            created_at=datetime.utcnow()
        )
        self.db.add(group)
        await self.db.commit()
        # expire_on_commit=False preserves object state; refresh() is unnecessary
        
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "students_count": 0,
            "created_at": group.created_at,
            "students": []
        }

    async def update_group(self, group: Group, name: str = None, description: str = None):
        """Обновить группу"""
        if name:
            group.name = name
        if description is not None:
            group.description = description
        
        await self.db.commit()
        # expire_on_commit=False preserves object state; refresh() is unnecessary
        
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "students_count": len(group.students),
            "created_at": group.created_at
        }

    async def delete_group(self, group: Group):
        """Удалить группу и все связи"""
        # Удаляем связи со студентами
        await self.db.execute(
            delete(GroupStudent).where(GroupStudent.group_id == group.id)
        )
        
        # Удаляем назначения тестов
        await self.db.execute(
            delete(TestAssignment).where(TestAssignment.group_id == group.id)
        )
        
        # Удаляем группу
        await self.db.delete(group)
        await self.db.commit()

    async def add_students(self, group: Group, student_ids: List[int], teacher_id: int) -> int:
        """Добавить студентов в группу"""
        # Проверяем, что студенты принадлежат учителю
        r = await self.db.execute(
            select(TeacherStudent).where(
                TeacherStudent.teacher_id == teacher_id,
                TeacherStudent.student_id.in_(student_ids)
            )
        )
        teacher_students = r.scalars().all()
        
        teacher_student_ids = {s.student_id for s in teacher_students}
        
        added = 0
        for student_id in student_ids:
            if student_id not in teacher_student_ids:
                continue
            
            r2 = await self.db.execute(
                select(GroupStudent).where(
                    GroupStudent.group_id == group.id,
                    GroupStudent.student_id == student_id
                )
            )
            existing = r2.scalars().first()
            
            if existing:
                continue
            
            self.db.add(GroupStudent(
                group_id=group.id,
                student_id=student_id
            ))
            added += 1
        
        await self.db.commit()
        return added

    async def get_group_by_name(self, name: str, teacher_id: int):
        """Найти группу по имени"""
        r = await self.db.execute(
            select(Group).where(
                Group.teacher_id == teacher_id,
                Group.name == name
            )
        )
        return r.scalars().first()

    async def delete_groups_by_teacher(self, teacher_id: int):
        """Удалить все группы учителя"""
        r = await self.db.execute(
            select(Group.id).where(Group.teacher_id == teacher_id)
        )
        group_ids = [g[0] for g in r.all()]
        
        if group_ids:
            await self.db.execute(
                delete(GroupStudent).where(GroupStudent.group_id.in_(group_ids))
            )
            
            await self.db.execute(
                update(TestAssignment).where(TestAssignment.group_id.in_(group_ids)).values(group_id=None)
            )
            
            await self.db.execute(
                delete(Group).where(Group.teacher_id == teacher_id)
            )

    async def delete_student_from_all_groups(self, student_id: int):
        """Удалить студента из всех групп"""
        await self.db.execute(
            delete(GroupStudent).where(GroupStudent.student_id == student_id)
        )