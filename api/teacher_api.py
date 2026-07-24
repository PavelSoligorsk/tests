from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from core.models import User
from dto_schemas import (
    TaskResponse, TestResponse, TestCreate,
    TestAssignmentCreate, TestGroupAssignment,
    TaskGroupedResponse, TaskClassTopicMetaResponse,
    TopicSectionMetaResponse, TeacherAssignmentItemResponse,
    TeacherGroupResponse, DetailedResultResponse, UserResponse,
    GroupCreateRequest, GroupUpdateRequest, AddStudentsToGroupRequest,
    TeacherStudentProfileResponse, TeacherHistoryItemResponse,
    GroupAssignResponse, AddStudentsToGroupResponse, MessageResponse,
)
from core import auth
from core.database import get_db
from services.teacher_service import TeacherService, PermissionError
from core.cache import cache_result, invalidate_user_cache, invalidate_cache_pattern

router = APIRouter(prefix="/teacher", tags=["Teacher API"])


def check_teacher(user: User = Depends(auth.get_current_user)):
    """Проверяет, что пользователь — учитель или админ"""
    if user.role not in ["teacher", "admin"]:
        raise HTTPException(status_code=403, detail="Доступ запрещён. Требуется роль teacher или admin")
    return user


def get_teacher_service(db: Session = Depends(get_db)) -> TeacherService:
    return TeacherService(db)


# ==================== БАНК ЗАДАНИЙ ====================

