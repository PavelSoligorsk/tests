import re
import random
from typing import List, Dict, Optional
from repositories.user_repository import UserRepository
from repositories.test_repository import TestRepository
from repositories.task_repository import TaskRepository
from repositories.result_repository import ResultRepository
from repositories.assignment_repository import AssignmentRepository
from repositories.theory_repository import TheoryRepository
from services.ai_service import AIService
from datetime import datetime  # Add this import

class StudentService:
    def __init__(self, db):
        self.user_repo = UserRepository(db)
        self.test_repo = TestRepository(db)
        self.task_repo = TaskRepository(db)
        self.result_repo = ResultRepository(db)
        self.assignment_repo = AssignmentRepository(db)
        self.theory_repo = TheoryRepository(db)
        self.ai_service = AIService()
        self.db = db
    
    def get_profile(self, user_id: int):
        """Получить профиль студента со статистикой"""
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        stats = self.user_repo.get_user_stats(user_id)
        
        return {
            "user": user,
            "stats": stats
        }
    
    def update_profile(self, user_id: int, update_data: dict):
        """Обновить профиль студента"""
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        return self.user_repo.update_user(user, update_data)
    
    def get_available_tests(self):
        """Получить доступные тесты"""
        return self.test_repo.get_available_tests()
    
    def get_test_for_passing(self, test_id: int):
        """Получить тест для прохождения"""
        test = self.test_repo.get_test_by_id(test_id)
        if not test:
            raise ValueError("Тест не найден")
        return test
    
    def submit_test(self, test_id: int, user_id: int, answers: List[dict]):
        """Отправить ответы на тест"""
        test = self.test_repo.get_test_with_tasks(test_id)
        if not test:
            raise ValueError("Тест не найден")
        
        total_points = 0
        result = self.result_repo.create_result(test_id, user_id)
        
        for ans in answers:
            task = self.task_repo.get_task_by_id(ans['task_id'])
            if not task:
                continue
            
            is_correct = self._check_answer(task, ans['user_answer'])
            current_points = 2 if (is_correct and task.is_open_answer) else (1 if is_correct else 0)
            total_points += current_points
            
            self.result_repo.save_answer(
                result.id, task.id, str(ans['user_answer']), is_correct, current_points
            )
        
        # Деактивируем AI-тест после прохождения
        if test.is_ai_generated:
            self.test_repo.deactivate_test(test_id)
        
        self.result_repo.update_result_points(result.id, total_points)
        
        return {
            "status": "success",
            "score": total_points,
            "max_score_possible": sum(2 if t.is_open_answer else 1 for t in test.tasks)
        }
    
    def get_history(self, user_id: int):
        """Получить историю попыток"""
        results = self.result_repo.get_user_history(user_id)
        
        history = []
        for r in results:
            history.append({
                "id": r.id,
                "test_id": r.test_id if r.test_id else 0,
                "user_id": r.user_id,
                "total_points": r.total_points or 0,
                "completed_at": r.completed_at,
                "test_title": r.test.title if r.test else "Тест удалён",
                "test": {
                    "id": r.test.id,
                    "title": r.test.title
                } if r.test else None
            })
        
        return history
    
    def get_detailed_result(self, result_id: int, user_id: int):
        """Получить детальный результат теста"""
        result = self.result_repo.get_result_by_id(result_id)
        if not result or result.user_id != user_id:
            raise ValueError("Результат не найден")
        
        if not result.test:
            return {
                "test_title": "Тест удалён",
                "total_points": result.total_points or 0,
                "max_points": 0,
                "completed_at": result.completed_at,
                "difficulty_stats": {},
                "details": []
            }
        
        all_tasks = self.task_repo.get_tasks_by_test_id(result.test_id)
        user_answers = self.result_repo.get_user_answers_for_result(result_id)
        answers_map = {ua.task_id: ua for ua in user_answers}
        
        details = []
        total_max_points = 0
        stats = {str(i): {"total": 0, "correct": 0} for i in range(1, 6)}
        
        for task in all_tasks:
            ua = answers_map.get(task.id)
            max_task_points = 2 if task.is_open_answer else 1
            total_max_points += max_task_points
            
            diff = str(task.difficulty) if task.difficulty else "1"
            if diff in stats:
                stats[diff]["total"] += 1
                if ua and ua.is_correct:
                    stats[diff]["correct"] += 1
            
            details.append({
                "task_id": task.id,
                "content": task.content,
                "options": task.options,
                "correct_answer": task.answer,
                "user_answer": ua.user_text_answer if ua else "Нет ответа",
                "is_correct": ua.is_correct if ua else False,
                "solution": task.solution,
                "difficulty": task.difficulty
            })
        
        return {
            "test_title": result.test.title,
            "total_points": result.total_points or 0,
            "max_points": total_max_points,
            "completed_at": result.completed_at,
            "difficulty_stats": stats,
            "details": details
        }
    
    def get_assignments(self, user_id: int):
        """Получить назначенные тесты"""
        assignments = self.assignment_repo.get_user_assignments(user_id)
        
        result = []
        for assignment in assignments:
            test = self.test_repo.get_test_with_tasks(assignment.test_id)
            
            tasks_count = len(test.tasks) if test else 0
            
            result.append({
                "assignment_id": assignment.id,
                "test_id": assignment.test_id,
                "test_title": test.title if test else "Тест удалён",
                "target_class": test.target_class if test else "",
                "target_topic": test.target_topic if test else "",
                "is_autocompile": test.is_autocompile if test else None,
                "tasks": [{"id": t.id, "content": t.content} for t in (test.tasks if test else [])],
                "assigned_at": assignment.assigned_at,
                "due_date": assignment.due_date,
                "is_completed": assignment.is_completed,
                "completed_at": assignment.completed_at,
                "total_tasks": tasks_count,
                "time_left": str(assignment.due_date -datetime.utcnow()) if assignment.due_date else None
            })
        
        return result
    
    def start_assigned_test(self, test_id: int, user_id: int):
        """Начать выполнение назначенного теста"""
        assignment = self.assignment_repo.get_assignment(test_id, user_id)
        if not assignment:
            raise ValueError("Тест не назначен вам или уже выполнен")
        
        if not self.assignment_repo.check_deadline(assignment):
            raise ValueError("Срок выполнения теста истёк")
        
        test = self.test_repo.get_test_with_tasks(test_id)
        if not test or not test.tasks:
            raise ValueError("Тест не содержит заданий")
        
        result = self.result_repo.create_result(test_id, user_id)
        
        tasks = []
        for task in test.tasks:
            tasks.append({
                "id": task.id,
                "content": task.content,
                "options": task.options,
                "is_open_answer": task.is_open_answer,
                "difficulty": task.difficulty,
            })
        
        return {
            "result_id": result.id,
            "test_title": test.title,
            "tasks": tasks,
            "time_limit": None
        }
    
    def get_ai_hint(self, task_id: int, user_id: int):
        """Получить AI подсказку для задания"""
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Задание не найдено")
        
        topic_mastery = self._calculate_topic_mastery(user_id, task.topic_number)
        
        task_dict = {
            'task_class': task.task_class,
            'topic_number': task.topic_number,
            'topic': task.topic,
            'section': task.section,
            'difficulty': task.difficulty,
            'is_open_answer': task.is_open_answer,
            'content': task.content,
            'options': task.options,
            'same_topic_total': topic_mastery['total'],
            'same_topic_correct': topic_mastery['correct']
        }
        
        hint = self.ai_service.get_hint(task_dict, topic_mastery['percentage'])
        
        return {
            "task_id": task_id,
            "hint": hint,
            "context": {
                "task_class": task.task_class,
                "topic_number": task.topic_number,
                "difficulty": task.difficulty,
                "topic_mastery_percent": topic_mastery['percentage']
            }
        }
    
    def get_ai_solution(self, task_id: int, user_id: int):
        """Получить AI решение задачи"""
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Задание не найдено")
        
        topic_mastery = self._calculate_topic_mastery(user_id, task.topic_number)
        
        task_dict = {
            'task_class': task.task_class,
            'topic_number': task.topic_number,
            'topic': task.topic,
            'section': task.section,
            'difficulty': task.difficulty,
            'is_open_answer': task.is_open_answer,
            'content': task.content,
            'options': task.options,
            'same_topic_total': topic_mastery['total'],
            'same_topic_correct': topic_mastery['correct']
        }
        
        ai_solution = self.ai_service.get_solution(task_dict, topic_mastery['percentage'])
        
        # Извлечение ответа ИИ
        answer_pattern = r'=== ОТВЕТ ===\s*(.+?)(?:\n|$)'
        match = re.search(answer_pattern, ai_solution, re.IGNORECASE)
        
        if not match:
            return {
                "task_id": task_id,
                "success": False,
                "message": "Решение ИИ не найдено (нет маркера '=== ОТВЕТ ===')",
                "ai_solution": ai_solution,
                "verified": False
            }
        
        ai_answer = match.group(1).strip()
        is_correct = self._verify_answer(ai_answer, task.answer)
        
        return {
            "task_id": task_id,
            "success": True,
            "verified": is_correct,
            "message": "Решение найдено и проверено. Ответ совпадает." if is_correct else "Решение найдено, но ответ не совпадает с правильным.",
            "ai_solution": ai_solution,
            "ai_answer": ai_answer,
            "correct_answer": task.answer,
            "context": {
                "task_class": task.task_class,
                "topic_number": task.topic_number,
                "difficulty": task.difficulty,
                "topic_mastery_percent": topic_mastery['percentage']
            }
        }
    
    def get_theory_topics(self):
        """Получить все темы теории"""
        topics = self.theory_repo.get_all_topics()
        
        MAIN_TOPICS = {
            'numbers': 'Числа и вычисления',
            'expressions': 'Выражения и их преобразования',
            'equations': 'Уравнения и неравенства',
            'functions': 'Координаты и функции',
            'geometry': 'Геометрия'
        }
        
        result = []
        for topic in topics:
            if topic[0]:
                result.append({
                    "topic": topic[0],
                    "label": MAIN_TOPICS.get(topic[0], topic[0]),
                    "sections_count": self.theory_repo.get_theory_sections_count(topic[0])
                })
        
        return result
    
    def get_theory_by_topic(self, topic: str):
        """Получить теорию по теме"""
        theories = self.theory_repo.get_theory_by_topic(topic)
        if not theories:
            raise ValueError(f"Теория для темы '{topic}' не найдена")
        return theories
    
    def ask_ai_about_theory(self, question: str, theory_id: Optional[int] = None, theory_content: str = ""):
        """Задать вопрос ИИ по теории"""
        if not question:
            raise ValueError("Вопрос не может быть пустым")
        
        theory_context = ""
        topic_name = ""
        section_name = ""
        
        if theory_id:
            theory = self.theory_repo.get_theory_by_id(theory_id)
            if theory:
                theory_context = theory.content or ""
                topic_name = theory.topic or ""
                section_name = theory.section or ""
        elif theory_content:
            theory_context = theory_content
        else:
            raise ValueError("Не указан theory_id или theory_content")
        
        answer = self.ai_service.get_theory_answer(question, theory_context, topic_name, section_name)
        
        return {
            "success": True,
            "question": question,
            "answer": answer,
            "context": {
                "topic": topic_name,
                "section": section_name
            }
        }
    
    def generate_ai_test(self, user_id: int, prompt: str, task_count: int, difficulty: Optional[str] = None):
        """Сгенерировать тест с помощью AI"""
        
        # Шаг 1: AI определяет темы и разделы
        structure_data = self.task_repo.get_tasks_structure()
        
        topics_structure = {}
        for topic, section in structure_data:
            if topic not in topics_structure:
                topics_structure[topic] = set()
            if section:
                topics_structure[topic].add(section)
        
        detected_topics = self.ai_service.classify_topics(prompt, topics_structure)
        
        # Если AI ничего не определил - случайный тест
        if not detected_topics:
            return self._generate_random_test(user_id, prompt, task_count, difficulty)
        
        # Шаг 2: Фильтрация заданий
        difficulty_map = {
            "easy": [1, 2],
            "medium": [2, 3, 4],
            "hard": [4, 5]
        }
        
        target_difficulties = difficulty_map.get(difficulty, [1, 2, 3, 4, 5]) if difficulty else [1, 2, 3, 4, 5]
        
        # Извлекаем темы и секции
        topic_names = []
        sections_map = {}
        
        for item in detected_topics:
            topic_name = item.get("name")
            sections = item.get("sections", [])
            if topic_name:
                topic_names.append(topic_name)
                sections_map[topic_name] = sections
        
        # Фильтруем задания
        if len(topic_names) >= 3:
            filtered_tasks = self._get_tasks_with_distribution(topic_names, sections_map, target_difficulties, task_count)
        else:
            filtered_tasks = self.task_repo.get_tasks_by_topics(topic_names, sections_map, target_difficulties)
        
        # Fallback: поиск по ключевым словам
        if not filtered_tasks:
            keywords = [w for w in re.sub(r'[^\w\s]', '', prompt).split() if len(w) > 3]
            if keywords:
                filtered_tasks = self.task_repo.get_tasks_by_keywords(keywords, target_difficulties)
        
        # Финальный fallback
        if not filtered_tasks:
            filtered_tasks = self.task_repo.get_random_tasks(300, None, target_difficulties)
        
        if not filtered_tasks:
            raise ValueError("Нет доступных заданий")
        
        # Шаг 3: AI выбирает лучшие задания
        tasks_for_ai = []
        topic_stats = {}
        
        for task in filtered_tasks:
            tasks_for_ai.append(
                f"ID:{task.id} | Тема:{task.topic or 'Н/Д'} | Раздел:{task.section or 'Н/Д'} | "
                f"Сложность:{task.difficulty or 'Н/Д'} | Тип:{'открытый' if task.is_open_answer else 'закрытый'} | "
                f"Содержание:{(task.content or '')[:300]}..."
            )
            
            t = task.topic or "Н/Д"
            topic_stats[t] = topic_stats.get(t, 0) + 1
        
        selected_ids = self.ai_service.select_tasks(
            prompt, tasks_for_ai, task_count, 
            difficulty or "Любая (Рататуй 🍲)", 
            len(topic_names), topic_stats
        )
        
        # Шаг 4: Загружаем выбранные задания
        if selected_ids:
            selected_tasks = self.task_repo.get_tasks_by_ids(selected_ids)
            
            # Добираем если нужно
            if len(selected_tasks) < task_count:
                remaining_ids = [t.id for t in filtered_tasks if t.id not in selected_ids]
                if remaining_ids:
                    needed = task_count - len(selected_tasks)
                    extra_ids = self._distribute_remaining_tasks(filtered_tasks, remaining_ids, needed)
                    if extra_ids:
                        extra_tasks = self.task_repo.get_tasks_by_ids(extra_ids)
                        selected_tasks.extend(extra_tasks)
        else:
            selected_tasks = random.sample(filtered_tasks, min(task_count, len(filtered_tasks)))
        
        # Шаг 5: Создаем тест
        sorted_tasks = self._sort_tasks(selected_tasks)
        
        topics_used = list(set([t.topic for t in selected_tasks if t.topic]))
        title_topics = ", ".join(topics_used[:3])
        if len(topics_used) > 3:
            title_topics += f" и ещё {len(topics_used)-3} тем"
        
        if not title_topics:
            title_topics = "Умный подбор"
        
        test_data = {
            "title": f"AI: {title_topics}",
            "target_class": None,
            "target_topic": prompt[:47],
            "is_autocompile": False,
            "is_ai_generated": True,
            "creator_id": user_id,
            "is_active": True
        }
        
        return self.test_repo.create_test(test_data, sorted_tasks)
    
    def _check_answer(self, task, user_answer) -> bool:
        """Проверить правильность ответа"""
        if not task.is_open_answer and isinstance(user_answer, list):
            correct_answers = {a.strip().lower() for a in task.answer.split(',')}
            student_answers = {str(a).strip().lower() for a in user_answer}
            return correct_answers == student_answers
        else:
            return str(user_answer).strip().lower() == str(task.answer).strip().lower()
    
    def _calculate_topic_mastery(self, user_id: int, topic_number: int) -> dict:
        """Рассчитать уровень освоения темы"""
        answers = self.result_repo.get_user_results_for_topic(user_id, topic_number)
        
        total = len(answers)
        correct = sum(1 for a in answers if a.is_correct)
        percentage = round((correct / total) * 100) if total > 0 else None
        
        return {
            "total": total,
            "correct": correct,
            "percentage": percentage
        }
    
    def _verify_answer(self, ai_answer: str, correct_answer: str) -> bool:
        """Сверить ответ ИИ с правильным"""
        if not correct_answer:
            return False
        
        def normalize(text):
            if not text:
                return ""
            result = text.lower().strip()
            result = result.replace(' ', '')
            result = result.replace('(', '')
            result = result.replace(')', '')
            result = result.replace('.', '')
            result = result.replace(',', '')
            return result
        
        return normalize(ai_answer) == normalize(correct_answer)
    
    def _generate_random_test(self, user_id: int, prompt: str, task_count: int, difficulty: Optional[str]):
        """Сгенерировать случайный тест"""
        total_tasks = task_count
        open_count = random.randint(0, total_tasks)
        closed_count = total_tasks - open_count
        
        difficulty_map = {
            "easy": [1, 2],
            "medium": [2, 3, 4],
            "hard": [4, 5]
        }
        
        target_difficulties = difficulty_map.get(difficulty, [1, 2, 3, 4, 5]) if difficulty else [1, 2, 3, 4, 5]
        
        open_tasks = self.task_repo.get_random_tasks(open_count, True, target_difficulties) if open_count > 0 else []
        closed_tasks = self.task_repo.get_random_tasks(closed_count, False, target_difficulties) if closed_count > 0 else []
        
        selected_tasks = closed_tasks + open_tasks
        
        if len(selected_tasks) < total_tasks:
            remaining = total_tasks - len(selected_tasks)
            existing_ids = [t.id for t in selected_tasks]
            extra_tasks = self.task_repo.get_random_tasks(remaining, None, target_difficulties)
            extra_tasks = [t for t in extra_tasks if t.id not in existing_ids]
            selected_tasks.extend(extra_tasks)
        
        sorted_tasks = self._sort_tasks(selected_tasks)
        
        test_data = {
            "title": f"AI: Случайный тест ({difficulty or 'Любая'})",
            "target_class": None,
            "target_topic": prompt[:255],
            "is_autocompile": False,
            "is_ai_generated": True,
            "creator_id": user_id,
            "is_active": True
        }
        
        return self.test_repo.create_test(test_data, sorted_tasks)
    
    def _get_tasks_with_distribution(self, topics: List[str], sections_map: dict, 
                                    difficulties: List[int], task_count: int):
        """Получить задания с распределением по темам"""
        MAX_PER_TOPIC = 100
        BUFFER_MULTIPLIER = 3
        
        total_needed = task_count * BUFFER_MULTIPLIER
        per_topic_quota = min(MAX_PER_TOPIC, max(10, total_needed // len(topics)))
        
        all_tasks = []
        all_task_ids = set()
        
        for topic, sections in sections_map.items():
            topic_tasks = self.task_repo.get_tasks_by_topics([topic], {topic: sections}, difficulties, per_topic_quota)
            
            for task in topic_tasks:
                if task.id not in all_task_ids:
                    all_task_ids.add(task.id)
                    all_tasks.append(task)
        
        if len(all_tasks) > 300:
            all_tasks = random.sample(all_tasks, 300)
        
        return all_tasks
    
    def _distribute_remaining_tasks(self, filtered_tasks, remaining_ids, needed):
        """Распределить оставшиеся задания по темам"""
        topic_remaining = {}
        for tid in remaining_ids:
            task = next((t for t in filtered_tasks if t.id == tid), None)
            if task:
                t = task.topic or "unknown"
                if t not in topic_remaining:
                    topic_remaining[t] = []
                topic_remaining[t].append(tid)
        
        extra_ids = []
        topics_list = list(topic_remaining.keys())
        
        while len(extra_ids) < needed and topics_list:
            for topic in topics_list:
                if len(extra_ids) >= needed:
                    break
                if topic_remaining[topic]:
                    extra_ids.append(topic_remaining[topic].pop())
                else:
                    topics_list.remove(topic)
        
        return extra_ids
    
    def _sort_tasks(self, tasks):
        """Отсортировать задания: сначала закрытые по сложности, потом открытые"""
        closed = sorted([t for t in tasks if not t.is_open_answer], key=lambda t: t.difficulty or 0)
        open_tasks = sorted([t for t in tasks if t.is_open_answer], key=lambda t: t.difficulty or 0)
        return closed + open_tasks