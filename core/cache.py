"""Redis caching helpers with DTO-first serialization."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Callable, Optional, TypeVar

try:
    import redis as redis_lib
    REDIS_AVAILABLE = False
except ImportError:
    REDIS_AVAILABLE = False

from pydantic import BaseModel

logger = logging.getLogger(__name__)

redis_client: Any = None
T = TypeVar("T", bound=BaseModel)


def get_redis() -> Any:
    """Lazily initialize Redis and fail closed if the backend is unavailable."""
    global redis_client

    if not REDIS_AVAILABLE:
        logger.warning("Redis package not installed. Caching disabled.")
        return None

    if redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            redis_client = redis_lib.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            redis_client.ping()
            logger.info("Redis connected: %s", redis_url)
        except Exception as exc:
            logger.error("Redis unavailable (%s). Running without cache.", exc)
            redis_client = None

    return redis_client


def generate_cache_key(
    prefix: str,
    user_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    *args: Any,
    **kwargs: Any,
) -> str:
    """Generate hierarchical cache keys of the form prefix:user:entity[:hash]."""
    key_parts = [prefix]

    if user_id is not None:
        key_parts.append(str(user_id))

    if entity_id is not None:
        key_parts.append(str(entity_id))

    if args or kwargs:
        params_str = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        key_parts.append(hashlib.md5(params_str.encode("utf-8")).hexdigest()[:8])

    return ":".join(key_parts)


def _materialize_model(result: Any, model_class: type[T]) -> T | list[T]:
    """Convert ORM payloads into Pydantic DTOs before caching or returning."""
    if isinstance(result, list):
        return [model_class.model_validate(item) for item in result]
    return model_class.model_validate(result)


def _serialize_pydantic(result: BaseModel | list[BaseModel]) -> str:
    if isinstance(result, list):
        return "[" + ",".join(item.model_dump_json() for item in result) + "]"
    return result.model_dump_json()


def _deserialize_pydantic(data: str, model_class: type[T]) -> T | list[T]:
    parsed = json.loads(data)
    if isinstance(parsed, list):
        return [model_class.model_validate_json(json.dumps(item)) for item in parsed]
    return model_class.model_validate_json(data)


def cache_result(
    prefix: str,
    user_id: Optional[int],
    fetcher: Callable[[], Any],
    model_class: type[T] | None = None,
    ttl: int = 300,
    force_refresh: bool = False,
    entity_id: Optional[int] = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Fetch a value, convert ORM payloads to DTOs, and cache the DTO payload."""
    redis_conn = get_redis()
    if redis_conn is None:
        logger.debug("Redis unavailable, fetching data directly")
        result = fetcher()
        if model_class is None:
            return result
        return _materialize_model(result, model_class)

    cache_key = generate_cache_key(prefix, user_id, entity_id, *args, **kwargs)

    if not force_refresh:
        try:
            cached = redis_conn.get(cache_key)
            if cached is not None:
                logger.debug("Cache HIT: %s", cache_key)
                if model_class is None:
                    return json.loads(cached)
                return _deserialize_pydantic(cached, model_class)
            logger.debug("Cache MISS: %s", cache_key)
        except Exception as exc:
            logger.warning("Redis read failed for %s: %s. Fetching from DB.", cache_key, exc)

    try:
        result = fetcher()
    except Exception:
        logger.exception("Fetcher failed for %s", cache_key)
        raise

    try:
        if model_class is not None:
            dto_result = _materialize_model(result, model_class)
        elif isinstance(result, BaseModel):
            dto_result = result
        elif isinstance(result, list) and result and isinstance(result[0], BaseModel):
            dto_result = result
        else:
            logger.warning("Result is not a Pydantic DTO, skipping cache for %s", cache_key)
            return result

        redis_conn.setex(cache_key, ttl, _serialize_pydantic(dto_result))
        logger.debug("Cache SET: %s (TTL: %ss)", cache_key, ttl)
        return dto_result
    except Exception as exc:
        logger.warning("Redis write failed for %s: %s. Data returned without caching.", cache_key, exc)
        if model_class is not None:
            return _materialize_model(result, model_class)
        return result


