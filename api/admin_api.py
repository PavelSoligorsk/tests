from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from core.models import User
from dto_schemas import (
    UserResponse, UserResponseWithStats, TaskResponse, TaskCreate,
    AllowedEmailResponse, AssignStudentRequest, TheoryResponse,
    TheoryCreate, TheoryUpdate, ImageUploadResponse,
    AllowedEmailCreate, ImageUploadRequest,
    ChangeUserRoleRequest, SendTaskToTgRequest,
    AllowedEmailItemResponse, RebuildTestsResponse, MessageResponse,
    TeacherHistoryItemResponse, DetailedResultResponse,
    BatchTaskCreateRequest, BatchTaskCreateResponse,
    BatchTaskUpdateRequest, BatchTaskUpdateResponse,
    BatchTaskDeleteRequest, BatchTaskDeleteResponse,
    ClassifyTasksRequest, ClassifyTasksResponse,
    TestResponse, TeacherTaskMetaResponse,
    TeacherTaskMetaByTopicSectionResponse,
    TeacherTaskDetailResponse,
)
from core import auth
from core.cache import invalidate_cache_pattern, async_cache_result, invalidate_user_cache
from core.database import get_db
from services.admin_service import AdminService, PermissionError

router = APIRouter(prefix="/admin", tags=["Admin"])


def get_admin_service(db: AsyncSession = Depends(get_db)) -> AdminService:
    return AdminService(db)


def _invalidate_task_caches() -> None:
    invalidate_cache_pattern("teacher_tasks*")
    invalidate_cache_pattern("teacher_test_detail*")
    invalidate_cache_pattern("teacher_test_tasks*")
    invalidate_cache_pattern("teacher_tests*")
    invalidate_cache_pattern("available_tests")
    invalidate_cache_pattern("available_tests:*")
    invalidate_cache_pattern("tests_meta")
    invalidate_cache_pattern("tests_meta:*")
    invalidate_cache_pattern("test_details")
    invalidate_cache_pattern("test_details:*")


def _invalidate_theory_caches() -> None:
    invalidate_cache_pattern("theory_topics")
    invalidate_cache_pattern("theory_topics:*")
    invalidate_cache_pattern("theory_by_topic*")
    invalidate_cache_pattern("theory_sections*")


# ==================== ПОЛЬЗОВАТЕЛИ ====================

