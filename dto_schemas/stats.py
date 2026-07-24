from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from dto_schemas.user import UserResponse


class UserStats(BaseModel):
    total_attempts: int
    avg_score: float

    model_config = ConfigDict(from_attributes=True)


class UserResponseWithStats(BaseModel):
    user: UserResponse
    stats: UserStats

    model_config = ConfigDict(from_attributes=True)


# ============ PERIOD STATS ============

class DailyStatsItem(BaseModel):
    date: str
    tests_count: int = 0
    total_tasks: int = 0
    correct_tasks: int = 0
    avg_score: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class PeriodStatsResponse(BaseModel):
    period: str
    user_id: int
    user_name: str
    start_date: Optional[str] = None
    end_date: str
    total_tests: int = 0
    total_tasks: int = 0
    correct_tasks: int = 0
    avg_score: float = 0.0
    best_score: float = 0.0
    worst_score: float = 0.0
    streak_days: int = 0
    daily_stats: list[DailyStatsItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ============ TOPICS STATS ============

class TopicSectionItem(BaseModel):
    section: str
    total_tasks: int = 0
    correct_tasks: int = 0
    mastery_percent: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class TopicSummaryItem(BaseModel):
    topic: str
    total_tasks: int = 0
    correct_tasks: int = 0
    mastery_percent: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class TopicItem(TopicSummaryItem):
    sections: list[TopicSectionItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TopicsStatsResponse(BaseModel):
    period: str
    user_id: int
    user_name: str
    topics: list[TopicItem] = Field(default_factory=list)
    strongest_topic: Optional[TopicSummaryItem] = None
    weakest_topic: Optional[TopicSummaryItem] = None

    model_config = ConfigDict(from_attributes=True)


# ============ DIFFICULTY STATS ============

class DifficultyItem(BaseModel):
    difficulty: int
    total_tasks: int = 0
    correct_tasks: int = 0
    mastery_percent: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class DifficultyStatsResponse(BaseModel):
    period: str
    user_id: int
    user_name: str
    difficulties: list[DifficultyItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ============ FULL STATS ============

class FullStatsResponse(BaseModel):
    period: PeriodStatsResponse
    topics: TopicsStatsResponse
    difficulties: DifficultyStatsResponse

    model_config = ConfigDict(from_attributes=True)