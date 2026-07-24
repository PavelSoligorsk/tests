"""
Redis-кеширование для эндпоинтов FastAPI.

Использование:
    from core.cache import cache_result, invalidate_user_cache

    # Кеширование результата
    result = cache_result(prefix, user_id, lambda: expensive_func(), ttl=300)

    # Инвалидация
    invalidate_user_cache(user_id, "get_student_profile")
    invalidate_cache_pattern("get_tests_meta:*")
"""

import json
import os
from typing import Optional, Callable, Any

try:
    import redis as redis_lib
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

redis_client = None


def get_redis() -> Optional[object]:
    """Получить Redis-клиент (ленивая инициализация)"""
    global redis_client
    if not REDIS_AVAILABLE:
        return None
    if redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            redis_client = redis_lib.from_url(redis_url, decode_responses=True)
            redis_client.ping()
        except Exception:
            redis_client = None
    return redis_client


def cache_result(prefix: str, user_id: Optional[int], fetcher: Callable[[], Any], ttl: int = 300) -> Any:
    """
    Универсальная функция кеширования.
    Args:
        prefix: Префикс ключа (например "get_student_profile")
        user_id: ID пользователя (или None для глобального кеша)
        fetcher: Функция, которая возвращает данные (вызывается при промахе кеша)
        ttl: Время жизни в секундах

    Returns:
        Данные (из кеша или свежеполученные)
    """
    redis_conn = get_redis()
    if redis_conn is None:
        return fetcher()

    key_parts = [prefix]
    if user_id is not None:
        key_parts.append(str(user_id))
    cache_key = ":".join(key_parts)
    try:
        cached = redis_conn.get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass

    result = fetcher()
    try:
        redis_conn.setex(cache_key, ttl, json.dumps(result, default=str))
    except Exception:
        pass

    return result


def invalidate_user_cache(user_id: int, *prefixes: str):
    """
    Инвалидировать кеш пользователя по указанным префиксам.

    Args:
        user_id: ID пользователя
        *prefixes: Префиксы ключей (например "get_student_profile")
    """
    redis_conn = get_redis()
    if redis_conn is None:
        return

    for prefix in prefixes:
        pattern = f"{prefix}:{user_id}" if prefix else f"*:{user_id}"
        try:
            keys = redis_conn.keys(pattern)
            if keys:
                redis_conn.delete(*keys)
        except Exception:
            pass


def invalidate_cache_pattern(pattern: str):
    """Инвалидировать кеш по glob-паттерну (например 'get_tests_meta:*')"""
    redis_conn = get_redis()
    if redis_conn is None:
        return

    try:
        keys = redis_conn.keys(pattern)
        if keys:
            redis_conn.delete(*keys)
    except Exception:
        pass


def invalidate_all_user_cache(user_id: int):
    """Инвалидировать весь кеш пользователя (все префиксы)"""
    invalidate_user_cache(user_id, "get_student_profile", "get_my_history",
                          "get_my_assignments_meta", "get_my_ai_tests")