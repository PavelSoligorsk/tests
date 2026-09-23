"""stdio MCP: пакетное создание, правка и удаление заданий админом.

Запуск: python -m mcp_admin
Env: ADMIN_API_BASE, и ADMIN_TOKEN либо ADMIN_USERNAME + ADMIN_PASSWORD.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_admin.client import AdminApiError, AdminTaskClient

mcp = FastMCP("admin-tasks")
_client: AdminTaskClient | None = None


def _api() -> AdminTaskClient:
    global _client
    if _client is None:
        _client = AdminTaskClient()
    return _client


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


async def _run(coro) -> str:
    try:
        return _dump(await coro)
    except AdminApiError as exc:
        return _dump({"error": exc.detail, "status": exc.status_code})


@mcp.tool()
async def tasks_meta() -> str:
    """Структура банка без текстов заданий.

    by_class: { класс: { номер_темы: количество } }
    by_topic_section: { тема: { раздел: количество } }
    """
    return await _run(_api().tasks_meta())


@mcp.tool()
async def list_tasks(topic: str, section: str) -> str:
    """Задания одного раздела (тема + раздел), с id и полным текстом."""
    return await _run(_api().list_by_topic_section(topic, section))


@mcp.tool()
async def list_tasks_by_class(task_class: str, topic_number: str) -> str:
    """Задания по классу и номеру темы, с id и полным текстом."""
    return await _run(_api().list_by_class(task_class, topic_number))


@mcp.tool()
async def get_task(task_id: int) -> str:
    """Одно задание по id."""
    return await _run(_api().get_task(task_id))


@mcp.tool()
async def upload_task_image(file_path: str = "", image_base64: str = "") -> str:
    """Загрузить скриншот задания в хранилище и получить URL.

    Передай file_path (png, который ты только что снял) или image_base64.
    В content вставляй markdown из ответа: ![](url).
    Если в тексте есть плейсхолдер {{image}}, create_tasks сам заменит его на эту картинку.
    """
    client = _api()
    if file_path:
        return await _run(client.upload_image_file(file_path))
    if image_base64:
        return await _run(client.upload_image(image_base64))
    return _dump({"error": "Нужен file_path или image_base64", "status": 400})


@mcp.tool()
async def create_tasks(tasks: list[dict]) -> str:
    """Пакетное создание. До 500 за запрос, большие списки режутся сами.

    Поля как в банке: task_class, topic_number, content, answer, is_open_answer,
    options (только для закрытых), difficulty 1..5, topic, section.
    У закрытого задания answer — номер варианта с 1 ("1", "2", …), не текст варианта.
    Картинка: сними скриншот, укажи image / image_path / screenshot (путь к png или base64)
    или несколько в images. URL вставится вместо {{image}} или в конец content как ![](url).
    """
    return await _run(_api().create_tasks(tasks))


@mcp.tool()
async def create_tasks_yaml(yaml_text: str) -> str:
    """Пакетное создание из YAML-списка.

    Пример элемента:
    task_class, topic_number, content (можно с $$...$$), options, answer,
    is_open_answer, difficulty, topic, section.
    answer закрытого задания — номер варианта с 1.
    Необязательно: image / screenshot — путь к png или base64; в content можно поставить {{image}}.
    """
    return await _run(_api().create_tasks_yaml(yaml_text))


@mcp.tool()
async def update_tasks(tasks: list[dict]) -> str:
    """Пакетное обновление. У каждого объекта обязателен id, остальные поля — что менять."""
    return await _run(_api().update_tasks(tasks))


@mcp.tool()
async def delete_tasks(ids: list[int]) -> str:
    """Пакетное удаление заданий по id."""
    return await _run(_api().delete_tasks(ids))


@mcp.tool()
async def apply_tasks(
    create: list[dict] | None = None,
    update: list[dict] | None = None,
    delete_ids: list[int] | None = None,
) -> str:
    """Один пакет: сначала create, потом update, потом delete_ids.

    Пустые списки можно не передавать. На первой ошибке следующие шаги не выполняются,
    уже записанные шаги остаются в базе.
    """
    return await _run(_api().apply(create=create, update=update, delete_ids=delete_ids))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
