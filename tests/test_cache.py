"""
Cache unit-tests: key generation, pydantic serialization loop,
cache_result / async_cache_result (hit, miss, fallback),
invalidation helpers (user, pattern, all-user).
Uses fakeredis for realistic Redis simulation.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

import core.cache as cache_mod


# ---------------------------------------------------------------------------
# Minimal Pydantic model for serialization round-trip assertions
# ---------------------------------------------------------------------------

class _Widget(BaseModel):
    id: int
    name: str


# ---------------------------------------------------------------------------
# Fixtures – fakeredis wired into cache_mod
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache_state():
    """Reset global state so each test starts clean."""
    cache_mod.redis_client = None
    # We do NOT override get_redis globally so each test can patch freely.
    yield
    cache_mod.redis_client = None


@pytest.fixture
def fake_redis():
    """Return a fresh fakeredis connection (decode_responses=True)."""
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


# ---------------------------------------------------------------------------
# 1. generate_cache_key
# ---------------------------------------------------------------------------


class TestGenerateCacheKey:
    """Unit-tests for cache key generation."""

    def test_prefix_only(self):
        key = cache_mod.generate_cache_key("tasks")
        assert key == "tasks"

    def test_prefix_and_user(self):
        key = cache_mod.generate_cache_key("profile", user_id=42)
        assert key == "profile:42"

    def test_prefix_user_entity(self):
        key = cache_mod.generate_cache_key("result", user_id=5, entity_id=99)
        assert key == "result:5:99"

    def test_prefix_user_entity_and_args(self):
        key = cache_mod.generate_cache_key("x", user_id=1, entity_id=2, "a", b="c")
        parts = key.split(":")
        assert parts[0] == "x"
        assert parts[1] == "1"
        assert parts[2] == "2"
        assert len(parts[3]) == 8  # md5 hex digest[:8]

    def test_deterministic(self):
        a = cache_mod.generate_cache_key("t", 1, 2, "hello", mode="strict")
        b = cache_mod.generate_cache_key("t", 1, 2, "hello", mode="strict")
        assert a == b

    def test_different_args_different_key(self):
        a = cache_mod.generate_cache_key("t", 1, 2, "a")
        b = cache_mod.generate_cache_key("t", 1, 2, "b")
        assert a != b


# ---------------------------------------------------------------------------
# 2. Serialization / deserialization round-trip
# ---------------------------------------------------------------------------


class TestPydanticSerialization:
    """_serialize_pydantic → _deserialize_pydantic must be lossless."""

    def test_single_model(self):
        w = _Widget(id=1, name="alpha")
        raw = cache_mod._serialize_pydantic(w)
        restored = cache_mod._deserialize_pydantic(raw, _Widget)
        assert restored == w

    def test_list_of_models(self):
        items = [_Widget(id=i, name=f"item-{i}") for i in range(3)]
        raw = cache_mod._serialize_pydantic(items)
        restored = cache_mod._deserialize_pydantic(raw, _Widget)
        assert restored == items

    def test_empty_list_serialization(self):
        raw = cache_mod._serialize_pydantic([])
        assert raw == "[]"

    def test_empty_list_deserialization(self):
        restored = cache_mod._deserialize_pydantic("[]", _Widget)
        assert restored == []


# ---------------------------------------------------------------------------
# 3. cache_result (sync) – via fakeredis
# ---------------------------------------------------------------------------


class TestCacheResultSync:
    """cache_result with a real (fakeredis) Redis backend."""

    def test_miss_then_hit(self, fake_redis, monkeypatch):
        """First call fetches; second call returns from cache."""
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        call_count = 0

        def fetcher():
            nonlocal call_count
            call_count += 1
            return _Widget(id=7, name="fetched")

        # -- Miss --
        result1 = cache_mod.cache_result(
            "widget", user_id=1, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert call_count == 1
        assert result1 == _Widget(id=7, name="fetched")

        # -- Hit --
        result2 = cache_mod.cache_result(
            "widget", user_id=1, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert call_count == 1  # fetcher NOT called again
        assert result2 == _Widget(id=7, name="fetched")

    def test_force_refresh_calls_fetcher(self, fake_redis, monkeypatch):
        """force_refresh=True ignores cache and re-fetches."""
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        call_count = 0

        def fetcher():
            nonlocal call_count
            call_count += 1
            return _Widget(id=call_count, name="v")

        # seed cache
        cache_mod.cache_result(
            "w", user_id=2, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert call_count == 1

        # force refresh
        r = cache_mod.cache_result(
            "w", user_id=2, fetcher=fetcher, model_class=_Widget, ttl=60,
            force_refresh=True,
        )
        assert call_count == 2
        assert r.id == 2

    def test_no_redis_falls_back_to_fetcher(self, monkeypatch):
        """When get_redis returns None, result still comes from fetcher."""
        monkeypatch.setattr(cache_mod, "get_redis", lambda: None)

        def fetcher():
            return _Widget(id=10, name="fallback")

        r = cache_mod.cache_result(
            "fb", user_id=3, fetcher=fetcher, model_class=_Widget,
        )
        assert r == _Widget(id=10, name="fallback")

    def test_no_model_class_returns_raw(self, fake_redis, monkeypatch):
        """Without model_class, raw fetcher value is stored and returned as JSON."""
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        raw = {"a": 1, "b": [2]}

        def fetcher():
            return raw

        r = cache_mod.cache_result("raw", user_id=5, fetcher=fetcher, ttl=60)
        assert r == raw

    def test_list_of_models(self, fake_redis, monkeypatch):
        """List of Pydantic models is cached correctly."""
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        items = [_Widget(id=1, name="a"), _Widget(id=2, name="b")]

        def fetcher():
            return items

        r1 = cache_mod.cache_result(
            "list", user_id=1, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert r1 == items

        # second call hits cache
        r2 = cache_mod.cache_result(
            "list", user_id=1, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert r2 == items

    def test_non_pydantic_not_cached(self, fake_redis, monkeypatch):
        """Non-Pydantic result is not cached (warning logged, raw returned)."""
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        def fetcher():
            return 42

        r = cache_mod.cache_result("int", user_id=1, fetcher=fetcher, ttl=60)
        assert r == 42

        # not cached — should not be in Redis
        key = cache_mod.generate_cache_key("int", user_id=1)
        assert fake_redis.get(key) is None


# ---------------------------------------------------------------------------
# 4. async_cache_result – via fakeredis
# ---------------------------------------------------------------------------


class TestCacheResultAsync:
    """async_cache_result with fakeredis."""

    async def test_miss_then_hit(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return _Widget(id=77, name="async-fetched")

        r1 = await cache_mod.async_cache_result(
            "aw", user_id=10, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert call_count == 1
        assert r1.id == 77

        r2 = await cache_mod.async_cache_result(
            "aw", user_id=10, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert call_count == 1  # cache hit
        assert r2.id == 77

    async def test_no_redis_falls_back(self, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: None)

        async def fetcher():
            return _Widget(id=1, name="noredis")

        r = await cache_mod.async_cache_result(
            "nr", user_id=5, fetcher=fetcher, model_class=_Widget,
        )
        assert r == _Widget(id=1, name="noredis")

    async def test_force_refresh(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return _Widget(id=call_count, name="v")

        # seed
        await cache_mod.async_cache_result(
            "fr", user_id=1, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert call_count == 1

        # force
        r = await cache_mod.async_cache_result(
            "fr", user_id=1, fetcher=fetcher, model_class=_Widget, ttl=60,
            force_refresh=True,
        )
        assert call_count == 2
        assert r.id == 2

    async def test_list_of_models_async(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        items = [_Widget(id=1, name="x"), _Widget(id=2, name="y")]

        async def fetcher():
            return items

        r = await cache_mod.async_cache_result(
            "alist", user_id=1, fetcher=fetcher, model_class=_Widget, ttl=60,
        )
        assert r == items


# ---------------------------------------------------------------------------
# 5. invalidate_user_cache
# ---------------------------------------------------------------------------


class TestInvalidateUserCache:
    """invalidate_user_cache removes keys by user-scoped patterns."""

    def test_removes_exact_and_prefixed_keys(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        # seed keys
        fake_redis.set("profile:42", "a")
        fake_redis.set("profile:42:extra", "b")
        fake_redis.set("profile:7", "c")  # should survive

        cache_mod.invalidate_user_cache(42, "profile")

        assert fake_redis.get("profile:42") is None
        assert fake_redis.get("profile:42:extra") is None
        assert fake_redis.get("profile:7") == "c"

    def test_multiple_prefixes(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        fake_redis.set("a:1", "x")
        fake_redis.set("b:1", "y")
        fake_redis.set("c:2", "z")  # different user, survives

        cache_mod.invalidate_user_cache(1, "a", "b")

        assert fake_redis.get("a:1") is None
        assert fake_redis.get("b:1") is None
        assert fake_redis.get("c:2") == "z"

    def test_no_redis_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: None)
        # Should not raise
        cache_mod.invalidate_user_cache(1, "anything")


# ---------------------------------------------------------------------------
# 6. invalidate_cache_pattern
# ---------------------------------------------------------------------------


class TestInvalidateCachePattern:
    """invalidate_cache_pattern removes keys matching a glob."""

    def test_removes_matching_keys(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        fake_redis.set("tasks:all", "1")
        fake_redis.set("tasks:meta", "2")
        fake_redis.set("users:1", "3")  # should survive

        cache_mod.invalidate_cache_pattern("tasks:*")

        assert fake_redis.get("tasks:all") is None
        assert fake_redis.get("tasks:meta") is None
        assert fake_redis.get("users:1") == "3"

    def test_no_redis_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: None)
        cache_mod.invalidate_cache_pattern("x:*")


# ---------------------------------------------------------------------------
# 7. invalidate_all_user_cache
# ---------------------------------------------------------------------------


class TestInvalidateAllUserCache:
    """invalidate_all_user_cache clears all known user-cache prefixes."""

    def test_clears_all_known_prefixes(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        prefixes = (
            "student_profile",
            "my_history",
            "my_assignments",
            "my_assignments_meta",
            "my_ai_tests",
            "detailed_result",
        )
        for pfx in prefixes:
            fake_redis.set(f"{pfx}:99", "v")
            fake_redis.set(f"{pfx}:99:sub", "vv")

        # unrelated key
        fake_redis.set("other:99", "keep")

        cache_mod.invalidate_all_user_cache(99)

        for pfx in prefixes:
            assert fake_redis.get(f"{pfx}:99") is None, f"{pfx}:99 not cleared"
            assert fake_redis.get(f"{pfx}:99:sub") is None, f"{pfx}:99:sub not cleared"

        assert fake_redis.get("other:99") == "keep"


# ---------------------------------------------------------------------------
# 8. _materialize_model helper
# ---------------------------------------------------------------------------


class TestMaterializeModel:
    """_materialize_model converts ORM-like payloads into Pydantic DTOs."""

    def test_single_dict(self):
        result = cache_mod._materialize_model({"id": 1, "name": "single"}, _Widget)
        assert result == _Widget(id=1, name="single")

    def test_list_of_dicts(self):
        result = cache_mod._materialize_model(
            [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
            _Widget,
        )
        assert result == [_Widget(id=1, name="a"), _Widget(id=2, name="b")]

    def test_pydantic_instance_passthrough(self):
        """Already a Pydantic model — validate, don't double-wrap."""
        w = _Widget(id=5, name="passthrough")
        result = cache_mod._materialize_model(w, _Widget)
        assert result == w


