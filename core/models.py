import enum
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, JSON, ForeignKey, Enum, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from core.database import Base
import datetime

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default=UserRole.STUDENT)
    
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    tg_username = Column(String, nullable=True)

    # ── Telegram chat_id (для отправки уведомлений учителю) ──
    tg_chat_id = Column(BigInteger, nullable=True)

    # ── Баланс (в копейках BYN) ──
    balance = Column(Integer, default=0)

    # ── Родитель ──
    parent_id = Column(Integer, ForeignKey("parents.id", ondelete="SET NULL"), nullable=True)
    parent = relationship("Parent", backref="students")

    test_results = relationship("TestResult", back_populates="user")
    created_tests = relationship("Test", back_populates="creator")
    my_students = relationship("TeacherStudent", foreign_keys="TeacherStudent.teacher_id", back_populates="teacher")
    my_teachers = relationship("TeacherStudent", foreign_keys="TeacherStudent.student_id", back_populates="student")

    # 🔥 Группы
    groups = relationship("Group", secondary="group_students", back_populates="students")
    owned_groups = relationship("Group", back_populates="teacher", foreign_keys="Group.teacher_id")
    
    # Назначения тестов
    test_assignments = relationship("TestAssignment", back_populates="user", foreign_keys="TestAssignment.user_id")


class Parent(Base):
    """Родитель студента (один родитель → много студентов)"""
    __tablename__ = "parents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    tg_username = Column(String(255), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Group(Base):
    """Группа студентов у учителя"""
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    teacher = relationship("User", back_populates="owned_groups", foreign_keys=[teacher_id])
    students = relationship("User", secondary="group_students", back_populates="groups")
    assignments = relationship("TestAssignment", back_populates="group", foreign_keys="TestAssignment.group_id")


class GroupStudent(Base):
    """Связь группы и студента (многие ко многим)"""
    __tablename__ = "group_students"
    
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime, default=datetime.datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    task_class = Column(String(50), nullable=False, index=True) 
    topic_number = Column(String(50), nullable=False, index=True)
    topic = Column(Text, nullable=True)
    section = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    hint = Column(Text, nullable=True)
    solution = Column(Text, nullable=True)
    answer = Column(String, nullable=False)
    is_open_answer = Column(Boolean, default=False)
    options = Column(JSON, nullable=True)
    difficulty = Column(Integer, default=1, nullable=False)


class Test(Base):
    __tablename__ = "tests"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=True)
    creator_id = Column(Integer, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    target_class = Column(String(50), nullable=True) 
    target_topic = Column(String(50), nullable=True)
    is_autocompile = Column(Boolean, default=True)
    is_ai_generated = Column(Boolean, default=False)

    # ── Правила прохождения ──
    # NULL = unlimited attempts (for auto-compile / AI tests)
    max_attempts = Column(Integer, nullable=True, default=None)
    time_limit_minutes = Column(Integer, nullable=True, default=None)
    allow_interruptions = Column(Boolean, default=True)
    exam_start = Column(DateTime, nullable=True, default=None)
    exam_end = Column(DateTime, nullable=True, default=None)
    
    creator = relationship("User", back_populates="created_tests")
    tasks = relationship("Task", secondary="test_task_association")
    results = relationship("TestResult", back_populates="test")


class TestResult(Base):
    __tablename__ = "test_results"
    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    total_points = Column(Integer, default=0)
    completed_at = Column(DateTime, nullable=True, default=None)
    
    test = relationship("Test", back_populates="results")
    user = relationship("User", back_populates="test_results") 
    answers = relationship("UserAnswer", back_populates="result")

    # ── Timer tracking ──
    started_at = Column(DateTime, nullable=True, default=None)
    time_spent_seconds = Column(Integer, default=0)


class UserAnswer(Base):
    __tablename__ = "user_answers"
    id = Column(Integer, primary_key=True, index=True)
    result_id = Column(Integer, ForeignKey("test_results.id"))
    task_id = Column(Integer, ForeignKey("tasks.id"))
    user_text_answer = Column(String, nullable=False)
    is_correct = Column(Boolean, default=False)
    points_earned = Column(Integer, default=0)
    
    result = relationship("TestResult", back_populates="answers")
    task = relationship("Task")


class TestTaskAssociation(Base):
    __tablename__ = "test_task_association"
    test_id = Column(Integer, ForeignKey("tests.id"), primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), primary_key=True)


class AllowedEmail(Base):
    __tablename__ = "allowed_emails"
    email = Column(String(255), primary_key=True, index=True, nullable=False)


