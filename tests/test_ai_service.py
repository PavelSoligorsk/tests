"""

🤖 ТЕСТЫ AI-СЕРВИСА
Моки для Mistral API, тестирование всех методов AIService.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import core.models as models


# ==================== МОКИ ====================

class MockMistralResponse:
    """Мок ответа от Mistral API"""
    def __init__(self, content: str):
        self.choices = [
            MagicMock(
                message=MagicMock(
                    content=content
                )
            )
        ]


@pytest.fixture(autouse=True)
def mock_mistral_env():
    """Подменяем MISTRAL_TOKEN, чтобы не было ошибки при инициализации"""
    with patch.dict('os.environ', {'MISTRAL_TOKEN': 'test_mock_token'}):
        yield


@pytest.fixture
def ai_service():
    """Инициализация AI сервиса (с моком)"""
    with patch('mistralai.client.Mistral') as mock_client:
        from services.ai_service import AIService
        service = AIService()
        yield service


# ==================== 1. ТЕСТЫ HINT ====================

class TestAIServiceHint:
    """Тесты получения подсказок"""

    def test_get_hint_success(self, ai_service):
        """✅ Успешное получение подсказки"""
        task = {
            "task_class": "10",
            "topic_number": "1",
            "topic": "algebra",
            "section": "equations",
            "content": "Решите $2x + 3 = 7$",
            "answer": "2",
            "hint": "",
            "solution": "",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 2
        }

        with patch.object(ai_service, '_chat_completion', return_value="Попробуйте перенести 3 в правую часть."):
            hint = ai_service.get_hint(task)
            assert isinstance(hint, str)
            assert len(hint) > 0
            assert "перенести" in hint.lower()

    def test_get_hint_with_mastery(self, ai_service):
        """✅ Подсказка с учётом усвоения темы"""
        task = {
            "task_class": "10",
            "topic_number": "1",
            "topic": "algebra",
            "section": "equations",
            "content": "Решите $2x + 3 = 7$",
            "answer": "2",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 2,
            "same_topic_total": 10,
            "same_topic_correct": 8
        }

        with patch.object(ai_service, '_chat_completion', return_value="Хороший прогресс! Попробуйте..."):
            hint = ai_service.get_hint(task, topic_mastery=80.0)
            assert isinstance(hint, str)
            assert len(hint) > 0

    def test_get_hint_no_api(self, ai_service):
        """❌ Ошибка API"""
        task = {"content": "test", "is_open_answer": False}

        with patch.object(ai_service, '_chat_completion', side_effect=Exception("API Error")):
            with pytest.raises(Exception, match="AI Error"):
                ai_service.get_hint(task)

    def test_get_hint_empty_task(self, ai_service):
        """❌ Пустое задание"""
        with patch.object(ai_service, '_chat_completion', return_value=""):
            hint = ai_service.get_hint({})
            assert hint == ""


# ==================== 2. ТЕСТЫ SOLUTION ====================

class TestAIServiceSolution:
    """Тесты получения решений"""

    def test_get_solution_success(self, ai_service):
        """✅ Успешное получение решения"""
        task = {
            "task_class": "10",
            "topic_number": "1",
            "topic": "algebra",
            "section": "equations",
            "content": "Решите $2x + 3 = 7$",
            "answer": "2",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 2
        }

        with patch.object(ai_service, '_chat_completion',
                          return_value="$$2x = 4$$\n$$x = 2$$\n=== ОТВЕТ === 2"):
            solution = ai_service.get_solution(task)
            assert isinstance(solution, str)
            assert "ОТВЕТ" in solution

    def test_get_solution_no_api(self, ai_service):
        """❌ Ошибка API при получении решения"""
        task = {"content": "test", "is_open_answer": False}

        with patch.object(ai_service, '_chat_completion', side_effect=Exception("API Error")):
            with pytest.raises(Exception, match="AI Error"):
                ai_service.get_solution(task)


# ==================== 3. ТЕСТЫ THEORY ====================

class TestAIServiceTheory:
    """Тесты вопросов по теории"""

    def test_get_theory_answer(self, ai_service):
        """✅ Успешный ответ на вопрос по теории"""
        with patch.object(ai_service, '_chat_completion',
                          return_value="Уравнение — это равенство с неизвестной."):
            answer = ai_service.get_theory_answer(
                question="Что такое уравнение?",
                theory_context="Уравнение — это математическое равенство.",
                topic_name="algebra",
                section_name="equations"
            )
            assert isinstance(answer, str)
            assert len(answer) > 0

    def test_get_theory_answer_no_context(self, ai_service):
        """✅ Вопрос без контекста"""
        with patch.object(ai_service, '_chat_completion', return_value="Я не знаю ответа."):
            answer = ai_service.get_theory_answer(
                question="Сложный вопрос?",
                theory_context="",
                topic_name="",
                section_name=""
            )
            assert isinstance(answer, str)

    def test_get_theory_answer_no_api(self, ai_service):
        """❌ Ошибка API"""
        with patch.object(ai_service, '_chat_completion', side_effect=Exception("API Error")):
            with pytest.raises(Exception, match="AI Error"):
                ai_service.get_theory_answer("test", "")


# ==================== 4. ТЕСТЫ CLASSIFY TOPICS ====================

class TestAIServiceClassify:
    """Тесты классификации тем"""

    def test_classify_topics_success(self, ai_service):
        """✅ Успешная классификация"""
        topics_structure = {
            "algebra": {"equations", "expressions"},
            "geometry": {"angles", "triangles"}
        }

        mock_response = json.dumps({
            "topics": [
                {"name": "algebra", "sections": ["equations"]}
            ]
        })

        with patch.object(ai_service, '_chat_completion', return_value=mock_response):
            result = ai_service.classify_topics("решить уравнение", topics_structure)
            assert len(result) == 1
            assert result[0]["name"] == "algebra"
            assert "equations" in result[0]["sections"]

    def test_classify_topics_empty(self, ai_service):
        """✅ Пустой результат классификации"""
        topics_structure = {"algebra": {"equations"}}

        with patch.object(ai_service, '_chat_completion', return_value=""):
            result = ai_service.classify_topics("test", topics_structure)
            assert result == []

    def test_classify_topics_invalid_json(self, ai_service):
        """✅ Невалидный JSON от API"""
        topics_structure = {"algebra": {"equations"}}

        with patch.object(ai_service, '_chat_completion', return_value="not json"):
            result = ai_service.classify_topics("test", topics_structure)
            assert result == []


# ==================== 5. ТЕСТЫ SELECT TASKS ====================

class TestAIServiceSelectTasks:
    """Тесты выбора заданий"""

    def test_select_tasks_success(self, ai_service):
        """✅ Успешный выбор заданий"""
        available_tasks = [
            {"id": 1, "content": "Task 1", "difficulty": 1, "topic": "algebra"},
            {"id": 2, "content": "Task 2", "difficulty": 2, "topic": "algebra"},
            {"id": 3, "content": "Task 3", "difficulty": 3, "topic": "geometry"},
        ]

        mock_response = json.dumps({"task_ids": [1, 2]})

        with patch.object(ai_service, '_chat_completion', return_value=mock_response):
            result = ai_service.select_tasks(
                user_prompt="algebra tasks",
                available_tasks=available_tasks,
                task_count=2,
                difficulty_text="medium",
                topics_count=1,
                topic_stats={"algebra": 2}
            )
            assert result == [1, 2]

    def test_select_tasks_empty(self, ai_service):
        """✅ Пустой результат"""
        with patch.object(ai_service, '_chat_completion', return_value='{"task_ids": []}'):
            result = ai_service.select_tasks(
                user_prompt="test", available_tasks=[], task_count=2,
                difficulty_text="easy", topics_count=1, topic_stats={}
            )
            assert result == []

    def test_select_tasks_invalid_response(self, ai_service):
        """✅ Невалидный ответ"""
        with patch.object(ai_service, '_chat_completion', return_value="not json"):
            result = ai_service.select_tasks(
                user_prompt="test", available_tasks=[], task_count=2,
                difficulty_text="easy", topics_count=1, topic_stats={}
            )
            assert result == []


# ==================== 6. ТЕСТЫ ВНУТРЕННИХ МЕТОДОВ ====================

class TestAIServiceInternal:
    """Тесты внутренних методов"""

    def test_build_hint_prompt(self, ai_service):
        """✅ Проверка формирования промпта подсказки"""
        task = {
            "task_class": "10", "topic_number": "1", "topic": "algebra",
            "section": "equations", "content": "test", "answer": "2",
            "difficulty": 2, "is_open_answer": False, "options": ["1", "2", "3", "4"]
        }
        prompt = ai_service._build_hint_prompt(task, None)
        assert "ЗАДАНИЕ" in prompt
        assert "test" in prompt
        assert "НЕ ДАВАЙ ГОТОВЫЙ ОТВЕТ" in prompt

    def test_build_solution_prompt(self, ai_service):
        """✅ Проверка формирования промпта решения"""
        task = {
            "task_class": "10", "topic_number": "1", "topic": "algebra",
            "section": "equations", "content": "test", "answer": "2",
            "difficulty": 2, "is_open_answer": False, "options": ["1", "2", "3", "4"]
        }
        prompt = ai_service._build_solution_prompt(task, None)
        assert "ЗАДАНИЕ" in prompt
        assert "ОТВЕТ" in prompt

    def test_get_format_instructions(self, ai_service):
        """✅ Проверка инструкций форматирования"""
        instructions = ai_service._get_format_instructions()
        assert "НЕ ДАВАЙ ГОТОВЫЙ ОТВЕТ" in instructions
        assert "$$" in instructions

    def test_get_solution_requirements(self, ai_service):
        """✅ Проверка требований к решению"""
        requirements = ai_service._get_solution_requirements()
        assert "ОТВЕТ" in requirements
        assert "KaTeX" in requirements