async def async_cache_result(
    prefix: str,
    user_id: Optional[int],
    fetcher: Callable[[], Any],
    model_class: type[T] | None = None,
    ttl: int = 300,
    force_refresh: bool = False,
    entity_id: Optional[int] = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Async version of cache_result — fetch, convert ORM → DTO, and cache."""
    redis_conn = get_redis()
    if redis_conn is None:
        logger.debug("Redis unavailable, fetching data directly")
        result = await fetcher()
        if model_class is None:
            return result
        return _materialize_model(result, model_class)

    cache_key = generate_cache_key(prefix, user_id, entity_id, *args, **kwargs)

    if not force_refresh:
        try:
            cached = redis_conn.get(cache_key)
            if cached is not None:
                logger.debug("Cache HIT: %s", cache_key)
                if model_class is None:
                    return json.loads(cached)
                return _deserialize_pydantic(cached, model_class)
            logger.debug("Cache MISS: %s", cache_key)
        except Exception as exc:
            logger.warning("Redis read failed for %s: %s. Fetching from DB.", cache_key, exc)

    try:
        result = await fetcher()
    except Exception:
        logger.exception("Fetcher failed for %s", cache_key)
        raise

    try:
        if model_class is not None:
            dto_result = _materialize_model(result, model_class)
        elif isinstance(result, BaseModel):
            dto_result = result
        elif isinstance(result, list) and result and isinstance(result[0], BaseModel):
            dto_result = result
        else:
            logger.warning("Result is not a Pydantic DTO, skipping cache for %s", cache_key)
            return result

        redis_conn.setex(cache_key, ttl, _serialize_pydantic(dto_result))
        logger.debug("Cache SET: %s (TTL: %ss)", cache_key, ttl)
        return dto_result
    except Exception as exc:
        logger.warning("Redis write failed for %s: %s. Data returned without caching.", cache_key, exc)
        if model_class is not None:
            return _materialize_model(result, model_class)
        return result


def invalidate_user_cache(user_id: int, *prefixes: str) -> None:
    """Invalidate all keys for a user without using Redis KEYS."""
    redis_conn = get_redis()
    if redis_conn is None:
        logger.debug("Redis unavailable, skipping cache invalidation")
        return

    for prefix in prefixes:
        for pattern in (f"{prefix}:{user_id}", f"{prefix}:{user_id}:*"):
            try:
                deleted_count = 0
                for key in redis_conn.scan_iter(match=pattern):
                    redis_conn.delete(key)
                    deleted_count += 1
                if deleted_count > 0:
                    logger.info("Invalidated %s keys matching '%s'", deleted_count, pattern)
            except Exception as exc:
                logger.warning("Cache invalidation failed for pattern '%s': %s", pattern, exc)


def invalidate_cache_pattern(pattern: str) -> None:
    """Invalidate by glob pattern using scan_iter only."""
    redis_conn = get_redis()
    if redis_conn is None:
        logger.debug("Redis unavailable, skipping pattern invalidation")
        return

    try:
        deleted_count = 0
        for key in redis_conn.scan_iter(match=pattern):
            redis_conn.delete(key)
            deleted_count += 1
        if deleted_count > 0:
            logger.info("Invalidated %s keys matching '%s'", deleted_count, pattern)
    except Exception as exc:
        logger.warning("Pattern invalidation failed for '%s': %s", pattern, exc)


def invalidate_all_user_cache(user_id: int) -> None:
    invalidate_user_cache(
        user_id,
        "student_profile",
        "my_history",
        "my_assignments",
        "my_assignments_meta",
        "my_ai_tests",
        "detailed_result",
    )