@router.get("/users", response_model=List[UserResponse])
async def get_users(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    return await service.get_users()


@router.patch("/users/{user_id}/role", response_model=MessageResponse)
async def change_user_role(
    user_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin),
    payload: ChangeUserRoleRequest | None = Body(default=None),
    new_role: Optional[str] = Query(default=None)
):
    try:
        role = payload.new_role if payload is not None else new_role
        if role is None:
            raise HTTPException(status_code=422, detail="new_role is required")
        return await service.change_user_role(user_id, role, current_admin.id)
    except ValueError as e:
        if "найден" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.delete_user(user_id, current_admin.id)
    except ValueError as e:
        raise HTTPException(status_code=400 if "Нельзя" in str(e) else 404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/profile", response_model=UserResponseWithStats)
async def get_user_profile(
    user_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.get_user_profile(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/users/{user_id}/history", response_model=list[TeacherHistoryItemResponse])
async def get_user_history(
    user_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    return await service.get_user_history(user_id)


# ==================== ЗАДАНИЯ ====================

@router.get("/", response_model=List[TaskResponse])
async def get_tasks(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    return await service.get_tasks()


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    payload: TaskCreate,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    result = await service.create_task(payload.model_dump())
    _invalidate_task_caches()
    return result


# ==================== ПАКЕТНЫЕ ОПЕРАЦИИ С ЗАДАНИЯМИ ====================
# Important: batch routes MUST be registered before /tasks/{task_id}
# to avoid the path param capturing "batch" as a task_id.


@router.post("/tasks/batch", response_model=BatchTaskCreateResponse)
async def create_tasks_batch(
    payload: BatchTaskCreateRequest,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Пакетное создание заданий (до 500 за раз)"""
    tasks_data = [t.model_dump() for t in payload.tasks]
    result = await service.create_tasks_batch(tasks_data)
    _invalidate_task_caches()
    return result


@router.put("/tasks/batch", response_model=BatchTaskUpdateResponse)
async def update_tasks_batch(
    payload: BatchTaskUpdateRequest,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Пакетное обновление заданий (до 500 за раз)"""
    tasks_data = [t.model_dump(exclude_unset=True) for t in payload.tasks]
    result = await service.update_tasks_batch(tasks_data)
    _invalidate_task_caches()
    return result


@router.delete("/tasks/batch", response_model=BatchTaskDeleteResponse)
async def delete_tasks_batch(
    payload: BatchTaskDeleteRequest,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Пакетное удаление заданий (до 500 за раз)"""
    result = await service.delete_tasks_batch(payload.ids)
    _invalidate_task_caches()
    return result


# --- Named-prefix GET routes (before {task_id} to avoid shadowing) ---


@router.get("/tasks/by-topic/{topic}/section/{section}", response_model=List[TaskResponse])
async def get_tasks_by_topic_section(
    topic: str,
    section: str,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Ленивая загрузка заданий по теме и разделу (как у учителя)"""
    return await async_cache_result(
        "teacher_tasks_by_topic_section",
        None,
        lambda: service.get_tasks_by_topic_section(topic, section),
        model_class=TaskResponse,
        ttl=3600,
        topic=topic,
        section=section
    )


@router.get("/tasks/by-class/", response_model=List[TaskResponse])
async def get_tasks_by_class_topic(
    task_class: str = Query(...),
    topic_number: str = Query(...),
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Ленивая загрузка заданий по классу и номеру темы (как у учителя)"""
    return await async_cache_result(
        "teacher_tasks_by_class",
        None,
        lambda: service.get_tasks_by_class_and_topic(task_class, topic_number),
        model_class=TaskResponse,
        ttl=3600,
        task_class=task_class,
        topic_number=topic_number
    )


# --- Single-item routes (after named-prefix to avoid shadowing) ---


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.get_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskCreate,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        result = await service.update_task(task_id, payload.model_dump())
        _invalidate_task_caches()
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/tasks/{task_id}", response_model=MessageResponse)
async def delete_task(
    task_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        result = await service.delete_task(task_id)
        _invalidate_task_caches()
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/results/{result_id}", response_model=DetailedResultResponse)
async def get_admin_detailed_result(
    result_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.get_detailed_result(result_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== РАЗРЕШЁННЫЕ EMAIL ====================

@router.get("/allowed/emails", response_model=list[AllowedEmailItemResponse])
async def get_allowed_emails(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    return await service.get_allowed_emails()


@router.post("/allowed-emails")
async def add_allowed_email(
    payload: AllowedEmailCreate,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.add_allowed_email(payload.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/allowed-emails/{email}")
async def delete_allowed_email(
    email: str,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.delete_allowed_email(email)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== НАЗНАЧЕНИЕ УЧИТЕЛЕЙ ====================

@router.post("/assign-student-to-teacher", response_model=MessageResponse)
async def assign_student_to_teacher(
    data: AssignStudentRequest,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.assign_student_to_teacher(data.teacher_id, data.student_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/remove-student-from-teacher/{student_id}", response_model=MessageResponse)
async def remove_student_from_teacher(
    student_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.remove_student_from_teacher(student_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== ТЕОРИЯ ====================

@router.post("/theory", response_model=TheoryResponse)
async def create_theory(
    payload: TheoryCreate,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        result = await service.create_theory(payload.model_dump())
        _invalidate_theory_caches()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/theory/getall", response_model=list[TheoryResponse])
async def get_all_theory(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    return await service.get_all_theory()


@router.get("/theory/{theory_id}", response_model=TheoryResponse)
async def get_theory_by_id(
    theory_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        return await service.get_theory_by_id(theory_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/theory/{theory_id}", response_model=TheoryResponse)
async def update_theory(
    theory_id: int,
    payload: TheoryUpdate,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        result = await service.update_theory(theory_id, payload.model_dump(exclude_unset=True))
        _invalidate_theory_caches()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/theory/{theory_id}")
async def delete_theory(
    theory_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        result = await service.delete_theory(theory_id)
        _invalidate_theory_caches()
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== ЗАГРУЗКА ИЗОБРАЖЕНИЙ ====================

@router.post("/upload-image", response_model=ImageUploadResponse)
async def upload_to_r2(
    payload: ImageUploadRequest,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    try:
        image_data = payload.image or payload.image_data or ""
        return await service.upload_image(image_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ОТПРАВКА В TELEGRAM ====================

@router.post("/tasks/{task_id}/send-to-tg")
async def send_task_to_tg(
    task_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin),
    payload: SendTaskToTgRequest | None = Body(default=None),
    chat_id: Optional[str] = Query(default=None)
):
    try:
        target_chat_id = payload.chat_id if payload is not None else chat_id
        if target_chat_id is None:
            raise HTTPException(status_code=422, detail="chat_id is required")
        return await service.send_task_to_tg(task_id, target_chat_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/classify-tasks", response_model=ClassifyTasksResponse)
async def classify_tasks(
    payload: ClassifyTasksRequest,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """AI-классификация заданий: определение topic/section.

    Параметр task_ids — массив ID заданий для обработки (без ограничений).
    Если пустой — обрабатываются все неклассифицированные задания.
    """
    try:
        result = await service.classify_tasks(payload.task_ids)
        _invalidate_task_caches()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== ЛЕНИВАЯ ЗАГРУЗКА (МЕТА-ИНФОРМАЦИЯ) ====================

@router.get("/tasks-meta")
async def get_tasks_meta(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Получить только структуру заданий (классы, темы) без содержимого"""
    return await async_cache_result(
        "teacher_tasks_meta",
        None,
        lambda: service.get_tasks_meta(),
        model_class=TeacherTaskMetaResponse,
        ttl=7200
    )


@router.get("/tasks-meta-by-topic-section")
async def get_tasks_meta_by_topic_section(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Получить структуру: { topic: { section: count } }"""
    return await async_cache_result(
        "teacher_tasks_meta_by_topic_section",
        None,
        lambda: service.get_tasks_meta_by_topic_section(),
        model_class=TeacherTaskMetaByTopicSectionResponse,
        ttl=7200
    )


# ==================== РАБОТА С ТЕСТАМИ ====================

@router.get("/tests", response_model=List[TestResponse])
async def get_all_tests(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Получить все тесты (админ видит все)"""
    return await async_cache_result(
        "teacher_tests",
        current_admin.id,
        lambda: service.get_tests(current_admin.id),
        model_class=TestResponse,
        ttl=300
    )


@router.get("/tests/{test_id}", response_model=TestResponse)
async def get_test_detail(
    test_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Получить детали теста"""
    try:
        return await async_cache_result(
            "teacher_test_detail",
            current_admin.id,
            lambda: service.get_test_detail(test_id, current_admin.id),
            model_class=TestResponse,
            ttl=300,
            entity_id=test_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/tests/{test_id}/tasks")
async def get_test_tasks(
    test_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Получить только задания теста (ленивая загрузка)"""
    try:
        return await async_cache_result(
            "teacher_test_tasks",
            current_admin.id,
            lambda: service.get_test_tasks(test_id, current_admin.id),
            model_class=TaskResponse,
            ttl=300,
            entity_id=test_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/rebuild-all-static-tests")
async def rebuild_all_static_tests(
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Пересборка всех статических тестов"""
    try:
        result = await service.rebuild_all_static_tests(current_admin.id)
        _invalidate_task_caches()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_short(
    task_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: User = Depends(auth.check_admin)
):
    """Короткая ссылка на задание (для совместимости с админкой)"""
    try:
        return await service.get_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Task not found")