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
)

logger = logging.getLogger(__name__)


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

    # ==================== AI-КЛАССИФИКАЦИЯ ЗАДАНИЙ ====================

    # Размеры батчей для этапа решения по уровням сложности
    SOLVE_BATCH_SIZES: dict[int, int] = {1: 20, 2: 10, 3: 7, 4: 3, 5: 1}

    # ── Токен-бюджеты (расценки) ──
    # Фаза 1: оценка сложности. json_mode (без thinking) — дёшево, flat.
    #   finish_reason=length при заниженном бюджете → JSON обрезается → пустой ответ.
    #   300 токенов/задачу даёт запас на verbose формулировки AI.
    ESTIMATE_TOKENS_PER_TASK: int = 300
    ESTIMATE_MIN_TOKENS: int = 4096

    # Фаза 2: решение. json_mode (без thinking) — модель всё равно считает внутри.
    #   thinking отключён, потому что он съедает бюджет на рассуждения,
    #   и JSON обрезается (finish_reason=length).
    #   Бюджет на задачу выше, т.к. модель пишет решение текстом перед JSON.
    SOLVE_TOKENS_PER_TASK: dict[int, int] = {
        1: 300,
        2: 600,
        3: 1000,
        4: 1500,
        5: 2500,
    }
    SOLVE_MIN_TOKENS: int = 4096
    SOLVE_MAX_TOKENS: int = 32000

    # Фаза 3: классификация topic/section. json_mode — один JSON-объект.
    #   200 токенов было мало даже на {"topic":"...","section":"..."} — finish_reason=length.
    CLASSIFY_TOKENS_PER_TASK: int = 1024
    CLASSIFY_MIN_TOKENS: int = 1024

    @staticmethod
    def _solve_tokens_for(tasks: list[Task]) -> int:
        """Вычислить max_tokens для пакета задач с учётом их сложностей."""
        total = 0
        for t in tasks:
            d = t.difficulty if t.difficulty in AdminService.SOLVE_TOKENS_PER_TASK else 1
            total += AdminService.SOLVE_TOKENS_PER_TASK[d]
        return max(AdminService.SOLVE_MIN_TOKENS, min(total, AdminService.SOLVE_MAX_TOKENS))

    async def classify_tasks(self, task_ids: list[int] | None = None) -> ClassifyTasksResponse:
        """AI-классификация заданий: сложность → решение → topic/section.

        Три фазы, каждая через отдельный AI-вызов:
        1. AI оценивает сложность (1-5) для каждого задания.
           Если AI не смог оценить → задание пропускается (не идёт на следующие этапы).
        2. Задания группируются по сложности и решаются пакетно
           (20/10/7/3/1 шт. для сложности 1/2/3/4/5).
           И закрытые, и открытые задания решаются в одном батче.
           Ответы сравниваются с эталоном.
        3. Для заданий с верным ответом AI классифицирует topic/section.

        Если передан task_ids — обрабатываются только указанные задания (без ограничений).
        Если task_ids пуст/None — обрабатываются все задания без section/topic.
        """
        from services.ai_service import AIService

        ai = AIService(provider="deepseek")
        log: list[str] = []
        stats = {"difficulty": 0, "solved": 0, "classified": 0, "failed": 0}

        # 1. Получаем задания
        if task_ids:
            result = await self.db.execute(
                select(Task).where(Task.id.in_(task_ids))
            )
            log.append(f"🔍 Обработка по ID: {len(task_ids)} шт.")
        else:
            result = await self.db.execute(
                select(Task)
                .where(
                    (Task.section.is_(None)) | (Task.section == "") |
                    (Task.topic.is_(None)) | (Task.topic == "")
                )
                .order_by(Task.task_class, Task.topic_number)
            )
            log.append("🔍 Обработка всех неклассифицированных заданий")

        tasks = list(result.scalars().all())

        if not tasks:
            log.append("✅ Все задания уже классифицированы")
            return ClassifyTasksResponse(
                total_processed=0, difficulty_assigned=0,
                solved_correctly=0, classified=0, failed=0, log=log
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

        log.append(f"📚 Тем в базе: {len(topics_structure)}")

        # ═══════════════════════════════════════════
        # ФАЗА 1: AI-оценка сложности (батчевая)
        # ═══════════════════════════════════════════
        log.append("\n── ФАЗА 1: оценка сложности ──")
        estimated_tasks: list[Task] = []

        # Батчами по 15 заданий — json_mode, без thinking, не перегружаем модель
        DIFF_BATCH = 15
        total_batches = (len(tasks) + DIFF_BATCH - 1) // DIFF_BATCH
        for batch_num in range(total_batches):
            batch = tasks[batch_num * DIFF_BATCH : (batch_num + 1) * DIFF_BATCH]
            prefix = f"[Phase1 batch {batch_num + 1}/{total_batches}]"
            ids_str = ", ".join(str(t.id) for t in batch)
            log.append(f"{prefix} #{ids_str} ({len(batch)} шт.)")

            try:
                diff_map = await self._ai_estimate_difficulty_batch(ai, batch)
            except Exception as e:
                diff_map = {}
                logger.error(f"Difficulty batch {batch_num + 1} failed: {e}")
                log.append(f"{prefix} 💥 ошибка: {e}")

            for task in batch:
                est_diff = diff_map.get(task.id)
                if est_diff is None:
                    stats["failed"] += 1
                    log.append(f"  ❌ #{task.id} AI не смог оценить сложность — пропущено")
                    continue

                if est_diff != task.difficulty:
                    task.difficulty = est_diff
                    stats["difficulty"] += 1
                    log.append(f"  🎯 #{task.id} сложность={est_diff}")
                else:
                    log.append(f"  🎯 #{task.id} сложность={task.difficulty} (не изменилась)")

                estimated_tasks.append(task)

        if estimated_tasks:
            await self.db.flush()

        log.append(f"📊 Фаза 1: оценено={len(estimated_tasks)}, пропущено={len(tasks) - len(estimated_tasks)}")

        if not estimated_tasks:
            log.append("❌ Ни одно задание не прошло оценку сложности")
            return ClassifyTasksResponse(
                total_processed=len(tasks),
                difficulty_assigned=stats["difficulty"],
                solved_correctly=0, classified=0,
                failed=stats["failed"], log=log,
            )

        # ═══════════════════════════════════════════
        # ФАЗА 2: Пакетное решение по уровням сложности
        # ═══════════════════════════════════════════
        log.append("\n── ФАЗА 2: пакетное решение ──")

        # Группируем задания по сложности
        by_difficulty: dict[int, list[Task]] = {d: [] for d in range(1, 6)}
        for task in estimated_tasks:
            d = task.difficulty if task.difficulty in range(1, 6) else 1
            by_difficulty[d].append(task)

        solved_tasks: list[Task] = []

        for diff_level in range(1, 6):
            batch_tasks = by_difficulty[diff_level]
            if not batch_tasks:
                continue

            batch_size = self.SOLVE_BATCH_SIZES[diff_level]
            log.append(f"  Сложность {diff_level}: {len(batch_tasks)} заданий, батч по {batch_size}")

            for batch_num, i in enumerate(range(0, len(batch_tasks), batch_size), 1):
                batch = batch_tasks[i:i + batch_size]
                closed = [t for t in batch if not t.is_open_answer]
                open_list = [t for t in batch if t.is_open_answer]

                # Решаем закрытые и открытые параллельно в одном батче
                coros = []
                if closed:
                    coros.append(("closed", self._ai_solve_batch(ai, closed)))
                if open_list:
                    coros.append(("open", self._ai_solve_open_batch(ai, open_list)))

                if coros:
                    results = await asyncio.gather(*(c[1] for c in coros), return_exceptions=True)
                    for (kind, _), answers_map in zip(coros, results):
                        if isinstance(answers_map, Exception):
                            logger.error(
                                f"Phase2 {kind} solve batch crashed for diff={diff_level}, "
                                f"batch={batch_num}: {type(answers_map).__name__}: {answers_map}"
                            )
                            log.append(f"  💥 [{kind}] batch {batch_num} (сл.{diff_level}) ошибка: {answers_map}")
                            continue
                        if not isinstance(answers_map, dict):
                            logger.warning(
                                f"Phase2 {kind} solve batch returned non-dict: {type(answers_map).__name__}"
                            )
                            continue
                        task_list = closed if kind == "closed" else open_list
                        for task in task_list:
                            ai_answer = answers_map.get(task.id, "")
                            kind_tag = "открытый" if kind == "open" else ""
                            if self._compare_answer(ai_answer, task):
                                solved_tasks.append(task)
                                stats["solved"] += 1
                                tag = f", {kind_tag}" if kind_tag else ""
                                log.append(f"  ✅ #{task.id} (сл.{diff_level}{tag}) ответ совпал: «{ai_answer}»")
                            else:
                                stats["failed"] += 1
                                tag = f", {kind_tag}" if kind_tag else ""
                                log.append(f"  ❌ #{task.id} (сл.{diff_level}{tag}) ответ не совпал: AI=«{ai_answer}», эталон=«{task.answer}»")


        log.append(f"📊 Фаза 2: решено верно={stats['solved']}, не совпало={stats['failed'] - (len(tasks) - len(estimated_tasks))}")

        # ═══════════════════════════════════════════
        # ФАЗА 3: Классификация topic/section (параллельно по 10)
        # ═══════════════════════════════════════════
        log.append("\n── ФАЗА 3: классификация topic/section ──")

        # Параллелим по 10 — DeepSeek API выдерживает такой параллелизм
        CLASSIFY_CONCURRENCY = 10

        async def _classify_one(task: Task, idx: int) -> str:
            prefix = f"[Phase3 {idx}/{len(solved_tasks)}] #{task.id} (сл.{task.difficulty})"
            try:
                classification = await self._ai_classify_task(ai, task, topics_structure)
                if classification and classification.get("topic"):
                    task.topic = classification["topic"]
                    task.section = classification.get("section", "")
                    stats["classified"] += 1
                    return f"{prefix} 🏷️  topic={task.topic}, section={task.section}"
                else:
                    stats["failed"] += 1
                    return f"{prefix} ⚠️ AI не вернул topic/section"
            except Exception as e:
                stats["failed"] += 1
                logger.error(f"Classify failed for task {task.id}: {e}")
                return f"{prefix} 💥 ошибка: {e}"

        for chunk_start in range(0, len(solved_tasks), CLASSIFY_CONCURRENCY):
            chunk = list(enumerate(solved_tasks[chunk_start : chunk_start + CLASSIFY_CONCURRENCY], chunk_start + 1))
            chunk_results = await asyncio.gather(*(_classify_one(task, idx) for idx, task in chunk))
            log.extend(chunk_results)
            if chunk_start + CLASSIFY_CONCURRENCY < len(solved_tasks):
                await asyncio.sleep(0.1)  # микро-пауза между пачками чтобы не забить API

        await self.db.commit()
        log.append(f"\n📊 Итого: сложность={stats['difficulty']}, решено={stats['solved']}, "
                   f"классифицировано={stats['classified']}, ошибок={stats['failed']}")

        return ClassifyTasksResponse(
            total_processed=len(tasks),
            difficulty_assigned=stats["difficulty"],
            solved_correctly=stats["solved"],
            classified=stats["classified"],
            failed=stats["failed"],
            log=log,
        )

    async def _ai_estimate_difficulty_batch(self, ai, tasks: list[Task]) -> dict[int, int]:
        """AI оценивает сложность пачки заданий (1-5) за один вызов.

        Использует json_mode (без thinking) — это классификация, не решение.
        Возвращает {task_id: difficulty}.
        """
        if not tasks:
            return {}

        task_blocks: list[str] = []
        for i, task in enumerate(tasks, 1):
            qtype = "открытый" if task.is_open_answer else "закрытый"
            block = (
                f"### Задание {i} (id={task.id}, класс={task.task_class}, тип={qtype})\n"
                f"{task.content[:400]}\n"
            )
            task_blocks.append(block)

        prompt = (
            "Оцени сложность КАЖДОГО задания по шкале 1-5, где:\n"
            "1 — устный счёт / очевидное, 5 — олимпиадное / требует много шагов.\n\n"
            "Верни ТОЛЬКО JSON-массив без markdown:\n"
            '[{"task_id": <id>, "difficulty": <1-5>}, ...]\n\n'
            + "\n".join(task_blocks)
        )

        try:
            response = await ai._chat_completion(
                system_prompt=(
                    "Ты оцениваешь сложность математических заданий. "
                    "Верни ТОЛЬКО валидный JSON-массив с полями task_id и difficulty (integer 1-5). "
                    "Никакого текста вне JSON."
                ),
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=max(self.ESTIMATE_MIN_TOKENS, len(tasks) * self.ESTIMATE_TOKENS_PER_TASK),
                json_mode=True,
            )

            if not response:
                logger.warning(f"Difficulty batch: empty response from AI for {len(tasks)} tasks")
                return {}

            logger.debug(f"Difficulty batch: raw response ({len(response)} chars): {response[:300]}...")

            # json_mode даёт чистый JSON, пробуем весь ответ как массив
            result: dict[int, int] = {}
            m = re.search(r'\[.*\]', response, re.DOTALL)
            if m:
                try:
                    items = json.loads(m.group())
                    if isinstance(items, list):
                        for item in items:
                            tid = item.get("task_id")
                            d = item.get("difficulty")
                            if tid is not None and isinstance(d, int) and 1 <= d <= 5:
                                result[int(tid)] = d
                    logger.debug(f"Difficulty batch: parsed {len(result)}/{len(tasks)} tasks")
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logger.warning(f"Difficulty batch JSON parse error: {e}")
                    logger.warning(f"  Failed JSON snippet: {m.group()[:200]}")
            else:
                logger.warning(f"Difficulty batch: no JSON array found in response")
                logger.warning(f"  Response preview: {response[:500]}")

            missing = [t.id for t in tasks if t.id not in result]
            if missing:
                logger.warning(f"Difficulty batch: {len(missing)} tasks missing in AI response: {missing}")

            return result

        except Exception as e:
            logger.warning(f"Difficulty batch estimation failed: {type(e).__name__}: {e}")

        return {}

    async def _ai_solve_open_batch(self, ai, tasks: list[Task]) -> dict[int, str]:
        """Пакетное решение открытых заданий — json_mode, без thinking.

        thinking отключён, потому что он съедает бюджет токенов на рассуждения,
        и JSON-массив обрезается (finish_reason=length).
        json_mode гарантирует валидный JSON на выходе.
        """
        if not tasks:
            return {}

        task_blocks: list[str] = []
        for i, task in enumerate(tasks, 1):
            block = (
                f"### Задание {i} (id={task.id}, класс={task.task_class}, сложность={task.difficulty})\n"
                f"Условие:\n{task.content[:800]}\n"
            )
            task_blocks.append(block)

        prompt = (
            "Реши КАЖДОЕ задание и выведи ответы в JSON-массиве. "
            "answer — ТОЛЬКО число или математическое выражение без префиксов (без «x=», «ответ:», и т.п.).\n"
            "Формат ответа строго:\n"
            '[{"task_id": <id>, "answer": "<число или выражение>"}, ...]\n\n'
            + "\n".join(task_blocks)
        )

        max_tokens = self._solve_tokens_for(tasks)

        try:
            response = await ai._chat_completion(
                system_prompt=(
                    "Ты — математик. Реши каждое задание и верни ответ СТРОГО в JSON-массиве "
                    '[{"task_id": <id>, "answer": "<ответ>"}, ...]. Никакого текста вне JSON.'
                ),
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=max_tokens,
                json_mode=True,
            )

            if not response:
                logger.warning(f"Open solve batch: empty response from AI for {len(tasks)} tasks")
                return {}

            logger.debug(f"Open solve batch: raw response ({len(response)} chars): {response[:300]}...")

            result: dict[int, str] = self._extract_answer_json(response)
            if not result:
                logger.warning(f"Open solve batch: _extract_answer_json returned empty for {len(tasks)} tasks")
                logger.warning(f"  Response tail: {response[-500:]}")
            else:
                logger.debug(f"Open solve batch: extracted {len(result)}/{len(tasks)} answers")
            return result

        except Exception as e:
            logger.warning(f"Open batch solve failed for {len(tasks)} tasks: {type(e).__name__}: {e}")

        return {}

    async def _ai_solve_batch(self, ai, tasks: list[Task]) -> dict[int, str]:
        """Пакетное решение закрытых заданий (выбор варианта) — json_mode, без thinking.

        AI решает ЗНАЧЕНИЕ правильного ответа (текст варианта), а не его номер.
        thinking отключён — json_mode даёт валидный JSON без обрезки.
        """
        if not tasks:
            return {}

        task_blocks: list[str] = []
        for i, task in enumerate(tasks, 1):
            opts = ""
            if task.options:
                for j, opt in enumerate(task.options, 1):
                    opts += f"{j}) {opt}\n"

            block = (
                f"### Задание {i} (id={task.id}, класс={task.task_class}, сложность={task.difficulty})\n"
                f"Условие:\n{task.content[:800]}\n"
                f"Варианты:\n{opts}"
            )
            task_blocks.append(block)

        prompt = (
            "Реши КАЖДОЕ задание и выбери правильный вариант. "
            "В поле answer запиши ТОЧНЫЙ ТЕКСТ правильного варианта (не номер, а само значение).\n"
            "Формат ответа строго:\n"
            '[{"task_id": <id>, "answer": "<текст правильного варианта>"}, ...]\n\n'
            + "\n".join(task_blocks)
        )

        max_tokens = self._solve_tokens_for(tasks)

        try:
            response = await ai._chat_completion(
                system_prompt=(
                    "Ты — математик. Реши каждое задание и верни ответ СТРОГО в JSON-массиве "
                    '[{"task_id": <id>, "answer": "<текст варианта>"}, ...]. '
                    "answer — ТОЧНЫЙ ТЕКСТ правильного варианта (не номер, а само значение). "
                    "Никакого текста вне JSON."
                ),
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=max_tokens,
                json_mode=True,
            )

            if not response:
                logger.warning(f"Closed solve batch: empty response from AI for {len(tasks)} tasks")
                return {}

            logger.debug(f"Closed solve batch: raw response ({len(response)} chars): {response[:300]}...")

            result: dict[int, str] = self._extract_answer_json(response)
            if not result:
                logger.warning(f"Closed solve batch: _extract_answer_json returned empty for {len(tasks)} tasks")
                logger.warning(f"  Response tail: {response[-500:]}")
            else:
                logger.debug(f"Closed solve batch: extracted {len(result)}/{len(tasks)} answers")
            return result

        except Exception as e:
            logger.warning(f"Batch solve failed for {len(tasks)} tasks: {type(e).__name__}: {e}")

        return {}

    @staticmethod
    def _extract_answer_json(response: str) -> dict[int, str]:
        """Извлекает {task_id: answer} из JSON-массива в ответе AI.

        Ищет JSON-массив в последней трети ответа (после рассуждений),
        а не в начале, где может быть шаблон из промпта.
        """
        # Ищем ВСЕ JSON-массивы, берём последний (он после рассуждений)
        matches = list(re.finditer(r'\[.*?\]', response, re.DOTALL))
        result: dict[int, str] = {}

        logger.debug(f"_extract_answer_json: response={len(response)} chars, found {len(matches)} array candidates")

        # Пробуем от последнего к первому — самый надёжный
        for idx, m in enumerate(reversed(matches)):
            try:
                items = json.loads(m.group())
                if isinstance(items, list) and items:
                    for item in items:
                        tid = item.get("task_id")
                        ans = item.get("answer")
                        if tid is not None and ans is not None:
                            result[int(tid)] = str(ans).strip()
                    if result:
                        logger.debug(f"_extract_answer_json: success at candidate #{idx} — {len(result)} entries")
                        return result
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"_extract_answer_json: candidate #{idx} parse error: {type(e).__name__}: {e}")
                continue

        # Fallback: ищем JSON в хвосте ответа (последние 2000 символов)
        tail = response[-2000:] if len(response) > 2000 else response
        m = re.search(r'\[.*\]', tail, re.DOTALL)
        if m:
            try:
                items = json.loads(m.group())
                for item in items:
                    tid = item.get("task_id")
                    ans = item.get("answer")
                    if tid is not None and ans is not None:
                        result[int(tid)] = str(ans).strip()
                if result:
                    logger.debug(f"_extract_answer_json: fallback success — {len(result)} entries")
                else:
                    logger.warning(f"_extract_answer_json: fallback parsed array but no valid entries: {m.group()[:300]}")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"_extract_answer_json: fallback parse error: {type(e).__name__}: {e}")
                logger.warning(f"  Fallback snippet: {m.group()[:300]}")
        else:
            logger.warning(f"_extract_answer_json: no JSON array found in response tail. Tail preview:")
            logger.warning(f"  {tail[:500]}")

        return result

    @staticmethod
    def _compare_answer(ai_answer: str, task: Task) -> bool:
        """Сравнить ответ AI с эталоном.

        Нормализует оба ответа и сравнивает:
        - Убирает пробелы, префиксы (x=, ответ:)
        - Нормализует десятичные разделители
        - Пробует числовое сравнение (float)
        """
        def _norm(s: str) -> str:
            s = s.strip().lower()
            s = s.replace(",", ".").replace(" ", "")
            # Убираем префиксы
            s = re.sub(r'^(x=|y=|ответ:?\s*|answer:?\s*)', '', s)
            # Убираем trailing точку
            s = s.rstrip('.')
            return s

        a = _norm(ai_answer)
        b = _norm(task.answer or "")

        # Точное строковое совпадение
        if a == b:
            return True

        # Числовое сравнение
        try:
            fa = float(a)
            fb = float(b)
            return abs(fa - fb) < 1e-9
        except (ValueError, TypeError):
            pass

        # Сравнение без скобок (скобки могут быть эквивалентны)
        a_nobraces = a.replace("(", "").replace(")", "")
        b_nobraces = b.replace("(", "").replace(")", "")
        if a_nobraces == b_nobraces:
            return True

        return False

    async def _ai_classify_task(self, ai, task: Task, topics_structure: dict) -> dict | None:
        """AI классифицирует задание → {topic, section}."""
        hierarchy = []
        for topic_name, sections in topics_structure.items():
            hierarchy.append(f"- {topic_name}")
            if sections:
                for s in sorted(sections):
                    hierarchy.append(f"    - {s}")

        prompt = f"""Classify this math task by topic and section from the list below.
Output ONLY a JSON object: {{"topic": "...", "section": "..."}}

=== AVAILABLE TOPICS ===
{chr(10).join(hierarchy)}

=== TASK ===
Class: {task.task_class}
Topic number: {task.topic_number}
Type: {'open answer' if task.is_open_answer else 'multiple choice'}
Problem:
{task.content[:600]}

Pick topic and section ONLY from the list above. If no exact match, choose the closest.
"""
        try:
            response = await ai._chat_completion(
                system_prompt="You are a strict classifier. Output valid JSON only, no markdown.",
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
                if data.get("topic"):
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