class TestAssignment(Base):
    """Назначение теста студенту или группе"""
    __tablename__ = "test_assignments"
    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Может быть NULL
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)  # 🔥
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)
    due_date = Column(DateTime, nullable=True)
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    
    test = relationship("Test")
    user = relationship("User", back_populates="test_assignments", foreign_keys=[user_id])
    group = relationship("Group", back_populates="assignments", foreign_keys=[group_id])  # 🔥
    
    __table_args__ = (
        UniqueConstraint('test_id', 'user_id', name='unique_test_user_assignment'),
    )


class Theory(Base):
    __tablename__ = "theory"
    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String(255), nullable=False, index=True)
    section = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    
    __table_args__ = (
        UniqueConstraint('topic', 'section', name='unique_topic_section'),
    )


class TeacherStudent(Base):
    """Связь учитель-ученик (многие ко многим)"""
    __tablename__ = "teacher_students"
    teacher_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    teacher = relationship("User", foreign_keys=[teacher_id], back_populates="my_students")
    student = relationship("User", foreign_keys=[student_id], back_populates="my_teachers")

class PasswordResetToken(Base):
    """Токен для сброса пароля"""
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ═══════════════════════════════════════════════════════════════
# Расписание, занятия, оплата
# ═══════════════════════════════════════════════════════════════


class LessonSchedule(Base):
    """Шаблон повторяющегося занятия (еженедельно по дням недели)."""
    __tablename__ = "lesson_schedules"

    id = Column(Integer, primary_key=True, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Тип: индивидуальное или групповое
    schedule_type = Column(String(20), nullable=False, default="individual")  # "individual" | "group"

    # Для индивидуального — student_id, для группового — group_id
    student_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)

    # Дни недели: JSON массив, например ["mon", "wed", "fri"]
    days_of_week = Column(JSON, nullable=False)

    # Время занятия
    time_start = Column(String(5), nullable=False)  # "14:30"
    duration_minutes = Column(Integer, nullable=False, default=60)

    # Стоимость одного занятия
    price_per_lesson = Column(Integer, nullable=True, default=None)

    # Активен ли шаблон (false = отменён, больше не генерирует)
    is_active = Column(Boolean, default=True)

    # До какой даты генерировать (NULL = бессрочно)
    recur_until = Column(DateTime, nullable=True)

    # Когда создан / остановлен
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    stopped_at = Column(DateTime, nullable=True)

    # Relationships
    teacher = relationship("User", foreign_keys=[teacher_id])
    student = relationship("User", foreign_keys=[student_id])
    group = relationship("Group")
    lessons = relationship("Lesson", back_populates="schedule", order_by="Lesson.scheduled_date")


class Lesson(Base):
    """Конкретное проведённое/запланированное занятие."""
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("lesson_schedules.id", ondelete="SET NULL"), nullable=True)

    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)

    # Тип
    lesson_type = Column(String(20), nullable=False, default="individual")
    student_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)

    # Дата и время
    scheduled_date = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=60)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)

    # Статус
    status = Column(String(20), nullable=False, default="scheduled")
    # "scheduled" | "completed" | "cancelled" | "rescheduled"

    # Ссылка на занятие, из которого перенесли (если rescheduled)
    rescheduled_from_id = Column(Integer, ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True)
    rescheduled_to_id = Column(Integer, ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True)

    # Заметка учителя
    teacher_note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    schedule = relationship("LessonSchedule", back_populates="lessons", foreign_keys=[schedule_id])
    teacher = relationship("User", foreign_keys=[teacher_id])
    student = relationship("User", foreign_keys=[student_id])
    group = relationship("Group")
    payments = relationship("Payment", back_populates="lesson")
    rescheduled_from = relationship("Lesson", foreign_keys=[rescheduled_from_id], remote_side=[id])
    rescheduled_to = relationship("Lesson", foreign_keys=[rescheduled_to_id], remote_side=[id])


class Payment(Base):
    """Оплата занятия или абонемента."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Тип оплаты
    payment_type = Column(String(30), nullable=False)
    # "per_lesson" | "monthly" | "package"

    amount = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    # "pending" | "paid" | "cancelled"

    # Для абонементов: сколько занятий оплачено / использовано
    package_total = Column(Integer, nullable=True)   # всего занятий в пакете
    package_used = Column(Integer, nullable=True, default=0)    # уже проведено

    # Для месячных: период действия
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)

    comment = Column(Text, nullable=True)

    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    lesson = relationship("Lesson", back_populates="payments", foreign_keys=[lesson_id])
    student = relationship("User", foreign_keys=[student_id])