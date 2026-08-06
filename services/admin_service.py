import os
import uuid
import base64
import re
import json
import asyncio
import datetime
import httpx
import boto3
from botocore.config import Config
from typing import List, Optional
import logging
from sqlalchemy import select, delete, update
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession
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
from dto_schemas.admin import AllowedEmailItemResponse, RebuildTestsResponse, RecomputeAnswersResponse, ClassifyTasksResponse
from dto_schemas.cached import (
    DetailedResultResponse,
    DetailedResultDetailResponse,
    DifficultyStatResponse,
    ResultUserResponse,
    TeacherHistoryItemResponse,
    TeacherHistoryResultResponse,
    TeacherTaskMetaResponse,
    TeacherTaskMetaByTopicSectionResponse,
    TeacherTaskDetailResponse,
)

logger = logging.getLogger(__name__)


class PermissionError(Exception):
    """Ошибка доступа."""
    pass


class AdminService:
    def __init__(self, db: AsyncSession):
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
    
    async def get_users(self):
        users = await self.user_repo.get_all_users()
        student_ids = [u.id for u in users if u.role == "student"]
        
        teacher_links = {}
        if student_ids:
            links = await self.teacher_student_repo.get_links_by_student_ids(student_ids)
            teacher_ids = [link.teacher_id for link in links]
            teachers = await self.user_repo.get_teachers_by_ids(teacher_ids)
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
    
    async def delete_user(self, user_id: int, admin_id: int):
        user = await self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        if user.id == admin_id:
            raise ValueError("Нельзя удалить самого себя")
        
        # Каскадное удаление через репозитории
        await self.teacher_student_repo.delete_links_by_user(user_id)
        await self.group_repo.delete_groups_by_teacher(user_id)
        await self.group_repo.delete_student_from_all_groups(user_id)
        
        # Удаление ответов и результатов
        result_ids = await self.result_repo.get_result_ids_by_user(user_id)
        if result_ids:
            await self.result_repo.delete_answers_by_result_ids(result_ids)
            await self.result_repo.delete_results_by_user(user_id)
        
        await self.assignment_repo.delete_assignments_by_user(user_id)
        
        # Удаление тестов учителя
        test_ids = await self.test_repo.get_test_ids_by_creator(user_id)
        if test_ids:
            await self.test_repo.delete_tests_by_ids(test_ids)
        
        await self.user_repo.delete_user(user)
        await self.db.commit()
        return MessageResponse(message="Пользователь и все связанные данные удалены")
    
    async def get_user_profile(self, user_id: int):
        user = await self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        stats = await self.user_repo.get_user_stats(user_id)
        
        return UserResponseWithStats(
            user=user,
            stats=UserStats(
                total_attempts=stats.get("total_attempts", 0),
                avg_score=stats.get("avg_score", 0.0),
            ),
        )
    
    async def get_user_history(self, user_id: int):
        results = await self.result_repo.get_user_history(user_id)
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
    
    async def create_task(self, task_data: dict):
        return await self.task_repo.create_task(task_data)
    
    async def change_user_role(self, user_id: int, new_role: str, admin_id: int):
        try:
            UserRole(new_role)
        except ValueError:
            raise ValueError(f"Недопустимая роль: {new_role}. Допустимые: admin, teacher, student")
        
        user = await self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        if user.id == admin_id and new_role != "admin":
            raise ValueError("Вы не можете снять роль админа с самого себя")
        
        await self.user_repo.update_user_role(user, new_role)
        await self.db.commit()
        return MessageResponse(message=f"Роль пользователя {user.username} изменена на {new_role}")
    
    async def update_task(self, task_id: int, update_data: dict):
        task = await self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Задание не найдено")

        # Обновляем атрибуты
        for key, value in update_data.items():
            setattr(task, key, value)

        await self.db.flush()

        # Пересчитываем ответы и результаты для этого задания
        recompute_stats = await self._recompute_answers_for_task(task)

        await self.db.commit()

        return task
    
    async def get_tasks(self):
        return await self.task_repo.get_all_tasks()
    
    async def get_task(self, task_id: int):
        task = await self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Task not found")
        return task
    
    async def delete_task(self, task_id: int):
        if not await self.task_repo.get_task_by_id(task_id):
            raise ValueError("Задание не найдено")
        await self.task_repo.delete_task(task_id)
        await self.db.commit()
        return MessageResponse(message=f"Задание с ID {task_id} и связанные данные успешно удалены")

    # ==================== ПАКЕТНЫЕ ОПЕРАЦИИ С ЗАДАНИЯМИ ====================

    async def create_tasks_batch(self, tasks_data: list[dict]) -> dict:
        """Пакетное создание заданий"""
        created = await self.task_repo.bulk_create_tasks(tasks_data)
        await self.db.commit()
        return {
            "created": created,
            "total": len(created),
        }

    async def update_tasks_batch(self, tasks_data: list[dict]) -> dict:
        """Пакетное обновление заданий"""
        # Группируем обновления по id
        updates: dict[int, dict] = {}
        all_ids = []
        for item in tasks_data:
            task_id = item.pop("id")
            all_ids.append(task_id)
            # Убираем None-значения, чтобы не перезаписывать поля
            updates[task_id] = {k: v for k, v in item.items() if v is not None}

        # Получаем существующие задания
        existing = await self.task_repo.get_tasks_by_ids(all_ids)
        existing_ids = {t.id for t in existing}
        not_found = [tid for tid in all_ids if tid not in existing_ids]

        # Обновляем
        updated = await self.task_repo.bulk_update_tasks(updates)

        # Пересчитываем ответы для каждого обновлённого задания
        for task in updated:
            await self._recompute_answers_for_task(task)

        await self.db.commit()
        return {
            "updated": updated,
            "not_found": not_found,
            "total_updated": len(updated),
        }

    async def delete_tasks_batch(self, task_ids: list[int]) -> dict:
        """Пакетное удаление заданий"""
        # Проверяем существование
        existing = await self.task_repo.get_tasks_by_ids(task_ids)
        existing_ids = {t.id for t in existing}
        not_found = [tid for tid in task_ids if tid not in existing_ids]

        deleted = await self.task_repo.bulk_delete_tasks(list(existing_ids))
        await self.db.commit()
        return {
            "deleted": deleted,
            "not_found": not_found,
            "total_deleted": len(deleted),
        }
    
    async def get_detailed_result(self, result_id: int):
        result = await self.result_repo.get_result_by_id(result_id)
        if not result:
            raise ValueError("Результат не найден")
        
        all_tasks = await self.task_repo.get_tasks_by_test_id(result.test_id)
        user_answers = await self.result_repo.get_user_answers_for_result(result_id)
        answers_map = {ua.task_id: ua for ua in user_answers}
        
        details = []
        total_max_points = 0
        difficulty_stats: dict[str, DifficultyStatResponse] = {}
        
        for task in all_tasks:
            ua = answers_map.get(task.id)
            is_correct = ua.is_correct if ua else False
            
            diff_level = task.difficulty if task.difficulty else 1
            diff_key = str(diff_level)
            
            if diff_key not in difficulty_stats:
                difficulty_stats[diff_key] = DifficultyStatResponse(total=0, correct=0)
            
            difficulty_stats[diff_key].total += 1
            if is_correct:
                difficulty_stats[diff_key].correct += 1
            
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
    
    async def get_allowed_emails(self):
        allowed_emails = await self.allowed_email_repo.get_all()
        
        result = []
        for ae in allowed_emails:
            user = await self.user_repo.get_user_by_email(ae.email)
            
            result.append(AllowedEmailItemResponse(
                email=ae.email,
                first_name=user.first_name if user else None,
                last_name=user.last_name if user else None,
                tg_username=user.tg_username if user else None,
            ))
        
        return result
    
    async def add_allowed_email(self, email: str):
        if not email:
            raise ValueError("Email is required")
        
        exists = await self.allowed_email_repo.get_by_email(email)
        if exists:
            raise ValueError("Email уже в списке")
        
        return await self.allowed_email_repo.create(email)
    
    async def delete_allowed_email(self, email: str):
        allowed = await self.allowed_email_repo.get_by_email(email)
        if not allowed:
            raise ValueError("Email не найден")
        
        await self.allowed_email_repo.delete(allowed)
        await self.db.commit()
        return {"status": "ok", "message": f"Доступ для {email} аннулирован"}
    
    # ==================== НАЗНАЧЕНИЕ УЧИТЕЛЕЙ ====================
    
    async def assign_student_to_teacher(self, teacher_id: int, student_id: int):
        teacher = await self.user_repo.get_user_by_id(teacher_id)
        if not teacher or teacher.role not in ["teacher", "admin"]:
            raise ValueError("Учитель не найден")
        
        student = await self.user_repo.get_user_by_id(student_id)
        if not student or student.role != "student":
            raise ValueError("Ученик не найден")
        
        await self.teacher_student_repo.create_link(teacher_id, student_id)
        await self.db.commit()
        
        return MessageResponse(message=f"Ученик {student.username} назначен учителю {teacher.username}")
    
    async def remove_student_from_teacher(self, student_id: int):
        if not await self.teacher_student_repo.delete_link_by_student(student_id):
            raise ValueError("Связь не найдена")
        
        await self.db.commit()
        return MessageResponse(message="Связь удалена")
    
    # ==================== ТЕОРИЯ ====================
    
    async def create_theory(self, theory_data: dict):
        topic = theory_data.get("topic")
        section = theory_data.get("section")
        
        existing = await self.theory_repo.get_theory_by_topic_and_section(topic, section)
        if existing:
            raise ValueError(f"Теория для темы '{topic}' и раздела '{section}' уже существует")
        
        return await self.theory_repo.create_theory(theory_data)
    
    async def get_all_theory(self):
        return await self.theory_repo.get_all_theory()
    
    async def get_theory_by_id(self, theory_id: int):
        theory = await self.theory_repo.get_theory_by_id(theory_id)
        if not theory:
            raise ValueError("Теория не найдена")
        return theory
    
    async def update_theory(self, theory_id: int, update_data: dict):
        theory = await self.theory_repo.get_theory_by_id(theory_id)
        if not theory:
            raise ValueError("Теория не найдена")
        
        return await self.theory_repo.update_theory(theory, update_data)
    
    async def delete_theory(self, theory_id: int):
        theory = await self.theory_repo.get_theory_by_id(theory_id)
        if not theory:
            raise ValueError("Теория не найдена")
        
        await self.theory_repo.delete_theory(theory)
        await self.db.commit()
        return MessageResponse(message=f"Теория для темы '{theory.topic}' и раздела '{theory.section}' успешно удалена")
    
    # ==================== ЗАГРУЗКА ИЗОБРАЖЕНИЙ ====================
    
    async def upload_image(self, image_data: str):
        if not image_data:
            raise ValueError("Missing image data")
        
        # Настройка R2 (boto3 sync, оборачиваем в поток)
        s3_client = await asyncio.to_thread(
            lambda: boto3.client(
                's3',
                endpoint_url=os.getenv("R2_ENDPOINT_URL"),
                aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
                region_name='auto',
                config=Config(signature_version='s3v4')
            )
        )
        
        if "," in image_data:
            image_base64 = image_data.split(",")[1]
        else:
            image_base64 = image_data
        
        image_bytes = base64.b64decode(image_base64)
        
        filename = f"tasks/{uuid.uuid4().hex}.png"
        
        await asyncio.to_thread(
            s3_client.put_object,
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

    def _parse_correct_option_ids(self, answer: str, options: list[str]) -> list[int]:
        """Parse the correct answer and return indices of matching options (0-based)."""
        answer = str(answer).strip()
        result = []
        for i, opt in enumerate(options):
            if str(opt).strip() == answer:
                result.append(i)
        return result

    async def send_task_to_tg(self, task_id: int, chat_id: str):
        task = await self.task_repo.get_task_by_id(task_id)
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

    async def rebuild_all_static_tests(self, admin_id: int):
        """
        🔄 Пересобрать статические (автособранные) тесты.
        Исправленная версия с явной загрузкой связей.
        """
        try:
            # ========== 1. Загружаем существующие тесты администратора с их задачами ==========
            # Явно загружаем связи tasks через selectinload
            result = await self.db.execute(
                select(Test)
                .options(selectinload(Test.tasks))  # ← Явная загрузка всех задач
                .filter(
                    Test.is_autocompile == True,
                    Test.is_ai_generated == False,
                    Test.creator_id == admin_id
                )
            )
            existing_tests = result.scalars().all()
            
            # Создаем словарь для быстрого поиска тестов по классу и теме
            tests_dict = {}
            for test in existing_tests:
                key = f"{test.target_class}_{test.target_topic}"
                tests_dict[key] = test
            
            # ========== 2. Получаем актуальные категории из задач ==========
            result = await self.db.execute(
                select(Task.task_class, Task.topic_number).distinct()
            )
            active_categories = result.all()
            
            updated_test_ids = []
            new_tests_created = 0

            for t_class, t_num in active_categories:
                t_class_str = str(t_class)
                t_num_str = str(t_num)
                key = f"{t_class_str}_{t_num_str}"
                
                # Проверяем, существует ли уже такой тест
                test = tests_dict.get(key)
                is_new_test = False
                
                if not test:
                    # Создаем новый тест
                    test = Test(
                        title=f"Тест: {t_class_str} класс, Тема {t_num_str}",
                        target_class=t_class_str,
                        target_topic=t_num_str,
                        is_autocompile=True,
                        is_ai_generated=False,
                        creator_id=admin_id,
                        is_active=True,
                    )
                    self.db.add(test)
                    await self.db.flush()  # Получаем ID
                    is_new_test = True
                    new_tests_created += 1
                
                # ========== 3. Получаем актуальные задачи для этой категории ==========
                result = await self.db.execute(
                    select(Task).filter(
                        Task.task_class == t_class,
                        Task.topic_number == t_num
                    ).order_by(
                        Task.is_open_answer.asc(),
                        Task.difficulty.asc()
                    )
                )
                relevant_tasks = result.scalars().all()
                
                # ========== 4. Обновляем связи теста с задачами ==========
                # Удаляем старые ассоциации (без lazy-load триггера)
                if not is_new_test:
                    await self.db.execute(
                        delete(TestTaskAssociation).where(
                            TestTaskAssociation.test_id == test.id))
                
                # Добавляем новые связи через ассоциации
                for task in relevant_tasks:
                    self.db.add(TestTaskAssociation(test_id=test.id, task_id=task.id))
                
                updated_test_ids.append(test.id)

            await self.db.flush()

            # ========== 5. Удаляем старые автотесты админа ==========
            deleted_count = 0
            
            if updated_test_ids:
                # Загружаем все тесты админа, которые НЕ должны существовать
                # с явной загрузкой связей для проверки
                result = await self.db.execute(
                    select(Test)
                    .options(selectinload(Test.tasks))  # ← Явная загрузка
                    .filter(
                        Test.id.not_in(updated_test_ids),
                        Test.is_autocompile == True,
                        Test.is_ai_generated == False,
                        Test.creator_id == admin_id
                    )
                )
                tests_to_check = result.scalars().all()
                
                # Отбираем тесты без задач
                bad_tests = [test for test in tests_to_check if not test.tasks]
                
                # Добавляем тесты без задач из основного списка (если есть дубли)
                # Для этого проверяем все тесты админа
                if not bad_tests:
                    # Если не нашли тесты без задач, проверяем отдельно
                    result = await self.db.execute(
                        select(Test)
                        .options(selectinload(Test.tasks))
                        .filter(
                            Test.is_autocompile == True,
                            Test.is_ai_generated == False,
                            Test.creator_id == admin_id
                        )
                    )
                    all_admin_tests = result.scalars().all()
                    bad_tests = [test for test in all_admin_tests 
                                if test.id not in updated_test_ids and not test.tasks]
                
                # Убираем дубликаты
                bad_test_ids = list(set([test.id for test in bad_tests]))
                
                if bad_test_ids:
                    # ========== 5.1 Удаляем связанные результаты и ответы ==========
                    # Получаем все результаты для удаляемых тестов
                    result = await self.db.execute(
                        select(TestResult.id).filter(
                            TestResult.test_id.in_(bad_test_ids)
                        )
                    )
                    bad_result_ids = [row[0] for row in result.all()]

                    if bad_result_ids:
                        # Удаляем ответы пользователей
                        await self.db.execute(
                            delete(UserAnswer).filter(
                                UserAnswer.result_id.in_(bad_result_ids)
                            )
                        )
                        
                        # Удаляем результаты тестов
                        await self.db.execute(
                            delete(TestResult).filter(
                                TestResult.id.in_(bad_result_ids)
                            )
                        )

                    # ========== 5.2 Удаляем связи тестов с задачами ==========
                    await self.db.execute(
                        delete(TestTaskAssociation).filter(
                            TestTaskAssociation.test_id.in_(bad_test_ids)
                        )
                    )

                    # ========== 5.3 Удаляем назначения тестов ==========
                    await self.db.execute(
                        delete(TestAssignment).filter(
                            TestAssignment.test_id.in_(bad_test_ids)
                        )
                    )

                    # ========== 5.4 Удаляем сами тесты ==========
                    result = await self.db.execute(
                        delete(Test).filter(
                            Test.id.in_(bad_test_ids)
                        )
                    )
                    deleted_count = result.rowcount

            await self.db.commit()
            
            logger.info(
                f"Rebuild tests completed. Updated: {len(updated_test_ids)}, "
                f"Created: {new_tests_created}, Deleted: {deleted_count}"
            )
            
            return RebuildTestsResponse(
                status="success",
                message=(
                    f"Успешно синхронизировано {len(updated_test_ids)} тестов. "
                    f"Создано новых: {new_tests_created}. "
                    f"Удалено устаревших автотестов: {deleted_count}."
                ),
                updated_test_ids=updated_test_ids,
                deleted_count=deleted_count,
            )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error rebuilding tests: {str(e)}", exc_info=True)
            raise Exception(f"Database Error: {str(e)}")

    async def _recompute_answers_for_task(self, task: Task):
        """
        Пересчитывает правильность и баллы для всех UserAnswer, привязанных к task,
        и обновляет total_points в соответствующих TestResult.
        Возвращает статистику: сколько обновлено ответов и результатов.
        
        Исправленная версия с явной загрузкой связей.
        """
        if not task:
            return RecomputeAnswersResponse(answers_updated=0, results_updated=0)

        # ========== 1. Получаем все ответы на это задание ==========
        result = await self.db.execute(
            select(UserAnswer).filter(UserAnswer.task_id == task.id)
        )
        user_answers = result.scalars().all()

        if not user_answers:
            return RecomputeAnswersResponse(answers_updated=0, results_updated=0)

        result_ids = set()
        answers_updated = 0

        # ========== 2. Пересчитываем каждый ответ ==========
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

            # Обновляем только если изменилось
            if ua.is_correct != is_correct_now or ua.points_earned != new_points:
                ua.is_correct = is_correct_now
                ua.points_earned = new_points
                answers_updated += 1
                if ua.result_id:
                    result_ids.add(ua.result_id)

        # ========== 3. Обновляем total_points для всех затронутых результатов ==========
        results_updated = 0
        if result_ids:
            # Явно загружаем ответы для каждого результата через selectinload
            result = await self.db.execute(
                select(TestResult)
                .options(
                    selectinload(TestResult.answers)  # ← Явная загрузка всех ответов
                )
                .filter(TestResult.id.in_(list(result_ids)))
            )
            # Используем unique() для избежания дубликатов при joined-загрузке
            results_list = result.scalars().unique().all()

            for r in results_list:
                # Пересчитываем сумму баллов
                new_total = sum(ans.points_earned for ans in r.answers)
                if r.total_points != new_total:
                    r.total_points = new_total
                    results_updated += 1

        # Если были изменения, коммитим их
        if answers_updated > 0 or results_updated > 0:
            await self.db.flush()
            logger.info(
                f"Recomputed answers for task {task.id}: "
                f"answers_updated={answers_updated}, results_updated={results_updated}"
            )

        return RecomputeAnswersResponse(
            answers_updated=answers_updated,
            results_updated=results_updated
        )

    # ==================== ЛЕНИВАЯ ЗАГРУЗКА (МЕТА-ИНФОРМАЦИЯ) ====================

    async def get_tasks_by_class_and_topic(self, task_class: str, topic_number: str):
        """Ленивая загрузка заданий по классу и номеру темы"""
        return await self.task_repo.get_tasks_by_class_and_topic(task_class, topic_number)

    async def get_tasks_by_topic_section(self, topic: str, section: str):
        """Ленивая загрузка заданий по теме и разделу"""
        return await self.task_repo.get_tasks_by_topic_and_section(topic, section)

    async def get_tasks_meta(self):
        """Получить метаинформацию: { task_class: { topic_number: count } }"""
        tasks = await self.task_repo.get_all_tasks()
        result = {}
        for task in tasks:
            cls = str(task.task_class)
            topic_num = str(task.topic_number)

            if cls not in result:
                result[cls] = {}
            if topic_num not in result[cls]:
                result[cls][topic_num] = 0

            result[cls][topic_num] += 1

        return TeacherTaskMetaResponse(result)

    async def get_tasks_meta_by_topic_section(self):
        """Получить метаинформацию по topic и section: { topic: { section: count } }"""
        tasks = await self.task_repo.get_all_tasks()
        result = {}

        for task in tasks:
            topic = task.topic or "Без темы"
            section = task.section or "Без раздела"

            if topic not in result:
                result[topic] = {}
            if section not in result[topic]:
                result[topic][section] = 0

            result[topic][section] += 1

        return TeacherTaskMetaByTopicSectionResponse(result)

    # ==================== РАБОТА С ТЕСТАМИ ====================

    async def get_tests(self, admin_id: int):
        """Получить все тесты (админ видит все)"""
        return await self.test_repo.get_teacher_tests(admin_id, "admin")

    async def get_test_detail(self, test_id: int, admin_id: int):
        """Получить детальную информацию о тесте"""
        test = await self.test_repo.get_test_with_tasks(test_id)

        if not test:
            raise ValueError("Тест не найден")

        return test

    async def get_test_tasks(self, test_id: int, admin_id: int):
        """Получить задания теста (для ленивой загрузки)"""
        test = await self.test_repo.get_test_with_tasks(test_id)
        if not test:
            raise ValueError("Тест не найден")

        tasks = []
        for task in test.tasks:
            tasks.append(TeacherTaskDetailResponse(
                id=task.id,
                content=task.content,
                options=task.options,
                answer=task.answer,
                hint=task.hint,
                solution=task.solution,
                is_open_answer=task.is_open_answer,
                difficulty=task.difficulty,
                topic=task.topic,
                section=task.section,
                topic_number=task.topic_number,
                task_class=task.task_class,
            ))
        return tasks

    # ==================== AI-КЛАССИФИКАЦИЯ ЗАДАНИЙ ====================

    # ── Конфигурация классификации ──
    CLASSIFY_TOKENS_PER_TASK: int = 1024
    CLASSIFY_MIN_TOKENS: int = 1024
    CLASSIFY_MAX_CONCURRENT = 10  # Семафор для классификации

    async def classify_tasks(self, task_ids: list[int] | None = None, include_classified: bool = False, reestimate_difficulty: bool = False, skip_classification: bool = False) -> ClassifyTasksResponse:
        """AI-классификация заданий: topic/section/difficulty.

        task_ids пуст = все задания.
        include_classified=True — включая уже размеченные.
        reestimate_difficulty=True — только задания с difficulty=1/NULL.
        skip_classification=True — не менять topic/section, только difficulty.
        """
        from services.ai_service import AIService

        ai = AIService(provider="deepseek")
        log: list[str] = []
        stats = {"classified": 0, "failed": 0}

        # 1. Получаем задания
        stmt = select(Task)
        if task_ids:
            stmt = stmt.where(Task.id.in_(task_ids))
            log.append(f"🔍 Обработка по ID: {len(task_ids)} шт.")
        else:
            log.append("🔍 Обработка всех заданий")
        # Filters:
        if reestimate_difficulty:
            stmt = stmt.where(
                (Task.difficulty.is_(None)) | (Task.difficulty == 1)
            )
            log.append("   (только с difficulty=1 или без сложности)")
        elif not include_classified:
            stmt = stmt.where(
                (Task.section.is_(None)) | (Task.section == "") |
                (Task.topic.is_(None)) | (Task.topic == "")
            )
            log.append("   (только неклассифицированные)")
        if skip_classification:
            log.append("   (только difficulty, topic/section не трогаем)")
        stmt = stmt.order_by(Task.task_class, Task.topic_number)
        result = await self.db.execute(stmt)

        tasks = list(result.scalars().all())

        if not tasks:
            log.append("✅ Все задания уже классифицированы")
            return ClassifyTasksResponse(
                total_processed=0, classified=0, failed=0, log=log
            )

        log.append(f"🔍 Найдено неклассифицированных: {len(tasks)}")

        # 2. Получаем структуру тем (для классификации)
        struct_res = await self.db.execute(
            select(Task.topic, Task.section)
            .where(Task.topic.isnot(None), Task.topic != "")
            .distinct()
        )
        topics_structure: dict[str, set] = {}
        for topic, section in struct_res:
            if topic not in topics_structure:
                topics_structure[topic] = set()
            if section:
                topics_structure[topic].add(section)

        log.append(f"📚 Тем в базе: {len(topics_structure) if topics_structure else 0}")

        # 3. Классификация topic/section (параллельно)
        classify_semaphore = asyncio.Semaphore(self.CLASSIFY_MAX_CONCURRENT)

        async def _classify_one(task: Task, idx: int) -> str:
            prefix = f"[{idx}/{len(tasks)}] #{task.id}"
            async with classify_semaphore:
                try:
                    classification = await self._ai_classify_task(ai, task, topics_structure)
                    if classification and (classification.get("topic") or classification.get("difficulty") is not None):
                        # Save logic:
                        changed = []
                        # topic/section
                        if not skip_classification and classification.get("topic"):
                            task.topic = classification["topic"]
                            task.section = classification.get("section", "")
                            changed.append(f"topic={task.topic}")
                        # difficulty
                        diff = classification.get("difficulty")
                        if diff is not None and isinstance(diff, int) and 1 <= diff <= 5:
                            task.difficulty = diff
                            changed.append(f"diff={task.difficulty}")
                        if changed:
                            stats["classified"] += 1
                            return f"{prefix} ✅ {', '.join(changed)}"
                        else:
                            stats["failed"] += 1
                            return f"{prefix} ⚠️ нечего сохранять"
                    else:
                        stats["failed"] += 1
                        return f"{prefix} ⚠️ AI не вернул topic/section"
                except Exception as e:
                    stats["failed"] += 1
                    logger.error(f"Classify failed for task {task.id}: {e}")
                    return f"{prefix} 💥 ошибка: {e}"

        chunk_results = await asyncio.gather(*(
            _classify_one(task, idx)
            for idx, task in enumerate(tasks, 1)
        ))
        log.extend(chunk_results)

        await self.db.commit()
        log.append(
            f"\n📊 Итого: классифицировано={stats['classified']}, ошибок={stats['failed']}"
        )

        return ClassifyTasksResponse(
            total_processed=len(tasks),
            classified=stats["classified"],
            failed=stats["failed"],
            log=log,
        )

    async def _ai_classify_task(self, ai, task: Task, topics_structure: dict) -> dict | None:
        """AI классифицирует задание → {topic, section}, выбирая только из существующих в БД тем.
        
        Если БД пустая (бутстрап) — AI классифицирует свободно, без ограничений.
        """
        task_type = "open answer" if task.is_open_answer else "multiple choice"

        # Бутстрап: если в БД ещё нет тем — AI классифицирует свободно
        if not topics_structure:
            prompt = f"""Classify this math task by topic, section, and difficulty.
Output ONLY a JSON object: {{"topic": "...", "section": "...", "difficulty": N}}

=== TASK INFO ===
Type: {task_type}
Current difficulty: {task.difficulty or 'not set'}/5
Problem:
{task.content[:600]}

=== CLASSIFICATION GUIDELINES ===
- topic - broad category (e.g., "Алгебра", "Геометрия", "Тригонометрия", "Логарифмы", "Прогрессии", "Функции", "Неравенства")
- section - specific subtopic (e.g., "Квадратные уравнения", "Площади фигур", "Тригонометрические уравнения", "Стереометрия")
- difficulty - integer from 1 (easiest) to 5 (hardest), based on number of solution steps and math level required
- Choose the most specific topic and section that matches this problem."""
        else:
            # Нормальный режим: список тем из БД
            available_lines = []
            for topic in sorted(topics_structure.keys()):
                sections = topics_structure[topic]
                if sections:
                    available_lines.append(f'  - "{topic}": разделы: {", ".join(f"\"{s}\"" for s in sorted(sections))}')
                else:
                    available_lines.append(f'  - "{topic}" (без разделов)')
            available_str = "\n".join(available_lines)

            prompt = f"""Classify this math task by topic, section, and difficulty.
Output ONLY a JSON object: {{"topic": "...", "section": "...", "difficulty": N}}

=== TASK INFO ===
Type: {task_type}
Current difficulty: {task.difficulty or 'not set'}/5
Problem:
{task.content[:600]}

=== AVAILABLE TOPICS & SECTIONS (choose ONLY from these) ===
{available_str}

=== CLASSIFICATION GUIDELINES ===
- topic MUST be one of the listed topics above.
- section MUST be one of the listed sections under that topic (or "" if none listed or none applies).
- difficulty - integer from 1 (easiest) to 5 (hardest), based on number of solution steps and math level required
- Choose the most specific match. If nothing fits, pick the closest topic from the list.
- Do NOT invent topics or sections that are not in the list above."""
        try:
            response = await ai._chat_completion(
                system_prompt="You are a strict classifier of math problems. Output valid JSON only, no markdown.",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=self.CLASSIFY_TOKENS_PER_TASK,
                json_mode=True,
            )

            if not response:
                logger.warning(f"Classify task #{task.id}: empty response from AI")
                return None

            logger.debug(f"Classify task #{task.id}: raw ({len(response)} chars): {response[:200]}")

            m = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if m:
                data = json.loads(m.group())
                topic = data.get("topic")
                section = data.get("section", "")
                difficulty = data.get("difficulty")
                if topic:
                    # Валидация: тема должна быть среди существующих в БД
                    # Но если БД пустая — доверяем AI (бутстрап)
                    if topics_structure and topic not in topics_structure:
                        logger.warning(f"Classify task #{task.id}: AI вернул тему '{topic}', которой нет в БД (доступны: {list(topics_structure.keys())})")
                        return None
                    # Валидация: раздел (если указан) должен быть среди разделов этой темы
                    if topics_structure and section and section not in topics_structure.get(topic, set()):
                        logger.warning(f"Classify task #{task.id}: AI вернул раздел '{section}' для темы '{topic}', но такого раздела нет в БД (доступны: {topics_structure.get(topic, set())})")
                        return None
                    # Валидация difficulty
                    if difficulty is not None:
                        try:
                            diff = int(difficulty)
                            if 1 <= diff <= 5:
                                data["difficulty"] = diff
                        except (ValueError, TypeError):
                            pass
                    return data
                else:
                    logger.warning(f"Classify task #{task.id}: JSON parsed but no 'topic' field: {data}")
            else:
                logger.warning(f"Classify task #{task.id}: no JSON object found in response: {response[:300]}")
        except json.JSONDecodeError as e:
            logger.warning(f"Classify task #{task.id}: JSON parse error: {e}")
        except Exception as e:
            logger.warning(f"AI classify failed for task {task.id}: {type(e).__name__}: {e}")
        return None
