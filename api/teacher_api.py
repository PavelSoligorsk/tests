from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import models, dto, auth
from database import get_db
from services.teacher_service import TeacherService, PermissionError

router = APIRouter(prefix="/teacher", tags=["Teacher API"])


def check_teacher(user: models.User = Depends(auth.get_current_user)):
    """Проверяет, что пользователь — учитель или админ"""
    if user.role not in ["teacher", "admin"]:
        raise HTTPException(status_code=403, detail="Доступ запрещён. Требуется роль teacher или admin")
    return user


def get_teacher_service(db: Session = Depends(get_db)) -> TeacherService:
    return TeacherService(db)


# ==================== БАНК ЗАДАНИЙ ====================

@router.get("/tasks", response_model=List[dto.TaskResponse])
def get_all_tasks(
    task_class: Optional[int] = Query(None),
    topic: Optional[str] = Query(None),
    topic_number: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    return service.get_tasks(task_class, topic, topic_number, section)


@router.get("/tasks-grouped")
def get_tasks_grouped(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    return service.get_tasks_grouped()


@router.get("/tasks/{task_id}", response_model=dto.TaskResponse)
def get_single_task(
    task_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.get_task_by_id(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== КОНСТРУКТОР ТЕСТОВ ====================

@router.get("/tests", response_model=List[dto.TestResponse])
def get_teacher_tests(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    return service.get_tests(current_teacher.id, current_teacher.role)


@router.post("/tests", response_model=dto.TestResponse)
def create_test(
    payload: dto.TestCreate,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.create_test(
            title=payload.title,
            creator_id=current_teacher.id,
            target_class=payload.target_class,
            target_topic=payload.target_topic,
            is_autocompile=payload.is_autocompile,
            task_ids=payload.task_ids
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/tests/{test_id}", response_model=dto.TestResponse)
def update_test(
    test_id: int,
    payload: dto.TestCreate,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.update_test(
            test_id=test_id,
            teacher_id=current_teacher.id,
            title=payload.title,
            target_class=payload.target_class,
            target_topic=payload.target_topic,
            is_autocompile=payload.is_autocompile,
            task_ids=payload.task_ids
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/tests/{test_id}")
def delete_test(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.delete_test(test_id, current_teacher.id, current_teacher.role)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tests/{test_id}", response_model=dto.TestResponse)
def get_test_detail(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.get_test_detail(test_id, current_teacher.id, current_teacher.role)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== РЕЗУЛЬТАТЫ УЧЕНИКОВ ====================

@router.get("/students")
def get_my_students(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    return service.get_my_students(current_teacher.id)


@router.get("/students-profile/{user_id}")
def get_student_profile(
    user_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.get_student_profile(user_id, current_teacher.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/students-history/{user_id}")
def get_student_history(
    user_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.get_student_history(user_id, current_teacher.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/results/{result_id}")
def get_teacher_detailed_result(
    result_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.get_detailed_result(result_id, current_teacher.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== НАЗНАЧЕНИЕ ТЕСТОВ ====================

@router.post("/assign-test")
def assign_test_to_students(
    assignment: dto.TestAssignmentCreate,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.assign_test(
            test_id=assignment.test_id,
            teacher_id=current_teacher.id,
            user_ids=assignment.user_ids,
            due_date=assignment.due_date,
            role=current_teacher.role
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/test/{test_id}/assignments")
def get_test_assignments(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.get_test_assignments(test_id, current_teacher.id, current_teacher.role)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/student/{student_id}/assignments")
def get_student_assignments(
    student_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.get_student_assignments(student_id, current_teacher.id, current_teacher.role)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.delete_assignment(assignment_id, current_teacher.id, current_teacher.role)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/assign-test-to-group")
def assign_test_to_group(
    assignment: dto.TestGroupAssignment,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    try:
        return service.assign_test_to_group(
            group_id=assignment.group_id,
            test_id=assignment.test_id,
            teacher_id=current_teacher.id,
            due_date=assignment.due_date,
            role=current_teacher.role
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
# ==================== УПРАВЛЕНИЕ ГРУППАМИ ====================

@router.get("/groups/")
def get_my_groups(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить все группы учителя"""
    return service.get_my_groups(current_teacher.id)


@router.post("/groups/")
def create_group(
    payload: dict,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Создать новую группу"""
    try:
        return service.create_group(
            name=payload.get("name", "").strip(),
            description=payload.get("description"),
            teacher_id=current_teacher.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/groups/{group_id}")
def update_group(
    group_id: int,
    payload: dict,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Обновить группу"""
    try:
        return service.update_group(
            group_id=group_id,
            teacher_id=current_teacher.id,
            name=payload.get("name", "").strip(),
            description=payload.get("description")
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/groups/{group_id}")
def delete_group(
    group_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Удалить группу"""
    try:
        return service.delete_group(group_id, current_teacher.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/groups/{group_id}/students")
def add_students_to_group(
    group_id: int,
    payload: dict,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Добавить студентов в группу"""
    try:
        return service.add_students_to_group(
            group_id=group_id,
            teacher_id=current_teacher.id,
            student_ids=payload.get("student_ids", [])
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/groups/{group_id}/students/{student_id}")
def remove_student_from_group(
    group_id: int,
    student_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Удалить студента из группы"""
    try:
        return service.remove_student_from_group(group_id, student_id, current_teacher.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/groups/{group_id}/students")
def get_group_students(
    group_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить список студентов группы"""
    try:
        return service.get_group_students(group_id, current_teacher.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
@router.get("/tasks/by-topic/{topic}/section/{section}")
def get_tasks_by_topic_section(
    topic: str,
    section: str,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить задания по теме и разделу (ленивая загрузка)"""
    return service.get_tasks_by_topic_section(topic, section)


@router.get("/tests/{test_id}/tasks")
def get_test_tasks(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить только задания теста (без метаинформации)"""
    try:
        return service.get_test_tasks(test_id, current_teacher.id, current_teacher.role)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@router.get("/tasks-meta")
def get_tasks_meta(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить только структуру заданий (классы, темы, разделы) без содержимого"""
    return service.get_tasks_meta()

@router.get("/tasks/by-class/{task_class}/topic/{topic_number}")
def get_tasks_by_class_and_topic(
    task_class: str,
    topic_number: str,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить задания по классу и номеру темы"""
    return service.get_tasks_by_class_and_topic(task_class, topic_number)