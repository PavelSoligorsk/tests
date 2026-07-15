from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import models, dto, auth
from core.database import get_db
from typing import List
from services.student_service import StudentService

router = APIRouter(prefix="/student", tags=["Student API"])


def get_student_service(db: Session = Depends(get_db)) -> StudentService:
    return StudentService(db)


@router.get("/me", response_model=dto.UserResponseWithStats)
def get_student_profile(
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_profile(current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/me", response_model=dto.UserResponse)
def update_student_profile(
    obj_in: dto.UserUpdate,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        update_data = obj_in.dict(exclude_unset=True)
        return service.update_profile(current_user.id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail="Ошибка при обновлении профиля")


@router.get("/tests", response_model=List[dto.TestResponse])
def get_student_tests(
    service: StudentService = Depends(get_student_service)
):
    return service.get_available_tests()


@router.get("/tests/{test_id}", response_model=dto.TestResponse)
def get_test_for_passing(
    test_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_test_for_passing(test_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/tests/{test_id}/submit")
def submit_test_results(
    test_id: int,
    answers: List[dict],
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.submit_test(test_id, current_user.id, answers)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/history")
def get_my_history(
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    return service.get_history(current_user.id)


@router.get("/results/{result_id}")
def get_detailed_result(
    result_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_detailed_result(result_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/my-assignments")
def get_my_assignments(
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    return service.get_assignments(current_user.id)


@router.post("/start-test/{test_id}")
def start_assigned_test(
    test_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.start_assigned_test(test_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400 if "Срок" in str(e) else 403, detail=str(e))


@router.post("/tasks/{task_id}/hint")
def get_ai_hint_while_solving(
    task_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_ai_hint(task_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


@router.post("/tasks/{task_id}/ai-solve")
def get_ai_solution(
    task_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_ai_solution(task_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


# Теоретические эндпоинты
@router.get("/theory/topics")
def get_theory_topics(
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    return service.get_theory_topics()


@router.get("/theory/by-topic/{topic}")
def get_theory_by_topic(
    topic: str,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_theory_by_topic(topic)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/theory/sections/{topic}")
def get_theory_sections(
    topic: str,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получить все разделы по теме"""
    try:
        return service.get_theory_sections(topic)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/theory/ask-ai")
def ask_ai_about_theory(
    request: dict,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        theory_id = request.get("theory_id")
        question = request.get("question", "").strip()
        theory_content = request.get("theory_content", "")
        
        return service.ask_ai_about_theory(question, theory_id, theory_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")

@router.get("/theory/by-topic/{topic}/section/{section}")
def get_theory_by_topic_section(
    topic: str,
    section: str,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получить теорию по теме и разделу"""
    try:
        return service.get_theory_by_topic_section(topic, section)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/generate-test")
def generate_ai_test(
    request: dto.AITestRequest,
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.generate_ai_test(
            current_user.id, 
            request.prompt, 
            request.task_count, 
            request.difficulty
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации теста: {str(e)}")
    
@router.get("/tests-meta")
def get_student_tests_meta(
    service: StudentService = Depends(get_student_service)
):
    """Получить только метаинформацию о тестах (без заданий)"""
    return service.get_available_tests_meta()

@router.get("/my-assignments-meta")
def get_my_assignments_meta(
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получить метаинформацию о назначенных тестах"""
    return service.get_assignments_meta(current_user.id)

@router.get("/ai-tests")
def get_my_ai_tests(
    service: StudentService = Depends(get_student_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получить AI-тесты студента (в том числе недопройденные)"""
    return service.get_ai_tests(current_user.id)
