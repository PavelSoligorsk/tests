from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.models import User
from dto_schemas import (
    UserResponseWithStats, UserResponse, TestResponse,
    UserUpdate, AITestRequest
)
from core import auth
from core.database import get_db
from typing import List
from services.student_service import StudentService
from core.cache import cache_result, invalidate_user_cache

router = APIRouter(prefix="/student", tags=["Student API"])


def get_student_service(db: Session = Depends(get_db)) -> StudentService:
    return StudentService(db)


@router.get("/me", response_model=UserResponseWithStats)
def get_student_profile(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить профиль студента с статистикой"""
    try:
        return cache_result(
            "student_profile",
            current_user.id,
            lambda: service.get_profile(current_user.id),
            ttl=300
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/me", response_model=UserResponse)
def update_student_profile(
    obj_in: UserUpdate,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Обновить профиль студента"""
    try:
        update_data = obj_in.model_dump(exclude_unset=True)
        
        # Инвалидируем кеш профиля
        invalidate_user_cache(current_user.id, "student_profile")
        
        return service.update_profile(current_user.id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail="Ошибка при обновлении профиля")


@router.get("/tests", response_model=List[TestResponse])
def get_student_tests(
    service: StudentService = Depends(get_student_service)
):
    """Получить все доступные тесты"""
    return cache_result(
        "available_tests",
        None,
        lambda: service.get_available_tests(),
        ttl=600
    )


@router.get("/tests/{test_id}", response_model=TestResponse)
def get_test_for_passing(
    test_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить тест для прохождения"""
    try:
        return cache_result(
            "test_details",
            None,
            lambda: service.get_test_for_passing(test_id),
            ttl=300,
            test_id=test_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/tests/{test_id}/submit")
def submit_test_results(
    test_id: int,
    answers: List[dict],
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Отправить результаты теста"""
    try:
        result = service.submit_test(test_id, current_user.id, answers)
        
        # Инвалидируем все кеши пользователя
        invalidate_user_cache(
            current_user.id,
            "student_profile",
            "my_history",
            "my_assignments",
            "my_assignments_meta",
            "my_ai_tests"
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/history")
def get_my_history(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить историю тестов студента"""
    return cache_result(
        "my_history",
        current_user.id,
        lambda: service.get_history(current_user.id),
        ttl=120
    )


@router.get("/results/{result_id}")
def get_detailed_result(
    result_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить детальный результат теста"""
    try:
        return cache_result(
            "detailed_result",
            current_user.id,
            lambda: service.get_detailed_result(result_id, current_user.id),
            ttl=600,
            result_id=result_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/my-assignments")
def get_my_assignments(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить назначенные тесты студента"""
    return cache_result(
        "my_assignments",
        current_user.id,
        lambda: service.get_assignments(current_user.id),
        ttl=180
    )


@router.post("/start-test/{test_id}")
def start_assigned_test(
    test_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Начать назначенный тест"""
    try:
        result = service.start_assigned_test(test_id, current_user.id)
        
        # Инвалидируем кеш назначений
        invalidate_user_cache(
            current_user.id,
            "my_assignments",
            "my_assignments_meta"
        )
        
        return result
    except ValueError as e:
        status_code = 400 if "Срок" in str(e) else 403
        raise HTTPException(status_code=status_code, detail=str(e))


@router.post("/tasks/{task_id}/hint")
def get_ai_hint_while_solving(
    task_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить подсказку от AI для задачи"""
    try:
        # Не кешируем, т.к. подсказки могут быть разными
        return service.get_ai_hint(task_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


@router.post("/tasks/{task_id}/ai-solve")
def get_ai_solution(
    task_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить решение от AI для задачи"""
    try:
        # Не кешируем, т.к. решения индивидуальны
        return service.get_ai_solution(task_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


# ============= ТЕОРЕТИЧЕСКИЕ ЭНДПОИНТЫ =============

@router.get("/theory/topics")
def get_theory_topics(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить все темы теории"""
    return cache_result(
        "theory_topics",
        None,
        lambda: service.get_theory_topics(),
        ttl=3600
    )


@router.get("/theory/by-topic/{topic}")
def get_theory_by_topic(
    topic: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить теорию по теме"""
    try:
        return cache_result(
            "theory_by_topic",
            None,
            lambda: service.get_theory_by_topic(topic),
            ttl=3600,
            topic=topic
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/theory/sections/{topic}")
def get_theory_sections(
    topic: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить все разделы по теме"""
    try:
        return cache_result(
            "theory_sections",
            None,
            lambda: service.get_theory_sections(topic),
            ttl=3600,
            topic=topic
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/theory/ask-ai")
def ask_ai_about_theory(
    request: dict,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Задать вопрос AI по теории"""
    try:
        theory_id = request.get("theory_id")
        question = request.get("question", "").strip()
        theory_content = request.get("theory_content", "")

        # Не кешируем, т.к. вопросы уникальны
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
    current_user: User = Depends(auth.get_current_user)
):
    """Получить теорию по теме и разделу"""
    try:
        return service.get_theory_by_topic_section(topic, section)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/generate-test")
def generate_ai_test(
    request: AITestRequest,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Сгенерировать AI-тест"""
    try:
        result = service.generate_ai_test(
            current_user.id,
            request.prompt,
            request.task_count,
            request.difficulty
        )
        
        # Инвалидируем кеш AI тестов
        invalidate_user_cache(current_user.id, "my_ai_tests")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации теста: {str(e)}")


@router.get("/tests-meta")
def get_student_tests_meta(
    service: StudentService = Depends(get_student_service)
):
    """Получить только метаинформацию о тестах (без заданий)"""
    return cache_result(
        "tests_meta",
        None,
        lambda: service.get_available_tests_meta(),
        ttl=600
    )


@router.get("/my-assignments-meta")
def get_my_assignments_meta(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить метаинформацию о назначенных тестах"""
    return cache_result(
        "my_assignments_meta",
        current_user.id,
        lambda: service.get_assignments_meta(current_user.id),
        ttl=180
    )


@router.get("/ai-tests")
def get_my_ai_tests(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить AI-тесты студента (в том числе недопройденные)"""
    return cache_result(
        "my_ai_tests",
        current_user.id,
        lambda: service.get_ai_tests(current_user.id),
        ttl=120
    )