@router.get("/tasks", response_model=List[TaskResponse])
def get_all_tasks(
    task_class: Optional[int] = Query(None),
    topic: Optional[str] = Query(None),
    topic_number: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить все задания с фильтрацией"""
    # Глобальный кеш с учетом параметров фильтрации
    return cache_result(
        "teacher_tasks",
        None,  # Глобальный кеш для всех учителей
        lambda: service.get_tasks(task_class, topic, topic_number, section),
        model_class=TaskResponse,
        ttl=3600,  # 1 час - задания меняются редко
        task_class=task_class,
        topic=topic,
        topic_number=topic_number,
        section=section
    )


@router.get("/tasks-grouped", response_model=TaskGroupedResponse)
def get_tasks_grouped(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить задания сгруппированные по классам и темам"""
    return cache_result(
        "teacher_tasks_grouped",
        None,
        lambda: service.get_tasks_grouped(),
        model_class=TaskGroupedResponse,
        ttl=3600
    )


@router.get("/tasks/by-class-topic")
def get_tasks_by_class_and_topic_query(
    task_class: str = Query(...),
    topic_number: str = Query(...),
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить задания по классу и номеру темы (query-параметры)"""
    return cache_result(
        "teacher_tasks_by_class_topic",
        None,
        lambda: service.get_tasks_by_class_and_topic(task_class, topic_number),
        model_class=TaskResponse,
        ttl=3600,
        task_class=task_class,
        topic_number=topic_number
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_single_task(
    task_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить одно задание по ID"""
    try:
        return cache_result(
            "teacher_task_detail",
            None,
            lambda: service.get_task_by_id(task_id),
            model_class=TaskResponse,
            ttl=3600,
            entity_id=task_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/tasks/by-topic/{topic}/section/{section}")
def get_tasks_by_topic_section(
    topic: str,
    section: str,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить задания по теме и разделу (ленивая загрузка)"""
    return cache_result(
        "teacher_tasks_by_topic_section",
        None,
        lambda: service.get_tasks_by_topic_section(topic, section),
        model_class=TaskResponse,
        ttl=3600,
        topic=topic,
        section=section
    )


@router.get("/tasks-meta")
def get_tasks_meta(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить только структуру заданий (классы, темы, разделы) без содержимого"""
    return cache_result(
        "teacher_tasks_meta",
        None,
        lambda: service.get_tasks_meta(),
        model_class=TaskClassTopicMetaResponse,
        ttl=7200  # 2 часа - структура меняется очень редко
    )


@router.get("/tasks/by-class/")
def get_tasks_by_class_and_topic(
    task_class: str = Query(...),
    topic_number: str = Query(...),
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить задания по классу и номеру темы"""
    return cache_result(
        "teacher_tasks_by_class",
        None,
        lambda: service.get_tasks_by_class_and_topic(task_class, topic_number),
        model_class=TaskResponse,
        ttl=3600,
        task_class=task_class,
        topic_number=topic_number
    )


@router.get("/tasks-meta-by-topic-section")
def get_tasks_meta_by_topic_section(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить структуру: { topic: { section: count } }"""
    return cache_result(
        "teacher_tasks_meta_by_topic_section",
        None,
        lambda: service.get_tasks_meta_by_topic_section(),
        model_class=TopicSectionMetaResponse,
        ttl=7200
    )


# ==================== КОНСТРУКТОР ТЕСТОВ ====================

@router.get("/tests", response_model=List[TestResponse])
def get_teacher_tests(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить все тесты учителя"""
    return cache_result(
        "teacher_tests",
        current_teacher.id,  # Персональный кеш для каждого учителя
        lambda: service.get_tests(current_teacher.id, current_teacher.role),
        model_class=TestResponse,
        ttl=300  # 5 минут - тесты могут часто меняться
    )


@router.post("/tests", response_model=TestResponse)
def create_test(
    payload: TestCreate,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Создать новый тест"""
    try:
        result = service.create_test(
            title=payload.title,
            creator_id=current_teacher.id,
            target_class=payload.target_class,
            target_topic=payload.target_topic,
            is_autocompile=payload.is_autocompile,
            task_ids=payload.task_ids
        )
        
        # Инвалидируем кеш тестов учителя
        invalidate_user_cache(current_teacher.id, "teacher_tests")
        # Инвалидируем глобальный кеш тестов для студентов
        invalidate_cache_pattern("available_tests")
        invalidate_cache_pattern("available_tests:*")
        invalidate_cache_pattern("tests_meta")
        invalidate_cache_pattern("tests_meta:*")
        
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/tests/{test_id}", response_model=TestResponse)
def update_test(
    test_id: int,
    payload: TestCreate,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Обновить тест"""
    try:
        result = service.update_test(
            test_id=test_id,
            teacher_id=current_teacher.id,
            title=payload.title,
            target_class=payload.target_class,
            target_topic=payload.target_topic,
            is_autocompile=payload.is_autocompile,
            task_ids=payload.task_ids
        )
        
        # Инвалидируем кеш
        invalidate_user_cache(current_teacher.id, "teacher_tests")
        invalidate_cache_pattern(f"teacher_test_detail:{current_teacher.id}:{test_id}")
        invalidate_cache_pattern(f"teacher_test_tasks:{current_teacher.id}:{test_id}")
        invalidate_cache_pattern(f"test_details:{test_id}")
        invalidate_cache_pattern("available_tests:*")
        invalidate_cache_pattern("available_tests")
        invalidate_cache_pattern("tests_meta")
        invalidate_cache_pattern("tests_meta:*")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/tests/{test_id}", response_model=MessageResponse)
def delete_test(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Удалить тест"""
    try:
        result = service.delete_test(test_id, current_teacher.id, current_teacher.role)
        
        # Инвалидируем кеш
        invalidate_user_cache(current_teacher.id, "teacher_tests")
        invalidate_cache_pattern(f"teacher_test_detail:{current_teacher.id}:{test_id}")
        invalidate_cache_pattern(f"teacher_test_tasks:{current_teacher.id}:{test_id}")
        invalidate_cache_pattern(f"test_details:{test_id}")
        invalidate_cache_pattern("available_tests:*")
        invalidate_cache_pattern("available_tests")
        invalidate_cache_pattern("tests_meta")
        invalidate_cache_pattern("tests_meta:*")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tests/{test_id}", response_model=TestResponse)
def get_test_detail(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить детали теста"""
    try:
        return cache_result(
            "teacher_test_detail",
            current_teacher.id,  # Персональный кеш
            lambda: service.get_test_detail(test_id, current_teacher.id, current_teacher.role),
            model_class=TestResponse,
            ttl=300,
            entity_id=test_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/tests/{test_id}/tasks")
def get_test_tasks(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить только задания теста (без метаинформации)"""
    try:
        return cache_result(
            "teacher_test_tasks",
            current_teacher.id,
            lambda: service.get_test_tasks(test_id, current_teacher.id, current_teacher.role),
            model_class=TaskResponse,
            ttl=300,
            entity_id=test_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== РЕЗУЛЬТАТЫ УЧЕНИКОВ ====================

@router.get("/students")
def get_my_students(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить список своих учеников"""
    return cache_result(
        "teacher_students",
        current_teacher.id,
        lambda: service.get_my_students(current_teacher.id),
        model_class=UserResponse,
        ttl=600  # 10 минут - студенты могут добавляться
    )


@router.get("/students-profile/{user_id}", response_model=TeacherStudentProfileResponse)
def get_student_profile(
    user_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить профиль ученика"""
    try:
        return service.get_student_profile(user_id, current_teacher.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/students-history/{user_id}", response_model=list[TeacherHistoryItemResponse])
def get_student_history(
    user_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить историю ученика"""
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
    current_teacher: User = Depends(check_teacher)
):
    """Получить детальный результат"""
    try:
        return cache_result(
            "teacher_result_detail",
            current_teacher.id,
            lambda: service.get_detailed_result(result_id, current_teacher.id),
            model_class=DetailedResultResponse,
            ttl=600,
            entity_id=result_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== НАЗНАЧЕНИЕ ТЕСТОВ ====================

@router.post("/assign-test", response_model=list[TeacherAssignmentItemResponse])
def assign_test_to_students(
    assignment: TestAssignmentCreate,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Назначить тест студентам"""
    try:
        result = service.assign_test(
            test_id=assignment.test_id,
            teacher_id=current_teacher.id,
            user_ids=assignment.user_ids,
            due_date=assignment.due_date,
            role=current_teacher.role
        )
        
        # Инвалидируем кеш
        invalidate_user_cache(current_teacher.id, 
            "teacher_test_assignments",
            "teacher_students"
        )
        # Инвалидируем кеш студентов
        for user_id in assignment.user_ids:
            invalidate_user_cache(user_id, 
                "my_assignments",
                "my_assignments_meta"
            )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/test/{test_id}/assignments")
def get_test_assignments(
    test_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить назначения теста"""
    try:
        return cache_result(
            "teacher_test_assignments",
            current_teacher.id,
            lambda: service.get_test_assignments(test_id, current_teacher.id, current_teacher.role),
            model_class=TeacherAssignmentItemResponse,
            ttl=300,
            entity_id=test_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/student/{student_id}/assignments")
def get_student_assignments(
    student_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить назначения студента"""
    try:
        return cache_result(
            "teacher_student_assignments",
            current_teacher.id,
            lambda: service.get_student_assignments(student_id, current_teacher.id, current_teacher.role),
            model_class=TeacherAssignmentItemResponse,
            ttl=300,
            entity_id=student_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/assignments/{assignment_id}", response_model=MessageResponse)
def delete_assignment(
    assignment_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Удалить назначение"""
    try:
        result = service.delete_assignment(assignment_id, current_teacher.id, current_teacher.role)
        
        # Инвалидируем кеш
        invalidate_user_cache(current_teacher.id,
            "teacher_test_assignments",
            "teacher_student_assignments"
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/assign-test-to-group", response_model=GroupAssignResponse)
def assign_test_to_group(
    assignment: TestGroupAssignment,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Назначить тест группе"""
    try:
        result = service.assign_test_to_group(
            group_id=assignment.group_id,
            test_id=assignment.test_id,
            teacher_id=current_teacher.id,
            due_date=assignment.due_date,
            role=current_teacher.role
        )
        
        # Инвалидируем кеш
        invalidate_user_cache(current_teacher.id,
            "teacher_test_assignments",
            "teacher_students",
            "teacher_groups"
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== УПРАВЛЕНИЕ ГРУППАМИ ====================

@router.get("/groups/")
def get_my_groups(
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить все группы учителя"""
    return cache_result(
        "teacher_groups",
        current_teacher.id,
        lambda: service.get_my_groups(current_teacher.id),
        model_class=TeacherGroupResponse,
        ttl=600
    )


@router.post("/groups/")
def create_group(
    payload: GroupCreateRequest,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Создать новую группу"""
    try:
        if not payload.name or not payload.name.strip():
            raise HTTPException(status_code=400, detail="Название группы обязательно")
        result = service.create_group(
            name=payload.name.strip(),
            description=payload.description,
            teacher_id=current_teacher.id
        )
        
        # Инвалидируем кеш групп
        invalidate_user_cache(current_teacher.id, "teacher_groups")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/groups/{group_id}")
def update_group(
    group_id: int,
    payload: GroupUpdateRequest,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Обновить группу"""
    try:
        result = service.update_group(
            group_id=group_id,
            teacher_id=current_teacher.id,
            name=payload.name.strip() if payload.name and payload.name.strip() else None,
            description=payload.description
        )
        
        # Инвалидируем кеш групп
        invalidate_user_cache(current_teacher.id, "teacher_groups")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/groups/{group_id}", response_model=MessageResponse)
def delete_group(
    group_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Удалить группу"""
    try:
        result = service.delete_group(group_id, current_teacher.id)
        
        # Инвалидируем кеш групп
        invalidate_user_cache(current_teacher.id, "teacher_groups")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/groups/{group_id}/students", response_model=AddStudentsToGroupResponse)
def add_students_to_group(
    group_id: int,
    payload: AddStudentsToGroupRequest,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Добавить студентов в группу"""
    try:
        result = service.add_students_to_group(
            group_id=group_id,
            teacher_id=current_teacher.id,
            student_ids=payload.student_ids
        )
        
        # Инвалидируем кеш
        invalidate_user_cache(current_teacher.id,
            "teacher_groups",
            "teacher_students"
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/groups/{group_id}/students/{student_id}")
def remove_student_from_group(
    group_id: int,
    student_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Удалить студента из группы"""
    try:
        result = service.remove_student_from_group(group_id, student_id, current_teacher.id)
        
        # Инвалидируем кеш
        invalidate_user_cache(current_teacher.id,
            "teacher_groups",
            "teacher_students"
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/groups/{group_id}/students")
def get_group_students(
    group_id: int,
    service: TeacherService = Depends(get_teacher_service),
    current_teacher: User = Depends(check_teacher)
):
    """Получить список студентов группы"""
    try:
        return cache_result(
            "teacher_group_students",
            current_teacher.id,
            lambda: service.get_group_students(group_id, current_teacher.id),
            ttl=600,
            group_id=group_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))