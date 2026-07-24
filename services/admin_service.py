import os
import uuid
import base64
import re
import httpx
import boto3
from botocore.config import Config
from typing import List
from sqlalchemy.orm import joinedload
from repositories.user_repository import UserRepository
from repositories.task_repository import TaskRepository
from repositories.test_repository import TestRepository
from repositories.result_repository import ResultRepository
from repositories.assignment_repository import AssignmentRepository
from repositories.group_repository import GroupRepository
from repositories.teacher_student_repository import TeacherStudentRepository
from repositories.allowed_email_repository import AllowedEmailRepository
from repositories.theory_repository import TheoryRepository
from core.models import Task, Test, TestResult, UserAnswer, TestAssignment, TestTaskAssociation, UserRole

from dto_schemas.user import UserResponse, MessageResponse
from dto_schemas.stats import UserResponseWithStats, UserStats
from dto_schemas.image import ImageUploadResponse
from dto_schemas.admin import AllowedEmailItemResponse, RebuildTestsResponse, RecomputeAnswersResponse
from dto_schemas.cached import (
    DetailedResultResponse,
    DetailedResultDetailResponse,
    DifficultyStatResponse,
    ResultUserResponse,
    TeacherHistoryItemResponse,
    TeacherHistoryResultResponse,
)




