"""Сигнал «доска сохранилась». В памяти этого процесса, без опроса базы."""
from __future__ import annotations

import asyncio
import json
from typing import Any

PING_SECONDS = 15


class BoardEvents:
    def __init__(self) -> None:
        self._topics: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, board_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._topics.setdefault(board_id, set()).add(queue)
        return queue

    def unsubscribe(self, board_id: str, queue: asyncio.Queue) -> None:
        listeners = self._topics.get(board_id)
        if not listeners:
            return
        listeners.discard(queue)
        if not listeners:
            self._topics.pop(board_id, None)

    def publish(self, board_id: str, payload: dict[str, Any]) -> None:
        listeners = self._topics.get(board_id)
        if not listeners:
            return
        for queue in list(listeners):
            self._put_latest(queue, payload)

    @staticmethod
    def _put_latest(queue: asyncio.Queue, payload: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


board_events = BoardEvents()


def encode_sse(event: str, data: dict[str, Any]) -> str:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n"


async def iter_sse(queue: asyncio.Queue, snapshot: dict[str, Any]):
    board_id = snapshot["id"]
    try:
        yield encode_sse("update", snapshot)
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), PING_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            event = str(payload.get("event") or "update")
            data = {key: value for key, value in payload.items() if key != "event"}
            yield encode_sse(event, data)
            if event == "delete":
                break
    finally:
        board_events.unsubscribe(board_id, queue)
