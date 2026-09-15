"""Статические примеры GeoGebra для двухэтапного AI (few-shot по теме/разделу)."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "geogebra" / "examples"
INDEX_PATH = EXAMPLES_DIR / "index.yml"

# Явный маппинг title → slug папки/файла (кириллица).
TOPIC_SLUGS: dict[str, str] = {
    "Планиметрия": "planimetriya",
    "Стереометрия": "stereometriya",
    "Графики": "grafiki",
}
SECTION_SLUGS: dict[str, str] = {
    "Трапеция": "trapetsiya",
    "Треугольник": "treugolnik",
    "Квадрат": "kvadrat",
    "Окружность": "okruzhnost",
    "Пирамида": "piramida",
    "Цилиндр": "tsilindr",
    "Параллелепипед": "parallelepiped",
    "Квадратичная функция": "kvadratichnaya_funktsiya",
}


def _slugify(text: str) -> str:
    text = (text or "").strip().lower()
    if text in {k.lower(): v for k, v in {**TOPIC_SLUGS, **SECTION_SLUGS}.items()}:
        mapping = {k.lower(): v for k, v in {**TOPIC_SLUGS, **SECTION_SLUGS}.items()}
        return mapping[text]
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_only).strip("_")
    return slug or "unknown"


def topic_slug(topic: str) -> str:
    return TOPIC_SLUGS.get(topic, _slugify(topic))


def section_slug(section: str) -> str:
    return SECTION_SLUGS.get(section, _slugify(section))


@lru_cache(maxsize=1)
def list_catalog() -> dict[str, list[str]]:
    """topic → [section, ...] из index.yml."""
    if not INDEX_PATH.is_file():
        logger.warning("GeoGebra examples index missing: %s", INDEX_PATH)
        return {}
    raw = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8")) or {}
    topics = raw.get("topics") or {}
    out: dict[str, list[str]] = {}
    for topic, sections in topics.items():
        if isinstance(sections, list):
            out[str(topic)] = [str(s) for s in sections]
        else:
            out[str(topic)] = []
    return out


def catalog_text() -> str:
    """Компактный список topic/section для stage1 промпта."""
    lines: list[str] = []
    for topic, sections in list_catalog().items():
        if sections:
            lines.append(f"- {topic}: {', '.join(sections)}")
        else:
            lines.append(f"- {topic}")
    return "\n".join(lines) if lines else "(каталог пуст)"


def resolve_topic_section(topic: str, section: str) -> tuple[Optional[str], Optional[str]]:
    """Нормализовать имена к ключам каталога; fallback на первую секцию темы."""
    catalog = list_catalog()
    if not catalog:
        return None, None

    topic_key = None
    topic_l = (topic or "").strip().lower()
    for name in catalog:
        if name.lower() == topic_l:
            topic_key = name
            break
    if topic_key is None:
        for name in catalog:
            if topic_l and (topic_l in name.lower() or name.lower() in topic_l):
                topic_key = name
                break
    if topic_key is None:
        logger.info("Unknown GeoGebra example topic %r — empty examples", topic)
        return None, None

    sections = catalog[topic_key]
    section_key = None
    section_l = (section or "").strip().lower()
    for name in sections:
        if name.lower() == section_l:
            section_key = name
            break
    if section_key is None and section_l:
        for name in sections:
            if section_l in name.lower() or name.lower() in section_l:
                section_key = name
                break
    if section_key is None:
        section_key = sections[0] if sections else None
        logger.info(
            "Unknown section %r for topic %s — fallback %s",
            section, topic_key, section_key,
        )
    return topic_key, section_key


def _example_path(topic: str, section: str) -> Path:
    return EXAMPLES_DIR / topic_slug(topic) / f"{section_slug(section)}.yml"


def _format_examples(data: dict[str, Any]) -> str:
    """Few-shot как JSON с полем commands — без use/stack."""
    blocks: list[str] = []
    for i, ex in enumerate(data.get("examples") or [], start=1):
        title = ex.get("title") or f"Пример {i}"
        prompt = (ex.get("prompt") or "").strip()
        commands = ex.get("commands") or []
        if isinstance(commands, str):
            commands = [ln.strip() for ln in commands.splitlines() if ln.strip()]
        app = ex.get("app") or data.get("app") or "geometry"
        height = str(ex.get("height") or data.get("height") or "400")
        parts = [f"### Пример {i}: {title}"]
        if prompt:
            parts.append(prompt)
        if commands:
            payload = {"app": app, "height": height, "commands": list(commands)}
            parts.append("```geogebra\n" + json.dumps(payload, ensure_ascii=False) + "\n```")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def load_examples(topic: str, section: str) -> str:
    """Текст few-shot примеров для stage2. Пустая строка, если файла нет."""
    topic_key, section_key = resolve_topic_section(topic, section)
    if not topic_key or not section_key:
        return ""
    path = _example_path(topic_key, section_key)
    if not path.is_file():
        logger.warning("GeoGebra examples file missing: %s", path)
        return ""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _format_examples(data)


def clear_catalog_cache() -> None:
    list_catalog.cache_clear()


def parse_figure_route(text: str) -> Optional[dict[str, Any]]:
    """
    Извлечь решение stage1: {"needs_figure": bool, "topic"?: "...", "section"?: "..."}.
    Если это обычный текст ответа (не роутинг) — вернуть None.
    """
    if not text or not text.strip():
        return None
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        match = re.search(r"\{[^{}]*\"needs_figure\"[^{}]*\}", raw, re.DOTALL)
        if match:
            candidate = match.group(0)
        elif raw.startswith("{") and raw.endswith("}"):
            candidate = raw
    if not candidate:
        return None
    # Роутинг — почти весь ответ это JSON (с забором или без), а не длинное решение.
    stripped_no_fence = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
    if stripped_no_fence and len(stripped_no_fence) > 80 and '"needs_figure"' not in stripped_no_fence:
        # В тексте есть и JSON, и длинный ответ — считаем финальным текстом, не роутингом.
        return None
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(data, dict) or "needs_figure" not in data:
        return None
    needs = data.get("needs_figure")
    if needs is True or needs is False:
        pass
    elif isinstance(needs, str) and needs.strip().lower() in {"true", "false"}:
        needs = needs.strip().lower() == "true"
    else:
        return None
    topic = str(data.get("topic") or "").strip()
    section = str(data.get("section") or "").strip()
    return {"needs_figure": bool(needs), "topic": topic, "section": section}
