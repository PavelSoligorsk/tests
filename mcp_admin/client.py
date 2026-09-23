"""HTTP-клиент к админским пакетным эндпоинтам заданий."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

BATCH_LIMIT = 500


class AdminApiError(Exception):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


_IMAGE_KEYS = ("image", "images", "image_path", "image_base64", "screenshot", "screenshots")


def image_markdown(url: str) -> str:
    return f"![]({url})"


def insert_image_urls(content: str, urls: list[str]) -> str:
    """Подставляет {{image}} по порядку. Лишние URL дописывает в конец content."""
    text = content or ""
    for url in urls:
        snippet = image_markdown(url)
        if "{{image}}" in text:
            text = text.replace("{{image}}", snippet, 1)
        else:
            text = text.rstrip() + "\n\n" + snippet
    return text


def _as_image_sources(task: dict) -> list[str]:
    sources: list[str] = []
    for key in _IMAGE_KEYS:
        value = task.get(key)
        if not value:
            continue
        if isinstance(value, str):
            sources.append(value)
        elif isinstance(value, list):
            sources.extend(str(item) for item in value if item)
    return sources


def _file_to_base64(source: str) -> str:
    path = Path(source)
    if path.is_file():
        return base64.b64encode(path.read_bytes()).decode("ascii")
    compact = "".join(source.split())
    if len(compact) > 80 and all(c.isalnum() or c in "+/=" for c in compact[:80]):
        return source
    raise AdminApiError(400, f"Файл скриншота не найден: {source}")


class AdminTaskClient:
    """Вызывает /admin/* от имени администратора.

    Токен: ADMIN_TOKEN, иначе логин ADMIN_USERNAME + ADMIN_PASSWORD.
    База: ADMIN_API_BASE (по умолчанию http://127.0.0.1:8000).
    """

    def __init__(self, http: httpx.AsyncClient | None = None):
        self.base = os.getenv("ADMIN_API_BASE", "http://127.0.0.1:8000").rstrip("/")
        self._token = os.getenv("ADMIN_TOKEN") or None
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=120.0)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _login(self) -> None:
        username = os.getenv("ADMIN_USERNAME")
        password = os.getenv("ADMIN_PASSWORD")
        if not username or not password:
            raise AdminApiError(
                401,
                "Задайте ADMIN_TOKEN или ADMIN_USERNAME и ADMIN_PASSWORD",
            )
        resp = await self._http.post(
            f"{self.base}/login",
            data={"username": username, "password": password},
        )
        if resp.status_code != 200:
            raise AdminApiError(resp.status_code, _detail(resp))
        body = resp.json()
        if body.get("role") != "admin":
            raise AdminApiError(403, f"Нужна роль admin, получена {body.get('role')}")
        self._token = body["access_token"]

    async def _headers(self) -> dict[str, str]:
        if not self._token:
            await self._login()
        return {"Authorization": f"Bearer {self._token}"}

    async def request(self, method: str, path: str, json: Any = None) -> Any:
        headers = await self._headers()
        resp = await self._http.request(method, f"{self.base}{path}", headers=headers, json=json)
        if resp.status_code == 401 and os.getenv("ADMIN_TOKEN") is None:
            self._token = None
            headers = await self._headers()
            resp = await self._http.request(method, f"{self.base}{path}", headers=headers, json=json)
        if resp.status_code >= 400:
            raise AdminApiError(resp.status_code, _detail(resp))
        if not resp.content:
            return None
        return resp.json()

    async def tasks_meta(self) -> dict:
        by_class = await self.request("GET", "/admin/tasks-meta")
        by_topic = await self.request("GET", "/admin/tasks-meta-by-topic-section")
        return {"by_class": by_class, "by_topic_section": by_topic}

    async def list_by_topic_section(self, topic: str, section: str) -> list:
        topic_q = quote(topic, safe="")
        section_q = quote(section, safe="")
        return await self.request(
            "GET",
            f"/admin/tasks/by-topic/{topic_q}/section/{section_q}",
        )

    async def list_by_class(self, task_class: str, topic_number: str) -> list:
        headers = await self._headers()
        resp = await self._http.get(
            f"{self.base}/admin/tasks/by-class/",
            headers=headers,
            params={"task_class": task_class, "topic_number": topic_number},
        )
        if resp.status_code >= 400:
            raise AdminApiError(resp.status_code, _detail(resp))
        return resp.json()

    async def get_task(self, task_id: int) -> dict:
        return await self.request("GET", f"/admin/tasks/{task_id}")

    async def upload_image(self, image_base64: str) -> dict:
        data = await self.request("POST", "/admin/upload-image", {"image": image_base64})
        url = data["url"]
        return {"url": url, "markdown": image_markdown(url)}

    async def upload_image_file(self, file_path: str) -> dict:
        return await self.upload_image(_file_to_base64(file_path))

    async def _with_images(self, tasks: list[dict]) -> list[dict]:
        prepared: list[dict] = []
        for raw in tasks:
            task = dict(raw)
            sources = _as_image_sources(task)
            for key in _IMAGE_KEYS:
                task.pop(key, None)
            if task.get("answer") is not None:
                task["answer"] = str(task["answer"])
            if sources:
                urls = []
                for source in sources:
                    uploaded = await self.upload_image(_file_to_base64(source))
                    urls.append(uploaded["url"])
                task["content"] = insert_image_urls(str(task.get("content") or ""), urls)
            prepared.append(task)
        return prepared

    async def create_tasks(self, tasks: list[dict]) -> dict:
        tasks = await self._with_images(tasks)
        created: list = []
        for chunk in _chunks(tasks, BATCH_LIMIT):
            data = await self.request("POST", "/admin/tasks/batch", {"tasks": chunk})
            created.extend(data.get("created") or [])
        return {"created": created, "total": len(created)}

    async def update_tasks(self, tasks: list[dict]) -> dict:
        updated: list = []
        not_found: list = []
        for chunk in _chunks(tasks, BATCH_LIMIT):
            data = await self.request("PUT", "/admin/tasks/batch", {"tasks": chunk})
            updated.extend(data.get("updated") or [])
            not_found.extend(data.get("not_found") or [])
        return {
            "updated": updated,
            "not_found": not_found,
            "total_updated": len(updated),
        }

    async def delete_tasks(self, ids: list[int]) -> dict:
        deleted: list = []
        not_found: list = []
        for chunk in _chunks(ids, BATCH_LIMIT):
            data = await self.request("DELETE", "/admin/tasks/batch", {"ids": chunk})
            deleted.extend(data.get("deleted") or [])
            not_found.extend(data.get("not_found") or [])
        return {
            "deleted": deleted,
            "not_found": not_found,
            "total_deleted": len(deleted),
        }

    async def apply(
        self,
        create: list[dict] | None = None,
        update: list[dict] | None = None,
        delete_ids: list[int] | None = None,
    ) -> dict:
        """Создание, затем обновление, затем удаление. Остановка на первой ошибке."""
        result: dict[str, Any] = {}
        if create:
            result["create"] = await self.create_tasks(create)
        if update:
            result["update"] = await self.update_tasks(update)
        if delete_ids:
            result["delete"] = await self.delete_tasks(delete_ids)
        if not result:
            raise AdminApiError(400, "Пустой пакет: передайте create, update или delete_ids")
        return result

    async def create_tasks_yaml(self, yaml_text: str) -> dict:
        """YAML-список заданий в формате банка (answer закрытых — номер варианта, с 1)."""
        loaded = yaml.safe_load(yaml_text)
        if isinstance(loaded, dict) and "tasks" in loaded:
            loaded = loaded["tasks"]
        if isinstance(loaded, dict):
            loaded = [loaded]
        if not isinstance(loaded, list) or not loaded:
            raise AdminApiError(400, "YAML должен быть списком заданий")
        return await self.create_tasks(loaded)


def _detail(resp: httpx.Response) -> Any:
    try:
        body = resp.json()
    except Exception:
        return resp.text
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return body
