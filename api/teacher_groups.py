from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
import models, dto, auth
from database import get_db
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/teacher/groups", tags=["Teacher Groups"])

# Проверка, что пользователь — учитель
def check_teacher(user: models.User = Depends(auth.get_current_user)):
    if user.role not in ["teacher", "admin"]:
        raise HTTPException(status_code=403, detail="Требуется роль teacher или admin")
    return user


# ==================== CRUD ГРУПП ====================

@router.get("/")
def get_my_groups(
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить все группы учителя"""
    groups = db.query(models.Group).filter(
        models.Group.teacher_id == current_teacher.id
    ).order_by(models.Group.name).all()
    
    result = []
    for group in groups:
        result.append({
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "students_count": len(group.students),
            "created_at": group.created_at,
            "students": [
                {
                    "id": s.id,
                    "first_name": s.first_name,
                    "last_name": s.last_name,
                    "username": s.username,
                    "tg_username": s.tg_username
                }
                for s in group.students
            ]
        })
    
    return result


@router.post("/")
def create_group(
    payload: dict,  # {name: str, description: str | None}
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Создать новую группу"""
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название группы обязательно")
    
    # Проверяем уникальность названия у этого учителя
    existing = db.query(models.Group).filter(
        models.Group.teacher_id == current_teacher.id,
        models.Group.name == name
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Группа с таким названием уже существует")
    
    group = models.Group(
        name=name,
        description=payload.get("description"),
        teacher_id=current_teacher.id
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "students_count": 0,
        "created_at": group.created_at,
        "students": []
    }


@router.put("/{group_id}")
def update_group(
    group_id: int,
    payload: dict,  # {name: str, description: str | None}
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Обновить группу"""
    group = db.query(models.Group).filter(
        models.Group.id == group_id,
        models.Group.teacher_id == current_teacher.id
    ).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    
    name = payload.get("name", "").strip()
    if name:
        # Проверяем уникальность (исключая текущую группу)
        existing = db.query(models.Group).filter(
            models.Group.teacher_id == current_teacher.id,
            models.Group.name == name,
            models.Group.id != group_id
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Группа с таким названием уже существует")
        
        group.name = name
    
    if "description" in payload:
        group.description = payload.get("description")
    
    db.commit()
    db.refresh(group)
    
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "students_count": len(group.students),
        "created_at": group.created_at
    }


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Удалить группу (и все связи)"""
    group = db.query(models.Group).filter(
        models.Group.id == group_id,
        models.Group.teacher_id == current_teacher.id
    ).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    
    # Удаляем связи со студентами
    db.query(models.GroupStudent).filter(
        models.GroupStudent.group_id == group_id
    ).delete()
    
    # Удаляем назначения тестов для этой группы
    db.query(models.TestAssignment).filter(
        models.TestAssignment.group_id == group_id
    ).delete()
    
    # Удаляем саму группу
    db.delete(group)
    db.commit()
    
    return {"message": f"Группа '{group.name}' удалена"}


# ==================== УПРАВЛЕНИЕ СТУДЕНТАМИ В ГРУППЕ ====================

@router.post("/{group_id}/students")
def add_students_to_group(
    group_id: int,
    payload: dict,  # {student_ids: List[int]}
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Добавить студентов в группу"""
    group = db.query(models.Group).filter(
        models.Group.id == group_id,
        models.Group.teacher_id == current_teacher.id
    ).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    
    student_ids = payload.get("student_ids", [])
    if not student_ids:
        raise HTTPException(status_code=400, detail="Не указаны студенты")
    
    # Проверяем, что все студенты принадлежат учителю
    teacher_students = db.query(models.TeacherStudent).filter(
        models.TeacherStudent.teacher_id == current_teacher.id,
        models.TeacherStudent.student_id.in_(student_ids)
    ).all()
    
    teacher_student_ids = {s.student_id for s in teacher_students}
    
    added = 0
    for student_id in student_ids:
        if student_id not in teacher_student_ids:
            continue  # Пропускаем чужих студентов
        
        # Проверяем, нет ли уже в группе
        existing = db.query(models.GroupStudent).filter(
            models.GroupStudent.group_id == group_id,
            models.GroupStudent.student_id == student_id
        ).first()
        
        if existing:
            continue
        
        db.add(models.GroupStudent(
            group_id=group_id,
            student_id=student_id
        ))
        added += 1
    
    db.commit()
    
    return {
        "message": f"Добавлено {added} студентов в группу '{group.name}'",
        "added": added
    }


@router.delete("/{group_id}/students/{student_id}")
def remove_student_from_group(
    group_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Удалить студента из группы"""
    group = db.query(models.Group).filter(
        models.Group.id == group_id,
        models.Group.teacher_id == current_teacher.id
    ).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    
    link = db.query(models.GroupStudent).filter(
        models.GroupStudent.group_id == group_id,
        models.GroupStudent.student_id == student_id
    ).first()
    
    if not link:
        raise HTTPException(status_code=404, detail="Студент не в группе")
    
    db.delete(link)
    db.commit()
    
    return {"message": "Студент удалён из группы"}


@router.get("/{group_id}/students")
def get_group_students(
    group_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить список студентов группы"""
    group = db.query(models.Group).filter(
        models.Group.id == group_id,
        models.Group.teacher_id == current_teacher.id
    ).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    
    return [
        {
            "id": s.id,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "username": s.username,
            "tg_username": s.tg_username
        }
        for s in group.students
    ]