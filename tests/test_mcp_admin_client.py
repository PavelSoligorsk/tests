"""Клиент MCP-админки: пакет create/update/delete через HTTP."""

import json

import httpx
import pytest

from mcp_admin.client import AdminApiError, AdminTaskClient


def _client(handler) -> AdminTaskClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://api.test",
    )
    client = AdminTaskClient(http)
    client.base = "http://api.test"
    client._token = "test-token"
    return client


@pytest.mark.asyncio
async def test_apply_create_then_update_then_delete() -> None:
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(200, json={"created": [{"id": 1}], "total": 1})
        if request.method == "PUT":
            return httpx.Response(200, json={"updated": [{"id": 2}], "not_found": [], "total_updated": 1})
        return httpx.Response(200, json={"deleted": [3], "not_found": [], "total_deleted": 1})

    client = _client(handler)
    result = await client.apply(
        create=[{"task_class": "10", "topic_number": "1", "content": "q", "answer": "a"}],
        update=[{"id": 2, "difficulty": 3}],
        delete_ids=[3],
    )
    assert [item[0] for item in seen] == ["POST", "PUT", "DELETE"]
    assert result["create"]["total"] == 1
    assert result["update"]["total_updated"] == 1
    assert result["delete"]["total_deleted"] == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_apply_stops_after_create_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "options обязателен"})

    client = _client(handler)
    with pytest.raises(AdminApiError) as exc:
        await client.apply(
            create=[{"content": "bad"}],
            delete_ids=[1],
        )
    assert exc.value.status_code == 422
    await client.aclose()


@pytest.mark.asyncio
async def test_create_chunks_over_batch_limit(monkeypatch) -> None:
    monkeypatch.setattr("mcp_admin.client.BATCH_LIMIT", 2)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        assert len(body["tasks"]) <= 2
        created = [{"id": calls}]
        return httpx.Response(200, json={"created": created, "total": 1})

    client = _client(handler)
    result = await client.create_tasks([{"n": i} for i in range(5)])
    assert calls == 3
    assert result["total"] == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_yaml_inserts_screenshot_url_into_content() -> None:
    sent_content = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/upload-image"):
            return httpx.Response(200, json={"url": "https://cdn.example/tasks/fig.png", "filename": "fig.png"})
        sent_content["content"] = body["tasks"][0]["content"]
        sent_content["answer"] = body["tasks"][0]["answer"]
        assert "image" not in body["tasks"][0]
        return httpx.Response(200, json={"created": [{"id": 9}], "total": 1})

    client = _client(handler)
    yaml_text = """
- task_class: "Выражения и их преобразования"
  topic_number: "Рациональная дробь"
  content: |
    Упростите выражение.
    {{image}}
  options:
    - '$-\\\\frac{6}{5x}$'
  answer: 1
  is_open_answer: false
  difficulty: 2
  topic: expressions
  section: "Рациональная дробь"
  image_base64: "%s"
""" % ("A" * 120)
    result = await client.create_tasks_yaml(yaml_text)
    assert result["total"] == 1
    assert sent_content["answer"] == "1"
    assert "![](https://cdn.example/tasks/fig.png)" in sent_content["content"]
    assert "{{image}}" not in sent_content["content"]
    await client.aclose()
