"""Shared async helpers used across async test files."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient


def _bearer(token: str) -> dict[str, str]:
    """Helper: Bearer auth header dict."""
    return {"Authorization": f"Bearer {token}"}


async def async_create_task(
    ac: AsyncClient, token: str, task_data: dict
) -> dict[str, Any]:
    """Helper: create a task via async client, return response JSON."""
    resp = await ac.post("/admin/tasks", json=task_data, headers=_bearer(token))
    assert resp.status_code == 200, f"Failed to create task: {resp.text}"
    return resp.json()


async def async_create_theory(
    ac: AsyncClient, token: str, theory_data: dict
) -> dict[str, Any]:
    """Helper: create theory via async client, return response JSON."""
    resp = await ac.post("/admin/theory", json=theory_data, headers=_bearer(token))
    assert resp.status_code == 200, f"Failed to create theory: {resp.text}"
    return resp.json()
