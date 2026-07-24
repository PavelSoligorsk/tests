"""
Redis-кеширование для эндпоинтов FastAPI с поддержкой Pydantic и SQLAlchemy.

Использование:
    from core.cache import cache_result, invalidate_user_cache
    
    # Кеширование с автоматической сериализацией
    @router.get("/tests")
    def get_tests():
        return cache_result(
            "available_tests",
            None,
            lambda: service.get_available_tests(),
            ttl=600
        )
"""

import json
import os
import hashlib
from typing import Optional, Callable, Any, TypeVar, List
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from uuid import UUID
from enum import Enum

try:
    import redis as redis_lib
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Pydantic поддержка
try:
    from pydantic import BaseModel
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

# SQLAlchemy поддержка
try:
    from sqlalchemy.orm import Query
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

redis_client = None
T = TypeVar('T')


class CustomJSONEncoder(json.JSONEncoder):
    """Кастомный JSON энкодер для Pydantic, SQLAlchemy и других объектов"""
    
    def default(self, obj):
        # Pydantic модели
        if PYDANTIC_AVAILABLE and isinstance(obj, BaseModel):
            return obj.model_dump() if hasattr(obj, 'model_dump') else obj.dict()
        
        # SQLAlchemy модели
        if SQLALCHEMY_AVAILABLE:
            if hasattr(obj, '__table__'):
                return self._sqlalchemy_to_dict(obj)
            if isinstance(obj, Query):
                return str(obj)
        
        # Даты и время
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, time):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return obj.total_seconds()
        
        # Decimal
        if isinstance(obj, Decimal):
            return float(obj)
        
        # UUID
        if isinstance(obj, UUID):
            return str(obj)
        
        # Enum
        if isinstance(obj, Enum):
            return obj.value
        
        # Наборы и кортежи
        if isinstance(obj, (set, tuple)):
            return list(obj)
        
        # Объекты с __dict__
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        
        return super().default(obj)
    
    def _sqlalchemy_to_dict(self, obj):
        """Преобразование SQLAlchemy модели в словарь"""
        result = {}
        for column in obj.__table__.columns:
            value = getattr(obj, column.name)
            if isinstance(value, (datetime, date, time, timedelta, Decimal, UUID)):
                result[column.name] = self.default(value)
            else:
                result[column.name] = value
        return result


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
        except Exception as e:
            print(f"Redis connection failed: {e}")
            redis_client = None
    return redis_client


def _serialize_result(result: Any) -> str:
    """
    Сериализация результата с поддержкой Pydantic, SQLAlchemy и других объектов
    """
    try:
        # Если результат - список SQLAlchemy объектов
        if SQLALCHEMY_AVAILABLE and isinstance(result, list) and result:
            if all(hasattr(item, '__table__') for item in result):
                return json.dumps(
                    [CustomJSONEncoder()._sqlalchemy_to_dict(item) for item in result],
                    cls=CustomJSONEncoder,
                    ensure_ascii=False
                )
        
        # Если результат - список Pydantic моделей
        if PYDANTIC_AVAILABLE and isinstance(result, list) and result:
            if all(isinstance(item, BaseModel) for item in result):
                return json.dumps(
                    [item.model_dump() if hasattr(item, 'model_dump') else item.dict() for item in result],
                    cls=CustomJSONEncoder,
                    ensure_ascii=False
                )
        
        # Стандартная сериализация
        return json.dumps(result, cls=CustomJSONEncoder, default=str, ensure_ascii=False)
    
    except Exception as e:
        # Если JSON не работает, сохраняем как строку
        return json.dumps(str(result))


def _deserialize_result(data: str) -> Any:
    """
    Десериализация результата
    """
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data


def generate_cache_key(prefix: str, user_id: Optional[int] = None, 
                      *args, **kwargs) -> str:
    """
    Генерация ключа кеша с учетом параметров.
    """
    key_parts = [prefix]
    
    if user_id is not None:
        key_parts.append(str(user_id))
    
    # Добавляем хеш от дополнительных параметров
    if args or kwargs:
        try:
            params_str = json.dumps({
                'args': args,
                'kwargs': kwargs
            }, sort_keys=True, default=str)
            params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
            key_parts.append(params_hash)
        except:
            key_parts.append(str(hash(str(args) + str(kwargs)))[:8])
    
    return ":".join(key_parts)


def cache_result(
    prefix: str, 
    user_id: Optional[int], 
    fetcher: Callable[[], Any], 
    ttl: int = 300,
    force_refresh: bool = False,
    *args, **kwargs
) -> Any:
    """
    Универсальная функция кеширования с поддержкой Pydantic и SQLAlchemy.
    """
    redis_conn = get_redis()
    if redis_conn is None:
        return fetcher()
    
    cache_key = generate_cache_key(prefix, user_id, *args, **kwargs)
    
    if not force_refresh:
        try:
            cached = redis_conn.get(cache_key)
            if cached is not None:
                return _deserialize_result(cached)
        except Exception:
            pass
    
    # Получаем свежие данные
    result = fetcher()
    
    # Сохраняем в кеш
    try:
        serialized = _serialize_result(result)
        redis_conn.setex(cache_key, ttl, serialized)
    except Exception as e:
        pass
    
    return result


def invalidate_user_cache(user_id: int, *prefixes: str):
    """
    Инвалидировать кеш пользователя по указанным префиксам.
    """
    redis_conn = get_redis()
    if redis_conn is None:
        return

    for prefix in prefixes:
        patterns = [
            f"{prefix}:{user_id}",
            f"{prefix}:{user_id}:*",
        ]
        
        for pattern in patterns:
            try:
                keys = redis_conn.keys(pattern)
                if keys:
                    redis_conn.delete(*keys)
            except Exception:
                pass


def invalidate_cache_pattern(pattern: str):
    """Инвалидировать кеш по glob-паттерну"""
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
    """Инвалидировать весь кеш пользователя"""
    invalidate_user_cache(
        user_id,
        "student_profile",
        "my_history",
        "my_assignments",
        "my_assignments_meta",
        "my_ai_tests"
    )


# Декоратор для кеширования
def cached(prefix: str, ttl: int = 300, user_key: bool = True):
    """
    Декоратор для кеширования результатов функций.
    
    Пример:
        @cached("my_profile", ttl=600)
        def get_profile(user_id: int):
            return {"id": user_id, "name": "John"}
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            user_id = None
            if user_key:
                if 'user_id' in kwargs:
                    user_id = kwargs['user_id']
                elif 'current_user' in kwargs and hasattr(kwargs['current_user'], 'id'):
                    user_id = kwargs['current_user'].id
                elif args:
                    for arg in args:
                        if hasattr(arg, 'id') and hasattr(arg, '__class__'):
                            user_id = arg.id
                            break
                        elif isinstance(arg, int):
                            user_id = arg
                            break
            
            return cache_result(
                prefix,
                user_id,
                lambda: func(*args, **kwargs),
                ttl=ttl,
                *args,
                **kwargs
            )
        return wrapper
    return decorator