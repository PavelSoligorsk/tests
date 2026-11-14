"""Ответ, сохранённый при выходе из теста, остаётся проверяемым."""
from services.student_service import StudentService


class _Task:
    def __init__(self, answer: str, is_open: bool = False):
        self.answer = answer
        self.is_open_answer = is_open


def _service() -> StudentService:
    return StudentService.__new__(StudentService)


def test_closed_answer_stays_correct_after_it_is_stored_as_text():
    service = _service()
    task = _Task("1,3")
    chosen = ["3", "1"]
    assert service._check_answer(task, chosen) is True

    stored = service._serialize_answer(chosen)
    restored = service._parse_stored_answer(stored)
    assert service._check_answer(task, restored) is True

    # Так save_progress писал список до исправления: str(['3', '1']).
    legacy = str(chosen)
    assert service._check_answer(task, service._parse_stored_answer(legacy)) is True


def test_open_answer_is_compared_as_text():
    service = _service()
    task = _Task(" 42 ", is_open=True)
    assert service._check_answer(task, "42") is True
    assert service._check_answer(task, service._parse_stored_answer("42")) is True
    assert service._check_answer(task, "41") is False
