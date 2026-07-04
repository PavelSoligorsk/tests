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
import models


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
    
    def change_user_role(self, user_id: int, new_role: str, admin_id: int):
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        if user.id == admin_id and new_role != "admin":
            raise ValueError("Вы не можете снять роль админа с самого себя")
        
        self.user_repo.update_user_role(user, new_role)
        return {"message": f"Роль пользователя {user.username} изменена на {new_role}"}
    
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
        return {"message": "Пользователь и все связанные данные удалены"}
    
    def get_user_profile(self, user_id: int):
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        stats = self.user_repo.get_user_stats(user_id)
        
        return {
            "user": user,
            "stats": stats
        }
    
    def get_user_history(self, user_id: int):
        results = self.result_repo.get_user_history(user_id)
        return [
            {
                "test_title": r.test.title if r.test else "Тест удален",
                "result": {
                    "id": r.id,
                    "total_points": r.total_points,
                    "completed_at": r.completed_at
                }
            } for r in results
        ]
    
    # ==================== ЗАДАНИЯ ====================
    
    def create_task(self, task_data: dict):
        return self.task_repo.create_task(task_data)
    
    def update_task(self, task_id: int, update_data: dict):
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Задание не найдено")
        return self.task_repo.update_task(task, update_data)
    
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
        return {"message": f"Задание с ID {task_id} и связанные данные успешно удалены"}
    
    def get_detailed_result(self, result_id: int):
        result = self.result_repo.get_result_by_id(result_id)
        if not result:
            raise ValueError("Результат не найден")
        
        all_tasks = self.task_repo.get_tasks_by_test_id(result.test_id)
        user_answers = self.result_repo.get_user_answers_for_result(result_id)
        answers_map = {ua.task_id: ua for ua in user_answers}
        
        details = []
        total_max_points = 0
        difficulty_stats = {}
        
        for task in all_tasks:
            ua = answers_map.get(task.id)
            is_correct = ua.is_correct if ua else False
            
            diff_level = str(task.difficulty) if task.difficulty else "1"
            
            if diff_level not in difficulty_stats:
                difficulty_stats[diff_level] = {"correct": 0, "total": 0}
            
            difficulty_stats[diff_level]["total"] += 1
            if is_correct:
                difficulty_stats[diff_level]["correct"] += 1
            
            max_task_points = 2 if task.is_open_answer else 1
            total_max_points += max_task_points
            
            details.append({
                "task_id": task.id,
                "content": task.content,
                "options": task.options,
                "difficulty": diff_level,
                "correct_answer": task.answer,
                "user_answer": ua.user_text_answer if ua else "Нет ответа",
                "is_correct": is_correct,
                "points_earned": ua.points_earned if ua else 0,
                "max_task_points": max_task_points,
                "solution": task.solution,
                "hint": task.hint
            })
        
        return {
            "test_title": result.test.title,
            "total_points": result.total_points,
            "max_points": total_max_points,
            "completed_at": result.completed_at,
            "difficulty_stats": difficulty_stats,
            "user": {
                "first_name": result.user.first_name,
                "last_name": result.user.last_name,
            },
            "details": details
        }
    
    # ==================== РАЗРЕШЁННЫЕ EMAIL ====================
    
    def get_allowed_emails(self):
        allowed_emails = self.allowed_email_repo.get_all()
        
        result = []
        for ae in allowed_emails:
            user = self.user_repo.get_user_by_email(ae.email)
            
            result.append({
                "email": ae.email,
                "first_name": user.first_name if user else None,
                "last_name": user.last_name if user else None,
                "tg_username": user.tg_username if user else None,
            })
        
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
        
        return {"message": f"Ученик {student.username} назначен учителю {teacher.username}"}
    
    def remove_student_from_teacher(self, student_id: int):
        if not self.teacher_student_repo.delete_link_by_student(student_id):
            raise ValueError("Связь не найдена")
        
        self.db.commit()
        return {"message": "Связь удалена"}
    
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
        return {"message": f"Теория для темы '{theory.topic}' и раздела '{theory.section}' успешно удалена"}
    
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
        
        return {
            "url": file_url,
            "filename": filename,
            "size": len(image_bytes)
        }
    
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
                
                return {"message": "Задача успешно отправлена в Telegram"}
                
            except httpx.RequestError as e:
                raise Exception(f"Не удалось связаться с рендер-ботом: {str(e)}")
    
    def _parse_correct_option_ids(self, task_answer: str, render_options: list) -> list:
        correct_option_ids = []
        raw_answers = str(task_answer).strip()
        
        if re.match(r'^[\d\s,;]+$', raw_answers):
            digit_answers = re.findall(r'\d+', raw_answers)
            for num_str in digit_answers:
                idx = int(num_str) - 1
                if 0 <= idx < len(render_options):
                    if idx not in correct_option_ids:
                        correct_option_ids.append(idx)
            
            if correct_option_ids:
                return sorted(correct_option_ids)
        
        clean_answers_list = [a.strip().strip('"').strip("'") 
                             for a in re.split(r'[,;|\n]', raw_answers) if a.strip()]
        
        for idx, opt in enumerate(render_options):
            clean_opt = opt.strip().strip('"').strip("'")
            if any(ans == clean_opt for ans in clean_answers_list):
                correct_option_ids.append(idx)
        
        if not correct_option_ids:
            correct_option_ids.append(0)
        
        return sorted(correct_option_ids)