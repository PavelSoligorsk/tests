from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import models, auth
from core.database import get_db
from services.stats_service import StatsService, PermissionError

router = APIRouter(prefix="/stats", tags=["Statistics"])


def get_stats_service(db: Session = Depends(get_db)) -> StatsService:
    return StatsService(db)


# ==================== ДЛЯ ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ ====================

@router.get("/me/period")
def get_my_period_stats(
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_period_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me/topics")
def get_my_topic_stats(
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_topics_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me/difficulty")
def get_my_difficulty_stats(
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_difficulty_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me/full")
def get_my_full_stats(
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_full_stats(current_user.id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== ДЛЯ КОНКРЕТНОГО ПОЛЬЗОВАТЕЛЯ ====================

@router.get("/user/{user_id}/period")
def get_user_period_stats(
    user_id: int,
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_period_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/user/{user_id}/topics")
def get_user_topic_stats(
    user_id: int,
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_topics_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/user/{user_id}/difficulty")
def get_user_difficulty_stats(
    user_id: int,
    period: str = Query("all"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_difficulty_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/user/{user_id}/full")
def get_user_full_stats(
    user_id: int,
    period: str = Query("month"),
    service: StatsService = Depends(get_stats_service),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        return service.get_full_stats(user_id, period, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))