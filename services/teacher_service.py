import datetime
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.user_repository import UserRepository
from repositories.test_repository import TestRepository
from repositories.task_repository import TaskRepository
from repositories.result_repository import ResultRepository
from repositories.assignment_repository import AssignmentRepository
from repositories.group_repository import GroupRepository
from repositories.teacher_student_repository import TeacherStudentRepository

from dto_schemas.user import MessageResponse, UserResponse
from dto_schemas.task import TaskResponse
from dto_schemas.stats import UserStats
from dto_schemas.cached import (
    TaskGroupedResponse,
    TeacherStudentProfileResponse,
    TeacherHistoryItemResponse,
    TeacherHistoryResultResponse,
    DetailedResultResponse,
    DetailedResultDetailResponse,
    DifficultyStatResponse,
    ResultUserResponse,
    TeacherGroupResponse,
    TeacherGroupStudentResponse,
    TeacherAssignmentItemResponse,
    TeacherTaskDetailResponse,
    TeacherTaskMetaResponse,
    TeacherTaskMetaByTopicSectionResponse,
    GroupAssignResponse,
    AddStudentsToGroupResponse,
)


class TeacherService:
    def __init__(self, db: AsyncSession):
        self.user_repo = UserRepository(db)
        self.test_repo = TestRepository(db)
        self.task_repo = TaskRepository(db)
        self.result_repo = ResultRepository(db)
        self.assignment_repo = AssignmentRepository(db)
        self.group_repo = GroupRepository(db)
        self.teacher_student_repo = TeacherStudentRepository(db)
        self.db = db
    
    # ==================== БАНК ЗАДАНИЙ ====================
    
    async def get_tasks(self, task_class=None, topic=None, topic_number=None, section=None):
        """Получить задания с фильтрацией"""
        return await self.task_repo.get_filtered_tasks(task_class, topic, topic_number, section)
    
    async def get_tasks_grouped(self):
        """Получить задания сгруппированные по классам и темам"""
        tasks = await self.task_repo.get_all_tasks_ordered()
        
        grouped = {}
        for task in tasks:
            cls = str(task.task_class)
            topic_num = str(task.topic_number)
            
            if cls not in grouped:
                grouped[cls] = {}
            if topic_num not in grouped[cls]:
                grouped[cls][topic_num] = []
            
            grouped[cls][topic_num].append(TaskResponse(
                id=task.id,
                task_class=task.task_class,
                topic_number=task.topic_number,
                topic=task.topic,
                section=task.section,
                content=task.content,
                answer=task.answer,
                hint=task.hint,
                solution=task.solution,
                is_open_answer=task.is_open_answer,
                options=task.options,
                difficulty=task.difficulty,
            ))
        
        def sort_key(cls):
            if cls.isdigit():
                return (0, int(cls))
            else:
                return (1, cls)
        
        return {
            "grouped": grouped,
            "total_tasks": len(tasks),
            "available_classes": sorted(grouped.keys(), key=sort_key)
        }
    
    async def get_task_by_id(self, task_id: int):
        """Получить задание по ID"""
        task = await self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError("Задание не найдено")
        return task
    
    # ==================== КОНСТРУКТОР ТЕСТОВ ====================
    
    async def get_tests(self, teacher_id: int, role: str):
        """Получить тесты учителя (или все для админа)"""
        return await self.test_repo.get_teacher_tests(teacher_id, role)
    
    async def create_test(self, title: str, creator_id: int, target_class=None,
                    target_topic=None, is_autocompile: bool = False,
                    task_ids=None):
        """Создать новый тест"""
        test_data = {
            "title": title,
            "target_class": str(target_class) if target_class else None,
            "target_topic": str(target_topic) if target_topic else None,
            "is_autocompile": is_autocompile,
            "creator_id": creator_id,
            "is_active": True
        }
        
        tasks = None
        if task_ids:
            tasks = await self.task_repo.get_tasks_by_ids(task_ids)
        
        return await self.test_repo.create_test(test_data, tasks)
    
    async def update_test(self, test_id: int, teacher_id: int, title: str,
                    target_class=None, target_topic=None,
                    is_autocompile: bool = False, task_ids=None):
        """Обновить тест"""
        test = await self.test_repo.check_test_owner(test_id, teacher_id)
        if not test:
            if not await self.test_repo.get_test_by_id(test_id):
                raise ValueError("Тест не найден")
            raise PermissionError("У вас нет доступа к этому тесту")
        
        update_data = {
            "title": title,
            "target_class": str(target_class) if target_class else test.target_class,
            "target_topic": str(target_topic) if target_topic else test.target_topic,
            "is_autocompile": is_autocompile
        }
        
        tasks = None
        if task_ids is not None:
            tasks = await self.task_repo.get_tasks_by_ids(task_ids)
        
        return await self.test_repo.update_test(test, update_data, tasks)
    
    async def delete_test(self, test_id: int, teacher_id: int, role: str):
        """Удалить тест со всеми связанными данными"""
        if role == "teacher":
            test = await self.test_repo.check_test_owner(test_id, teacher_id)
            if not test:
                if not await self.test_repo.get_test_by_id(test_id):
                    raise ValueError("Тест не найден")
                raise PermissionError("Вы не можете удалить этот тест")
        
        try:
            await self.test_repo.delete_test_cascade(test_id)
            await self.db.commit()
            return MessageResponse(message=f"Тест #{test_id} и все связанные данные удалены")
        except Exception as e:
            raise Exception(f"Ошибка при удалении: {str(e)}")
    
    async def get_test_detail(self, test_id: int, teacher_id: int, role: str):
        """Получить детальную информацию о тесте"""
        test = await self.test_repo.get_test_with_tasks(test_id)
        
        if not test:
            raise ValueError("Тест не найден")
        
        if role == "teacher" and test.creator_id != teacher_id:
            raise PermissionError("У вас нет доступа к этому тесту")
        
        return test
    
    # ==================== РЕЗУЛЬТАТЫ УЧЕНИКОВ ====================
    
    async def get_my_students(self, teacher_id: int):
        """Получить список студентов учителя"""
        return await self.teacher_student_repo.get_teacher_students(teacher_id)
    
    async def get_student_profile(self, student_id: int, teacher_id: int):
        """Получить профиль студента"""
        if not await self.teacher_student_repo.check_student_belongs_to_teacher(student_id, teacher_id):
            raise PermissionError("У вас нет доступа к этому ученику")
        
        user = await self.user_repo.get_user_by_id(student_id)
        if not user or user.role != "student":
            raise ValueError("Ученик не найден")
        
        stats = await self.user_repo.get_user_stats(student_id)
        
        return TeacherStudentProfileResponse(
            user=UserResponse.model_validate(user),
            stats=UserStats(**stats),
        )
    
    async def get_student_history(self, student_id: int, teacher_id: int):
        """Получить историю тестов студента"""
        if not await self.teacher_student_repo.check_student_belongs_to_teacher(student_id, teacher_id):
            raise PermissionError("У вас нет доступа к этому ученику")
        
        user = await self.user_repo.get_user_by_id(student_id)
        if not user or user.role != "student":
            raise ValueError("Ученик не найден")
        
        results = await self.result_repo.get_user_history(student_id)
        
        return [
            TeacherHistoryItemResponse(
                test_title=r.test.title if r.test else "Тест удалён",
                result=TeacherHistoryResultResponse(
                    id=r.id,
                    total_points=r.total_points or 0,
                    completed_at=r.completed_at,
                ),
            )
            for r in results
        ]
    
    async def get_detailed_result(self, result_id: int, teacher_id: int):
        """Получить детальный результат теста (для учителя)"""
        result = await self.result_repo.get_result_by_id(result_id)
        
        if not result:
            raise ValueError("Результат не найден")
        
        if not await self.teacher_student_repo.check_student_belongs_to_teacher(result.user_id, teacher_id):
            raise PermissionError("У вас нет доступа к этому ученику")
        
        return await self._format_detailed_result(result)

    # ==================== НАЗНАЧЕНИЕ ТЕСТОВ ====================
    
    async def assign_test(self, test_id: int, teacher_id: int, user_ids: List[int],
                due_date=None, role: str = "teacher"):
        """Назначить тест студентам"""
        test = await self.test_repo.get_test_by_id(test_id)
        if not test:
            raise ValueError("Тест не найден")
        
        if role == "teacher" and test.creator_id != teacher_id:
            raise PermissionError("Вы не можете назначать этот тест")
        
        students = await self.teacher_student_repo.get_students_by_ids(user_ids)
        if len(students) != len(user_ids):
            raise ValueError("Некоторые пользователи не найдены или не являются студентами")
        
        missing = await self.teacher_student_repo.check_students_belong_to_teacher(user_ids, teacher_id)
        if missing:
            raise PermissionError(f"Вы не можете назначать тесты студентам: {missing}")
        
        created_assignments = []
        existing_assignments = []
        for user_id in user_ids:
            existing = await self.assignment_repo.check_existing_assignment(test_id, user_id)
            if existing:
                existing_assignments.append(existing)
                continue
            
            assignment = await self.assignment_repo.create_assignment(
                test_id=test_id,
                user_id=user_id,
                due_date=due_date
            )
            created_assignments.append(assignment)
        
        if created_assignments:
            await self.db.commit()
            for a in created_assignments:
                await self.db.refresh(a)
        
        all_assignments = created_assignments + existing_assignments
        
        result = []
        for assignment in all_assignments:
            student = await self.user_repo.get_user_by_id(assignment.user_id)
            result.append(TeacherAssignmentItemResponse(
                id=assignment.id if assignment.id else 0,
                test_id=assignment.test_id,
                test_title=test.title,
                user_id=assignment.user_id,
                student_name=f"{student.first_name} {student.last_name}" if student else "Неизвестный",
                assigned_at=assignment.assigned_at,
                due_date=assignment.due_date,
                is_completed=assignment.is_completed if assignment.is_completed is not None else False,
                completed_at=assignment.completed_at,
            ))
        
        return result
    
    async def get_test_assignments(self, test_id: int, teacher_id: int, role: str):
        """Получить назначения для теста"""
        test = await self.test_repo.get_test_by_id(test_id)
        if not test:
            raise ValueError("Тест не найден")
        
        if role == "teacher" and test.creator_id != teacher_id:
            raise PermissionError("Вы не можете просматривать назначения этого теста")
        
        max_points = self.test_repo.calculate_test_max_points(test)
        
        assignments = await self.assignment_repo.get_test_assignments(test_id)
        latest_results = await self.assignment_repo.get_latest_results_for_test(test_id)
        results_map = {r.user_id: r for r in latest_results}
        
        result = []
        for assignment in assignments:
            student = await self.user_repo.get_user_by_id(assignment.user_id)
            latest_result = results_map.get(assignment.user_id)
            
            is_completed = latest_result is not None
            completed_at = latest_result.completed_at if latest_result else None
            total_points = latest_result.total_points if latest_result else None
            result_id = latest_result.id if latest_result else None
            
            percentage = round((total_points / max_points) * 100, 1) if (total_points is not None and max_points > 0) else None
            
            result.append(TeacherAssignmentItemResponse(
                id=assignment.id,
                test_id=assignment.test_id,
                test_title=test.title,
                user_id=assignment.user_id,
                student_name=f"{student.first_name} {student.last_name}" if student else "Неизвестный",
                student_username=student.username if student else None,
                assigned_at=assignment.assigned_at,
                due_date=assignment.due_date,
                is_completed=is_completed,
                completed_at=completed_at,
                total_tasks=len(test.tasks) if test.tasks else 0,
                total_points=total_points,
                max_points=max_points,
                percentage=percentage,
                result_id=result_id,
            ))
        
        result.sort(key=lambda x: (x.is_completed, x.student_name))
        return result
    
    async def get_student_assignments(self, student_id: int, teacher_id: int, role: str):
        """Получить назначения студента"""
        student = await self.user_repo.get_user_by_id(student_id)
        if not student or student.role != "student":
            raise ValueError("Студент не найден")
        
        if role == "teacher":
            if not await self.teacher_student_repo.check_student_belongs_to_teacher(student_id, teacher_id):
                raise PermissionError("У вас нет доступа к этому ученику")
        
        assignments = await self.assignment_repo.get_user_assignments(student_id)
        latest_results = await self.assignment_repo.get_latest_results_for_student(student_id)
        results_map = {r.test_id: r for r in latest_results}
        
        response = []
        for assignment in assignments:
            test = await self.test_repo.get_test_by_id(assignment.test_id)
            if not test:
                continue
            
            latest_result = results_map.get(assignment.test_id)
            is_completed = latest_result is not None
            completed_at = latest_result.completed_at if latest_result else None
            total_points = latest_result.total_points if latest_result else None
            result_id = latest_result.id if latest_result else None
            
            max_points = self.test_repo.calculate_test_max_points(test)
            percentage = round((total_points / max_points) * 100, 1) if (total_points is not None and max_points > 0) else None
            
            response.append(TeacherAssignmentItemResponse(
                id=assignment.id,
                test_id=assignment.test_id,
                test_title=test.title,
                user_id=assignment.user_id,
                student_name=f"{student.first_name} {student.last_name}",
                student_username=student.username,
                assigned_at=assignment.assigned_at,
                due_date=assignment.due_date,
                is_completed=is_completed,
                completed_at=completed_at,
                total_tasks=len(test.tasks) if test.tasks else 0,
                total_points=total_points,
                max_points=max_points,
                percentage=percentage,
                result_id=result_id,
            ))
        
        return response
    
    async def delete_assignment(self, assignment_id: int, teacher_id: int, role: str):
        """Удалить назначение"""
        assignment = await self.assignment_repo.get_assignment_by_id(assignment_id)
        if not assignment:
            raise ValueError("Назначение не найдено")
        
        test = await self.test_repo.get_test_by_id(assignment.test_id)
        if not test:
            raise ValueError("Связанный тест не найден")
        
        if role == "teacher" and test.creator_id != teacher_id:
            raise PermissionError("Вы не можете удалить это назначение")
        
        await self.assignment_repo.delete_assignment_by_obj(assignment)
        await self.db.commit()
        
        return MessageResponse(message="Назначение удалено")
    
    async def assign_test_to_group(self, group_id: int, test_id: int, teacher_id: int,
                        due_date=None, role: str = "teacher"):
        """Назначить тест всей группе"""
        group = await self.group_repo.get_group_by_id(group_id, teacher_id)
        if not group:
            raise ValueError("Группа не найдена")
        
        student_ids = await self.group_repo.get_student_ids_by_group(group_id, teacher_id)
        if not student_ids:
            raise ValueError("В группе нет студентов")
        
        test = await self.test_repo.get_test_by_id(test_id)
        if not test:
            raise ValueError("Тест не найден")
        
        if role == "teacher" and test.creator_id != teacher_id:
            raise PermissionError("Вы не можете назначать этот тест")
        
        created = 0
        for student_id in student_ids:
            existing = await self.assignment_repo.check_existing_assignment(test_id, student_id)
            if existing:
                continue
            
            await self.assignment_repo.create_assignment(
                test_id=test_id,
                user_id=student_id,
                due_date=due_date,
                group_id=group.id
            )
            created += 1
        
        if created > 0:
            await self.db.commit()
        
        return GroupAssignResponse(
            message=f"Тест назначен {created} студентам группы '{group.name}'",
            assigned_count=created,
            group_id=group.id,
            test_id=test_id,
        )
    
    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================
    
    async def _format_detailed_result(self, result) -> DetailedResultResponse:
        """Форматировать детальный результат"""
        if not result.test:
            return DetailedResultResponse(
                test_title="Тест удалён",
                total_points=result.total_points or 0,
                max_points=0,
                completed_at=result.completed_at,
                difficulty_stats={},
                user=ResultUserResponse(
                    first_name=result.user.first_name if result.user else "Неизвестный",
                    last_name=result.user.last_name if result.user else "",
                ),
                details=[],
            )
        
        all_tasks = await self.task_repo.get_tasks_by_test_id(result.test_id)
        user_answers = await self.result_repo.get_user_answers_for_result(result.id)
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
            total_points=result.total_points or 0,
            max_points=total_max_points,
            completed_at=result.completed_at,
            difficulty_stats=difficulty_stats,
            user=ResultUserResponse(
                first_name=result.user.first_name if result.user else "Неизвестный",
                last_name=result.user.last_name if result.user else "",
            ),
            details=details,
        )
    
        # ==================== УПРАВЛЕНИЕ ГРУППАМИ ====================
    
    async def get_my_groups(self, teacher_id: int):
        """Получить все группы учителя"""
        groups = await self.group_repo.get_teacher_groups(teacher_id)
        
        result = []
        for group in groups:
            result.append(TeacherGroupResponse(
                id=group.id,
                name=group.name,
                description=group.description,
                students_count=len(group.students),
                created_at=group.created_at,
                students=[
                    TeacherGroupStudentResponse(
                        id=s.id,
                        first_name=s.first_name,
                        last_name=s.last_name,
                        username=s.username,
                        tg_username=s.tg_username,
                    )
                    for s in group.students
                ],
            ))
        
        return result
    
    async def create_group(self, name: str, teacher_id: int, description: str = None):
        """Создать новую группу"""
        if not name:
            raise ValueError("Название группы обязательно")
        
        return await self.group_repo.create_group(name, teacher_id, description)
    
    async def update_group(self, group_id: int, teacher_id: int, name: str = None, description: str = None):
        """Обновить группу"""
        group = await self.group_repo.get_group_by_id(group_id, teacher_id)
        if not group:
            raise ValueError("Группа не найдена")
        
        if name:
            existing = await self.group_repo.get_group_by_name(name, teacher_id)
            if existing and existing.id != group_id:
                raise PermissionError("Группа с таким названием уже существует")
        
        return await self.group_repo.update_group(group, name, description)
    
    async def delete_group(self, group_id: int, teacher_id: int):
        """Удалить группу"""
        group = await self.group_repo.get_group_by_id(group_id, teacher_id)
        if not group:
            raise ValueError("Группа не найдена")
        
        await self.group_repo.delete_group(group)
        await self.db.commit()
        return MessageResponse(message=f"Группа '{group.name}' удалена")
    
    async def add_students_to_group(self, group_id: int, teacher_id: int, student_ids: list):
        """Добавить студентов в группу"""
        group = await self.group_repo.get_group_by_id(group_id, teacher_id)
        if not group:
            raise ValueError("Группа не найдена")
        
        if not student_ids:
            raise ValueError("Не указаны студенты")
        
        added = await self.group_repo.add_students(group, student_ids, teacher_id)
        
        return AddStudentsToGroupResponse(
            message=f"Добавлено {added} студентов в группу '{group.name}'",
            added=added,
        )
    
    async def remove_student_from_group(self, group_id: int, student_id: int, teacher_id: int):
        """Удалить студента из группы"""
        group = await self.group_repo.get_group_by_id(group_id, teacher_id)
        if not group:
            raise ValueError("Группа не найдена")
        
        if not await self.group_repo.remove_student(group, student_id):
            raise ValueError("Студент не в группе")
        
        await self.db.commit()
        return MessageResponse(message="Студент удалён из группы")
    
    async def get_group_students(self, group_id: int, teacher_id: int):
        """Получить список студентов группы"""
        group = await self.group_repo.get_group_by_id(group_id, teacher_id)
        if not group:
            raise ValueError("Группа не найдена")
        
        return [
            TeacherGroupStudentResponse(
                id=s.id,
                first_name=s.first_name,
                last_name=s.last_name,
                username=s.username,
                tg_username=s.tg_username,
            )
            for s in group.students
        ]
    
    async def get_tasks_by_topic_section(self, topic: str, section: str):
        """Получить задания по теме и разделу"""
        return await self.task_repo.get_tasks_by_topic_and_section(topic, section)

    async def get_test_tasks(self, test_id: int, teacher_id: int, role: str):
        """Получить задания теста (для ленивой загрузки)"""
        test = await self.test_repo.get_test_with_tasks(test_id)
        if not test:
            raise ValueError("Тест не найден")
        if role == "teacher" and test.creator_id != teacher_id:
            raise PermissionError("У вас нет доступа к этому тесту")
        
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
    
    async def get_tasks_by_class_and_topic(self, task_class: str, topic_number: str):
        return await self.task_repo.get_tasks_by_class_and_topic(task_class, topic_number)
    
    def get_tasks_meta_by_topic_section(self):
        """Получить метаинформацию по topic и section: { topic: { section: count } }"""
        tasks = self.task_repo.get_all_tasks()
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




class PermissionError(Exception):
    """Ошибка доступа"""
    pass