# ---------------------------------------------------------------------------
# 9. Edge-case: fetcher exception propagation
# ---------------------------------------------------------------------------


class TestCacheErrorPropagation:
    """Fetcher failures bubble up through cache layer."""

    def test_sync_fetcher_exception(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        def fetcher():
            raise RuntimeError("DB down")

        with pytest.raises(RuntimeError, match="DB down"):
            cache_mod.cache_result("fail", user_id=1, fetcher=fetcher, model_class=_Widget)

    async def test_async_fetcher_exception(self, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_mod, "get_redis", lambda: fake_redis)

        async def fetcher():
            raise RuntimeError("DB down")

        with pytest.raises(RuntimeError, match="DB down"):
            await cache_mod.async_cache_result(
                "fail", user_id=1, fetcher=fetcher, model_class=_Widget,
            )


# ---------------------------------------------------------------------------
# 10. Redis write failure – graceful degradation
# ---------------------------------------------------------------------------


class TestCacheWriteFailure:
    """When Redis write fails, result is still returned (fail-open)."""

    def test_sync_write_failure(self, monkeypatch):
        """setex raises → result returned, no exception raised."""

        class BrokenRedis:
            """Fake that reads OK but fails on write."""

            def __init__(self):
                self._store: dict[str, str] = {}

            def get(self, key: str):
                return self._store.get(key)

            def setex(self, key, ttl, value):
                raise OSError("Redis write failed")

        broken = BrokenRedis()
        monkeypatch.setattr(cache_mod, "get_redis", lambda: broken)

        def fetcher():
            return _Widget(id=3, name="ok")

        r = cache_mod.cache_result(
            "broken", user_id=1, fetcher=fetcher, model_class=_Widget,
        )
        assert r == _Widget(id=3, name="ok")

    async def test_async_write_failure(self, monkeypatch):
        class BrokenRedis:
            def __init__(self):
                self._store: dict[str, str] = {}

            def get(self, key: str):
                return self._store.get(key)

            def setex(self, key, ttl, value):
                raise OSError("Redis write failed")

        broken = BrokenRedis()
        monkeypatch.setattr(cache_mod, "get_redis", lambda: broken)

        async def fetcher():
            return _Widget(id=4, name="async-ok")

        r = await cache_mod.async_cache_result(
            "broken", user_id=1, fetcher=fetcher, model_class=_Widget,
        )
        assert r == _Widget(id=4, name="async-ok")
