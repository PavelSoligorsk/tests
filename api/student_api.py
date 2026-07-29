from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import User
from dto_schemas import (
    UserResponseWithStats, UserResponse, TestResponse,
    UserUpdate, AITestRequest, TheoryResponse,
    StudentHistoryItemResponse, DetailedResultResponse,
    StudentAssignmentItemResponse, TheoryTopicSummaryResponse,
    TheorySectionSummaryResponse, StudentAssignmentMetaItemResponse,
    StudentAITestItemResponse, AvailableTestMetaResponse,
    TheoryQuestionRequest, TestAnswerSubmission, StartAssignedTestResponse,
    RetakeTestResponse,
    SaveProgressRequest, SaveProgressResponse,
)
from core import auth
from core.database import get_db
from typing import List
from services.student_service import StudentService
from core.cache import async_cache_result, invalidate_user_cache

router = APIRouter(prefix="/student", tags=["Student API"])


def get_student_service(db: AsyncSession = Depends(get_db)) -> StudentService:
    return StudentService(db)


@router.get("/me", response_model=UserResponseWithStats)
async def get_student_profile(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить профиль студента с статистикой"""
    try:
        return await async_cache_result(
            "student_profile",
            current_user.id,
            lambda: service.get_profile(current_user.id),
            model_class=UserResponseWithStats,
            ttl=300
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/me", response_model=UserResponse)
async def update_student_profile(
    obj_in: UserUpdate,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Обновить профиль студента"""
    try:
        update_data = obj_in.model_dump(exclude_unset=True)
        
        # Инвалидируем кеш профиля
        invalidate_user_cache(current_user.id, "student_profile")
        
        return await service.update_profile(current_user.id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail="Ошибка при обновлении профиля")


@router.get("/tests", response_model=List[TestResponse])
async def get_student_tests(
    service: StudentService = Depends(get_student_service)
):
    """Получить все доступные тесты"""
    return await async_cache_result(
        "available_tests",
        None,
        lambda: service.get_available_tests(),
        model_class=TestResponse,
        ttl=600
    )


@router.get("/tests/{test_id}", response_model=TestResponse)
async def get_test_for_passing(
    test_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить тест для прохождения"""
    try:
        test = await async_cache_result(
            "test_details",
            None,
            lambda: service.get_test_for_passing(test_id),
            model_class=TestResponse,
            ttl=300,
            entity_id=test_id
        )
        # Проверка лимитов per-user (не кешируется)
        await service._check_attempt_limits(current_user.id, test)
        return test
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tests/{test_id}/submit")
async def submit_test_results(
    test_id: int,
    answers: List[TestAnswerSubmission],
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Отправить результаты теста"""
    try:
        result = await service.submit_test(test_id, current_user.id, [answer.model_dump() for answer in answers])
        
        # Инвалидируем все кеши пользователя
        invalidate_user_cache(
            current_user.id,
            "student_profile",
            "my_history",
            "my_assignments",
            "my_assignments_meta",
            "my_ai_tests",
            "detailed_result"
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/tests/{test_id}/save-progress", response_model=SaveProgressResponse)
async def save_test_progress(
    test_id: int,
    request: SaveProgressRequest,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Сохранить прогресс без завершения теста.

    Позволяет студенту выйти из теста без потери ответов.
    Фронтенд может вызывать этот эндпоинт когда студент:
    - Закрывает вкладку
    - Переходит на другую страницу
    - Нажимает «Выйти» (но не «Завершить»)
    - Периодически (автосохранение)

    При возобновлении теста (start-test) сервер вернёт previous_answers.
    """
    try:
        result = await service.save_progress(
            test_id,
            current_user.id,
            [ans.model_dump() for ans in request.answers]
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/history")
async def get_my_history(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить историю тестов студента"""
    return await async_cache_result(
        "my_history",
        current_user.id,
        lambda: service.get_history(current_user.id),
        model_class=StudentHistoryItemResponse,
        ttl=120
    )


@router.get("/results/{result_id}")
async def get_detailed_result(
    result_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить детальный результат теста"""
    try:
        return await async_cache_result(
            "detailed_result",
            current_user.id,
            lambda: service.get_detailed_result(result_id, current_user.id),
            model_class=DetailedResultResponse,
            ttl=600,
            entity_id=result_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/my-assignments")
async def get_my_assignments(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить назначенные тесты студента"""
    return await async_cache_result(
        "my_assignments",
        current_user.id,
        lambda: service.get_assignments(current_user.id),
        model_class=StudentAssignmentItemResponse,
        ttl=180
    )


@router.post("/start-test/{test_id}")
async def start_assigned_test(
    test_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Начать назначенный тест"""
    try:
        result = await service.start_assigned_test(test_id, current_user.id)
        
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
async def get_ai_hint_while_solving(
    task_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить подсказку от AI для задачи"""
    try:
        # Не кешируем, т.к. подсказки могут быть разными
        return await service.get_ai_hint(task_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


@router.post("/tasks/{task_id}/ai-solve")
async def get_ai_solution(
    task_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить решение от AI для задачи"""
    try:
        # Не кешируем, т.к. решения индивидуальны
        return await service.get_ai_solution(task_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


# ============= ТЕОРЕТИЧЕСКИЕ ЭНДПОИНТЫ =============

@router.get("/theory/topics")
async def get_theory_topics(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить все темы теории"""
    return await async_cache_result(
        "theory_topics",
        None,
        lambda: service.get_theory_topics(),
        model_class=TheoryTopicSummaryResponse,
        ttl=3600
    )


@router.get("/theory/by-topic/{topic}")
async def get_theory_by_topic(
    topic: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить теорию по теме"""
    try:
        return await async_cache_result(
            "theory_by_topic",
            None,
            lambda: service.get_theory_by_topic(topic),
            model_class=TheoryResponse,
            ttl=3600,
            topic=topic
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/theory/sections/{topic}")
async def get_theory_sections(
    topic: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить все разделы по теме"""
    try:
        return await async_cache_result(
            "theory_sections",
            None,
            lambda: service.get_theory_sections(topic),
            model_class=TheorySectionSummaryResponse,
            ttl=3600,
            topic=topic
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/theory/ask-ai")
async def ask_ai_about_theory(
    request: TheoryQuestionRequest,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Задать вопрос AI по теории"""
    try:
        theory_id = request.theory_id
        question = request.question.strip()
        theory_content = request.theory_content

        # Не кешируем, т.к. вопросы уникальны
        return await service.ask_ai_about_theory(question, theory_id, theory_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


@router.get("/theory/by-topic/{topic}/section/{section}")
async def get_theory_by_topic_section(
    topic: str,
    section: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить теорию по теме и разделу"""
    try:
        return await service.get_theory_by_topic_section(topic, section)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/generate-test")
async def generate_ai_test(
    request: AITestRequest,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Сгенерировать AI-тест"""
    try:
        result = await service.generate_ai_test(
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
async def get_student_tests_meta(
    service: StudentService = Depends(get_student_service)
):
    """Получить только метаинформацию о тестах (без заданий)"""
    return await async_cache_result(
        "tests_meta",
        None,
        lambda: service.get_available_tests_meta(),
        model_class=AvailableTestMetaResponse,
        ttl=600
    )


@router.get("/my-assignments-meta")
async def get_my_assignments_meta(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить метаинформацию о назначенных тестах"""
    return await async_cache_result(
        "my_assignments_meta",
        current_user.id,
        lambda: service.get_assignments_meta(current_user.id),
        model_class=StudentAssignmentMetaItemResponse,
        ttl=180
    )


@router.get("/ai-tests")
async def get_my_ai_tests(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить AI-тесты студента (в том числе недопройденные)"""
    return await async_cache_result(
        "my_ai_tests",
        current_user.id,
        lambda: service.get_ai_tests(current_user.id),
        model_class=StudentAITestItemResponse,
        ttl=120
    )


@router.get("/ai-tests/incomplete", response_model=list[StudentAITestItemResponse])
async def get_incomplete_ai_tests(
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Получить AI-тесты, которые студент начал но не завершил"""
    return await service.get_incomplete_ai_tests(current_user.id)


@router.post("/start-ai-test/{test_id}", response_model=StartAssignedTestResponse)
async def start_ai_test(
    test_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Начать AI-тест — получить задания и result_id"""
    try:
        result = await service.start_ai_test(test_id, current_user.id)

        invalidate_user_cache(
            current_user.id,
            "my_ai_tests",
        )

        return result
    except ValueError as e:
        raise HTTPException(status_code=400 if "деактивирован" in str(e) or "не AI" in str(e) else 403, detail=str(e))


@router.post("/retake/{result_id}", response_model=RetakeTestResponse)
async def retake_test(
    result_id: int,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(auth.get_current_user)
):
    """Пересдать тест — создать новую попытку по предыдущему result_id.

    result_id — ID любого завершённого TestResult пользователя.
    Сервер находит test_id, проверяет лимиты попыток, экзаменационное окно
    и создаёт новый TestResult с заданиями.
    """
    try:
        result = await service.retake_test(result_id, current_user.id)

        invalidate_user_cache(
            current_user.id,
            "student_profile",
            "my_history",
            "my_assignments",
            "my_assignments_meta",
            "my_ai_tests",
        )

        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))