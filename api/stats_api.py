from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from core.models import User
from core import auth
from core.database import get_db
from dto_schemas.stats import PeriodStatsResponse, TopicsStatsResponse, DifficultyStatsResponse, FullStatsResponse
from services.stats_service import StatsService, PermissionError

router = APIRouter(prefix="/stats", tags=["Statistics"])


def get_stats_service(db: Session = Depends(get_db)) -> StatsService:
    return StatsService(db)


# ==================== ДЛЯ ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ ====================

@router.get("/me/period", response_model=PeriodStatsResponse)
def get_my_period_stats(
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_period_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me/topics", response_model=TopicsStatsResponse)
def get_my_topic_stats(
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_topics_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me/difficulty", response_model=DifficultyStatsResponse)
def get_my_difficulty_stats(
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_difficulty_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me/full", response_model=FullStatsResponse)
def get_my_full_stats(
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_full_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== ДЛЯ КОНКРЕТНОГО ПОЛЬЗОВАТЕЛЯ ====================

@router.get("/user/{user_id}/period", response_model=PeriodStatsResponse)
def get_user_period_stats(
    user_id: int,
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_period_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/user/{user_id}/topics", response_model=TopicsStatsResponse)
def get_user_topic_stats(
    user_id: int,
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_topics_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/user/{user_id}/difficulty", response_model=DifficultyStatsResponse)
def get_user_difficulty_stats(
    user_id: int,
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_difficulty_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/user/{user_id}/full", response_model=FullStatsResponse)
def get_user_full_stats(
    user_id: int,
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: User = Depends(auth.get_current_user)
):
    try:
        return service.get_full_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))