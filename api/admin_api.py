from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models, dto, auth
from core.database import get_db
from services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin"])


def get_admin_service(db: Session = Depends(get_db)) -> AdminService:
    return AdminService(db)


# ==================== ПОЛЬЗОВАТЕЛИ ====================

@router.get("/users", response_model=List[dto.UserResponse])
def get_users(
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    return service.get_users()


@router.patch("/users/{user_id}/role")
def change_user_role(
    user_id: int,
    new_role: str,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.change_user_role(user_id, new_role, current_admin.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.delete_user(user_id, current_admin.id)
    except ValueError as e:
        raise HTTPException(status_code=400 if "Нельзя" in str(e) else 404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/profile", response_model=dto.UserResponseWithStats)
def get_user_profile(
    user_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.get_user_profile(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/users/{user_id}/history")
def get_user_history(
    user_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    return service.get_user_history(user_id)


# ==================== ЗАДАНИЯ ====================

@router.get("/", response_model=List[dto.TaskResponse])
def get_tasks(
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    return service.get_tasks()


@router.get("/tasks/{task_id}", response_model=dto.TaskResponse)
def get_task(
    task_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.get_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/tasks", response_model=dto.TaskResponse)
def create_task(
    payload: dto.TaskCreate,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    return service.create_task(payload.dict())


@router.put("/tasks/{task_id}", response_model=dto.TaskResponse)
def update_task(
    task_id: int,
    payload: dto.TaskCreate,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.update_task(task_id, payload.dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.delete_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/results/{result_id}")
def get_admin_detailed_result(
    result_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.get_detailed_result(result_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== РАЗРЕШЁННЫЕ EMAIL ====================

@router.get("/allowed/emails", response_model=list[dto.AllowedEmailResponse])
def get_allowed_emails(
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    return service.get_allowed_emails()


@router.post("/allowed-emails")
def add_allowed_email(
    payload: dict,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.add_allowed_email(payload.get("email"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/allowed-emails/{email}")
def delete_allowed_email(
    email: str,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.delete_allowed_email(email)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== НАЗНАЧЕНИЕ УЧИТЕЛЕЙ ====================

@router.post("/assign-student-to-teacher")
def assign_student_to_teacher(
    data: dto.AssignStudentRequest,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.assign_student_to_teacher(data.teacher_id, data.student_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/remove-student-from-teacher/{student_id}")
def remove_student_from_teacher(
    student_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.remove_student_from_teacher(student_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== ТЕОРИЯ ====================

@router.post("/theory", response_model=dto.TheoryResponse)
def create_theory(
    payload: dto.TheoryCreate,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.create_theory(payload.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/theory/getall", response_model=list[dto.TheoryResponse])
def get_all_theory(
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    return service.get_all_theory()


@router.get("/theory/{theory_id}", response_model=dto.TheoryResponse)
def get_theory_by_id(
    theory_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.get_theory_by_id(theory_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/theory/{theory_id}", response_model=dto.TheoryResponse)
def update_theory(
    theory_id: int,
    payload: dto.TheoryUpdate,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.update_theory(theory_id, payload.dict(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/theory/{theory_id}")
def delete_theory(
    theory_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return service.delete_theory(theory_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== ЗАГРУЗКА ИЗОБРАЖЕНИЙ ====================

@router.post("/upload-image", response_model=dto.ImageUploadResponse)
async def upload_to_r2(
    payload: dict,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        image_data = payload.get("image") or payload.get("image_data", "")
        return service.upload_image(image_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ОТПРАВКА В TELEGRAM ====================

@router.post("/tasks/{task_id}/send-to-tg")
async def send_task_to_tg(
    task_id: int,
    chat_id: str,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    try:
        return await service.send_task_to_tg(task_id, chat_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/rebuild-all-static-tests")
def rebuild_all_static_tests(
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Пересборка всех статических тестов"""
    try:
        return service.rebuild_all_static_tests(current_admin.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/{task_id}", response_model=dto.TaskResponse)
def get_task_short(
    task_id: int,
    service: AdminService = Depends(get_admin_service),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Короткая ссылка на задание (для совместимости с админкой)"""
    try:
        return service.get_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Task not found")