class AdminService:
    def __init__(self, db):
        self.user_repo = UserRepository(db)
        self.task_repo = TaskRepository(db)
        self.test_repo = TestRepository(db)
        self.result_repo = ResultRepository(db)
        self.assignment_repo = AssignmentRepository(db)
        self.group_repo = GroupRepository(db)
        self.teacher_student_repo = TeacherStudentRepository(db)
        self.allowed_email_repo = AllowedEmailRepository(db)
        self.theory_repo = TheoryRepository(db)
        self.db = db
    
    # ==================== ПОЛЬЗОВАТЕЛИ ====================
    
    def get_users(self):
        users = self.user_repo.get_all_users()
        student_ids = [u.id for u in users if u.role == "student"]
        
        teacher_links = {}
        if student_ids:
            links = self.teacher_student_repo.get_links_by_student_ids(student_ids)
            teacher_ids = [link.teacher_id for link in links]
            teachers = self.user_repo.get_teachers_by_ids(teacher_ids)
            teachers_dict = {t.id: t for t in teachers}
            
            for link in links:
                teacher = teachers_dict.get(link.teacher_id)
                if teacher:
                    teacher_links[link.student_id] = {
                        "first_name": teacher.first_name,
                        "last_name": teacher.last_name,
                    }
        
        result = []
        for user in users:
            user_data = {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
                "tg_username": user.tg_username,
                "phone": user.phone,
                "role": user.role,
                "teacher": teacher_links.get(user.id) if user.role == "student" else None
            }
            result.append(user_data)
        
        return result
    
    def delete_user(self, user_id: int, admin_id: int):
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        if user.id == admin_id:
            raise ValueError("Нельзя удалить самого себя")
        
        # Каскадное удаление через репозитории
        self.teacher_student_repo.delete_links_by_user(user_id)
        self.group_repo.delete_groups_by_teacher(user_id)
        self.group_repo.delete_student_from_all_groups(user_id)
        
        # Удаление ответов и результатов
        result_ids = self.result_repo.get_result_ids_by_user(user_id)
        if result_ids:
            self.result_repo.delete_answers_by_result_ids(result_ids)
            self.result_repo.delete_results_by_user(user_id)
        
        self.assignment_repo.delete_assignments_by_user(user_id)
        
        # Удаление тестов учителя
        test_ids = self.test_repo.get_test_ids_by_creator(user_id)
        if test_ids:
            self.test_repo.delete_tests_by_ids(test_ids)
        
        self.user_repo.delete_user(user)
        return MessageResponse(message="Пользователь и все связанные данные удалены")
    
    def get_user_profile(self, user_id: int):
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        stats = self.user_repo.get_user_stats(user_id)
        
        return UserResponseWithStats(
            user=user,
            stats=UserStats(
                total_attempts=stats.get("total_attempts", 0),
                avg_score=stats.get("avg_score", 0.0),
            ),
        )
    
    def get_user_history(self, user_id: int):
        results = self.result_repo.get_user_history(user_id)
        return [
            TeacherHistoryItemResponse(
                test_title=r.test.title if r.test else "Тест удален",
                result=TeacherHistoryResultResponse(
                    id=r.id,
                    total_points=r.total_points,
                    completed_at=r.completed_at,
                ),
            )
            for r in results
        ]
    
    # ==================== ЗАДАНИЯ ====================
    
    def create_task(self, task_data: dict):
        return self.task_repo.create_task(task_data)
    
    def change_user_role(self, user_id: int, new_role: str, admin_id: int):
        try:
            UserRole(new_role)
        except ValueError:
            raise ValueError(f"Недопустимая роль: {new_role}. Допустимые: admin, teacher, student")
        
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        if user.id == admin_id and new_role != "admin":
            raise ValueError("Вы не можете снять роль админа с самого себя")
        
        self.user_repo.update_user_role(user, new_role)
        return MessageResponse(message=f"Роль пользователя {user.username} изменена на {new_role}")
    
    def update_task(self, task_id: int, update_data: dict):
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Задание не найдено")

        # Обновляем атрибуты (без коммита)
        for key, value in update_data.items():
            setattr(task, key, value)

        self.db.flush()  # сохраняем изменения в БД, но не коммитим

        # Пересчитываем ответы и результаты для этого задания
        recompute_stats = self._recompute_answers_for_task(task)

        self.db.commit()

        return task
    
    def get_tasks(self):
        return self.task_repo.get_all_tasks()
    
    def get_task(self, task_id: int):
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Task not found")
        return task
    
    def delete_task(self, task_id: int):
        if not self.task_repo.get_task_by_id(task_id):
            raise ValueError("Задание не найдено")
        self.task_repo.delete_task(task_id)
        return MessageResponse(message=f"Задание с ID {task_id} и связанные данные успешно удалены")
    
    def get_detailed_result(self, result_id: int):
        result = self.result_repo.get_result_by_id(result_id)
        if not result:
            raise ValueError("Результат не найден")
        
        all_tasks = self.task_repo.get_tasks_by_test_id(result.test_id)
        user_answers = self.result_repo.get_user_answers_for_result(result_id)
        answers_map = {ua.task_id: ua for ua in user_answers}
        
        details = []
        total_max_points = 0
        difficulty_stats: dict[str, DifficultyStatResponse] = {}
        
        for task in all_tasks:
            ua = answers_map.get(task.id)
            is_correct = ua.is_correct if ua else False
            
            diff_level = str(task.difficulty) if task.difficulty else "1"
            
            if diff_level not in difficulty_stats:
                difficulty_stats[diff_level] = DifficultyStatResponse(total=0, correct=0)
            
            difficulty_stats[diff_level].total += 1
            if is_correct:
                difficulty_stats[diff_level].correct += 1
            
            max_task_points = 2 if task.is_open_answer else 1
            total_max_points += max_task_points
            
            details.append(DetailedResultDetailResponse(
                task_id=task.id,
                content=task.content,
                options=task.options,
                difficulty=diff_level,
                correct_answer=task.answer,
                user_answer=ua.user_text_answer if ua else "Нет ответа",
                is_correct=is_correct,
                points_earned=ua.points_earned if ua else 0,
                max_task_points=max_task_points,
                solution=task.solution,
                hint=task.hint,
            ))
        
        return DetailedResultResponse(
            test_title=result.test.title,
            total_points=result.total_points,
            max_points=total_max_points,
            completed_at=result.completed_at,
            difficulty_stats=difficulty_stats,
            user=ResultUserResponse(
                first_name=result.user.first_name,
                last_name=result.user.last_name,
            ),
            details=details,
        )
    
    # ==================== РАЗРЕШЁННЫЕ EMAIL ====================
    
    def get_allowed_emails(self):
        allowed_emails = self.allowed_email_repo.get_all()
        
        result = []
        for ae in allowed_emails:
            user = self.user_repo.get_user_by_email(ae.email)
            
            result.append(AllowedEmailItemResponse(
                email=ae.email,
                first_name=user.first_name if user else None,
                last_name=user.last_name if user else None,
                tg_username=user.tg_username if user else None,
            ))
        
        return result
    
    def add_allowed_email(self, email: str):
        if not email:
            raise ValueError("Email is required")
        
        exists = self.allowed_email_repo.get_by_email(email)
        if exists:
            raise ValueError("Email уже в списке")
        
        return self.allowed_email_repo.create(email)
    
    def delete_allowed_email(self, email: str):
        allowed = self.allowed_email_repo.get_by_email(email)
        if not allowed:
            raise ValueError("Email не найден")
        
        self.allowed_email_repo.delete(allowed)
        return {"status": "ok", "message": f"Доступ для {email} аннулирован"}
    
    # ==================== НАЗНАЧЕНИЕ УЧИТЕЛЕЙ ====================
    
    def assign_student_to_teacher(self, teacher_id: int, student_id: int):
        teacher = self.user_repo.get_user_by_id(teacher_id)
        if not teacher or teacher.role not in ["teacher", "admin"]:
            raise ValueError("Учитель не найден")
        
        student = self.user_repo.get_user_by_id(student_id)
        if not student or student.role != "student":
            raise ValueError("Ученик не найден")
        
        self.teacher_student_repo.create_link(teacher_id, student_id)
        self.db.commit()
        
        return MessageResponse(message=f"Ученик {student.username} назначен учителю {teacher.username}")
    
    def remove_student_from_teacher(self, student_id: int):
        if not self.teacher_student_repo.delete_link_by_student(student_id):
            raise ValueError("Связь не найдена")
        
        self.db.commit()
        return MessageResponse(message="Связь удалена")
    
    # ==================== ТЕОРИЯ ====================
    
    def create_theory(self, theory_data: dict):
        topic = theory_data.get("topic")
        section = theory_data.get("section")
        
        existing = self.theory_repo.get_theory_by_topic_and_section(topic, section)
        if existing:
            raise ValueError(f"Теория для темы '{topic}' и раздела '{section}' уже существует")
        
        return self.theory_repo.create_theory(theory_data)
    
    def get_all_theory(self):
        return self.theory_repo.get_all_theory()
    
    def get_theory_by_id(self, theory_id: int):
        theory = self.theory_repo.get_theory_by_id(theory_id)
        if not theory:
            raise ValueError("Теория не найдена")
        return theory
    
    def update_theory(self, theory_id: int, update_data: dict):
        theory = self.theory_repo.get_theory_by_id(theory_id)
        if not theory:
            raise ValueError("Теория не найдена")
        
        return self.theory_repo.update_theory(theory, update_data)
    
    def delete_theory(self, theory_id: int):
        theory = self.theory_repo.get_theory_by_id(theory_id)
        if not theory:
            raise ValueError("Теория не найдена")
        
        self.theory_repo.delete_theory(theory)
        return MessageResponse(message=f"Теория для темы '{theory.topic}' и раздела '{theory.section}' успешно удалена")
    
    # ==================== ЗАГРУЗКА ИЗОБРАЖЕНИЙ ====================
    
    def upload_image(self, image_data: str):
        if not image_data:
            raise ValueError("Missing image data")
        
        # Настройка R2
        s3_client = boto3.client(
            's3',
            endpoint_url=os.getenv("R2_ENDPOINT_URL"),
            aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            region_name='auto',
            config=Config(signature_version='s3v4')
        )
        
        if "," in image_data:
            image_base64 = image_data.split(",")[1]
        else:
            image_base64 = image_data
        
        image_bytes = base64.b64decode(image_base64)
        
        filename = f"tasks/{uuid.uuid4().hex}.png"
        
        s3_client.put_object(
            Bucket=os.getenv("R2_BUCKET_NAME"),
            Key=filename,
            Body=image_bytes,
            ContentType='image/png',
            CacheControl='max-age=31536000'
        )
        
        file_url = f"{os.getenv('R2_PUBLIC_URL')}/{filename}"
        
        return ImageUploadResponse(
            url=file_url,
            filename=filename,
            size=len(image_bytes),
        )
    
    # ==================== ОТПРАВКА В TELEGRAM ====================
    
    async def send_task_to_tg(self, task_id: int, chat_id: str):
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Задание не найдено")
        
        # Логика вариантов ответов
        render_options = []
        correct_option_ids = []
        is_quiz = not task.is_open_answer
        
        if is_quiz and task.options:
            if isinstance(task.options, list):
                render_options = [str(opt).strip() for opt in task.options]
            elif isinstance(task.options, dict):
                render_options = [str(val).strip() for val in task.options.values()]
            
            correct_option_ids = self._parse_correct_option_ids(task.answer, render_options)
        
        if is_quiz and len(render_options) < 2:
            is_quiz = False
        
        diff = int(task.difficulty) if task.difficulty else 1
        
        meta_info = f"{task.task_class} | {task.topic_number}"
        if task.section:
            meta_info += f"\n📂 Раздел: {task.section}"
        if task.topic:
            meta_info += f"\n📖 Тема: {task.topic}"
        
        telegram_caption = (
            f"{meta_info}\n"
            f"🔥 Сложность: {diff}\n"
            f"🆔 ID задачи: {task.id}"
        )
        
        render_payload = {
            "chat_id": chat_id,
            "latex": task.content.strip(),
            "caption": telegram_caption,
            "is_quiz": is_quiz,
            "options": render_options,
            "correct_option_ids": correct_option_ids,
            "difficulty": task.difficulty,
            "answer": str(task.answer).strip() if task.answer else ""
        }
        
        BASE_URL = os.getenv("RENDER_API_URL", "http://localhost:8000")
        
        if BASE_URL.endswith("/send_math"):
            RENDER_API_URL = BASE_URL
        else:
            RENDER_API_URL = f"{BASE_URL.rstrip('/')}/send_math"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    RENDER_API_URL,
                    json=render_payload,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    raise Exception(f"Ошибка рендер-бота: {response.text}")
                
                return MessageResponse(message="Задача успешно отправлена в Telegram")
                
            except httpx.RequestError as e:
                raise Exception(f"Не удалось связаться с рендер-ботом: {str(e)}")
    
    def rebuild_all_static_tests(self, admin_id: int):
        """
        🔄 Пересобрать статические (автособранные) тесты.
        """
        try:
            # ========== 1. Собираем актуальные категории из задач ==========
            active_categories = self.db.query(
                Task.task_class, 
                Task.topic_number
            ).distinct().all()
            
            updated_test_ids = []

            for t_class, t_num in active_categories:
                t_class_str = str(t_class)
                t_num_str = str(t_num)
                
                test = self.db.query(Test).filter(
                    Test.target_class == t_class_str,
                    Test.target_topic == t_num_str,
                    Test.is_autocompile == True,
                    Test.is_ai_generated == False,
                    Test.creator_id == admin_id
                ).first()

                if not test:
                    test = Test(
                        title=f"Тест: {t_class_str} класс, Тема {t_num_str}",
                        target_class=t_class_str,
                        target_topic=t_num_str,
                        is_autocompile=True,
                        is_ai_generated=False,
                        creator_id=admin_id,
                        is_active=True
                    )
                    self.db.add(test)
                    self.db.flush()

                relevant_tasks = self.db.query(Task).filter(
                    Task.task_class == t_class,
                    Task.topic_number == t_num
                ).order_by(
                    Task.is_open_answer.asc(),
                    Task.difficulty.asc()
                ).all()

                test.tasks = relevant_tasks
                updated_test_ids.append(test.id)

            self.db.flush()

            # ========== 2. Удаляем старые автотесты админа ==========
            deleted_count = 0
            if updated_test_ids:
                bad_tests_query = self.db.query(Test.id).filter(
                    Test.id.not_in(updated_test_ids),
                    Test.is_autocompile == True,
                    Test.is_ai_generated == False,
                    Test.creator_id == admin_id
                )

                empty_tests = self.db.query(Test.id).filter(
                    ~Test.tasks.any(),
                    Test.id.not_in(updated_test_ids),
                    Test.is_autocompile == True,
                    Test.is_ai_generated == False,
                    Test.creator_id == admin_id
                ).all()

                bad_test_ids = [t[0] for t in bad_tests_query.all()]
                bad_test_ids.extend([t[0] for t in empty_tests])
                bad_test_ids = list(set(bad_test_ids))

                if bad_test_ids:
                    bad_result_ids = [
                        r[0] for r in self.db.query(TestResult.id)
                        .filter(TestResult.test_id.in_(bad_test_ids))
                        .all()
                    ]

                    if bad_result_ids:
                        self.db.query(UserAnswer).filter(
                            UserAnswer.result_id.in_(bad_result_ids)
                        ).delete(synchronize_session=False)
                        
                        self.db.query(TestResult).filter(
                            TestResult.id.in_(bad_result_ids)
                        ).delete(synchronize_session=False)

                    self.db.query(TestTaskAssociation).filter(
                        TestTaskAssociation.test_id.in_(bad_test_ids)
                    ).delete(synchronize_session=False)

                    self.db.query(TestAssignment).filter(
                        TestAssignment.test_id.in_(bad_test_ids)
                    ).delete(synchronize_session=False)

                    deleted_count = self.db.query(Test).filter(
                        Test.id.in_(bad_test_ids)
                    ).delete(synchronize_session=False)

            self.db.commit()
            
            return RebuildTestsResponse(
                status="success",
                message=(
                    f"Успешно синхронизировано {len(updated_test_ids)} тестов. "
                    f"Удалено устаревших автотестов: {deleted_count}."
                ),
                updated_test_ids=updated_test_ids,
                deleted_count=deleted_count,
            )

        except Exception as e:
            self.db.rollback()
            raise Exception(f"Database Error: {str(e)}")
        
    def _recompute_answers_for_task(self, task: Task):
        """
        Пересчитывает правильность и баллы для всех UserAnswer, привязанных к task,
        и обновляет total_points в соответствующих TestResult.
        Возвращает статистику: сколько обновлено ответов и результатов.
        """
        if not task:
            return RecomputeAnswersResponse(answers_updated=0, results_updated=0)

        # Получаем все ответы на это задание
        user_answers = self.db.query(UserAnswer).filter(
            UserAnswer.task_id == task.id
        ).all()

        if not user_answers:
            return RecomputeAnswersResponse(answers_updated=0, results_updated=0)

        result_ids = set()
        answers_updated = 0

        for ua in user_answers:
            # Определяем, правильный ли ответ сейчас
            is_correct_now = False
            user_ans_str = str(ua.user_text_answer).strip().lower() if ua.user_text_answer else ""
            task_ans_str = str(task.answer).strip().lower() if task.answer else ""

            if user_ans_str and task_ans_str:
                # Для закрытых заданий (is_open_answer=False) сравниваем с эталоном
                # Для открытых – точное совпадение (можно усложнить, но пока так)
                is_correct_now = (user_ans_str == task_ans_str)

            # Вычисляем баллы: 2 за открытый правильный, 1 за закрытый правильный, иначе 0
            new_points = 0
            if is_correct_now:
                new_points = 2 if task.is_open_answer else 1

            if ua.is_correct != is_correct_now or ua.points_earned != new_points:
                ua.is_correct = is_correct_now
                ua.points_earned = new_points
                answers_updated += 1
                result_ids.add(ua.result_id)

        # Обновляем total_points для всех затронутых результатов
        results_updated = 0
        if result_ids:
            from sqlalchemy.orm import joinedload
            results = self.db.query(TestResult).options(
                joinedload(TestResult.answers)
            ).filter(TestResult.id.in_(list(result_ids))).all()

            for result in results:
                new_total = sum(ans.points_earned for ans in result.answers)
                if result.total_points != new_total:
                    result.total_points = new_total
                    results_updated += 1

        return RecomputeAnswersResponse(answers_updated=answers_updated, results_updated=results_updated)

