#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Скрипт для классификации учебных заданий с помощью DeepSeek API.
ЖЁСТКАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ ФАЗ:
Фаза 1: Оценка сложности ВСЕХ заданий → ждём → Фаза 2
Фаза 2: Решение ВСЕХ заданий → ждём → Фаза 3  
Фаза 3: Классификация ВСЕХ заданий → ждём → Сохранение
"""

import os
import sys
import json
import re
import time
import asyncio
import csv
import logging
from typing import Optional, List, Dict, Any
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# ----------------------------------------------------------------------
# Настройки
# ----------------------------------------------------------------------
DEFAULT_MODEL = "deepseek-v4-flash"
API_URL = "https://api.deepseek.com/v1/chat/completions"
INPUT_FILE = "tasks.json"
OUTPUT_FILE = "classification_results.json"

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Конфигурация токен-бюджетов
# ----------------------------------------------------------------------
class ClassifyConfig:
    # Размеры батчей для решения в зависимости от сложности
    SOLVE_BATCH_SIZES: dict[int, int] = {1: 10, 2: 5, 3: 3, 4: 2, 5: 1}
    
    # Фаза 1: Оценка сложности
    ESTIMATE_BATCH_SIZE = 15  # По сколько заданий отправлять в одном запросе оценки
    ESTIMATE_TOKENS_PER_TASK: int = 500
    ESTIMATE_MIN_TOKENS: int = 8100
    ESTIMATE_MAX_CONCURRENT = 10  # Семафор для оценки сложности
    
    # Фаза 2: Решение
    SOLVE_TOKENS_PER_TASK: dict[int, int] = {
        1: 300, 2: 600, 3: 1000, 4: 1500, 5: 2500,
    }
    SOLVE_MIN_TOKENS: int = 4096
    SOLVE_MAX_TOKENS: int = 60000
    SOLVE_MAX_CONCURRENT = 10  # Семафор для решения
    
    # Фаза 3: Классификация
    CLASSIFY_TOKENS_PER_TASK: int = 1024
    CLASSIFY_MIN_TOKENS: int = 1024
    CLASSIFY_MAX_CONCURRENT = 10  # Семафор для классификации

# ----------------------------------------------------------------------
# Модель задания
# ----------------------------------------------------------------------
class Task:
    def __init__(
        self, 
        id: int, 
        content: str, 
        answer: str = "", 
        options: List[str] = None,
        difficulty: int = 0,
        task_class: int = 0,
        topic_number: int = 0,
        is_open_answer: bool = None
    ):
        self.id = id
        self.content = content.strip()
        self.answer = answer.strip() if answer else ""
        self.options = options or []
        
        # Определяем тип задания
        if is_open_answer is None:
            self.is_open_answer = not bool(self.options)
        else:
            self.is_open_answer = is_open_answer
            
        self.difficulty = difficulty or 1
        self.task_class = task_class
        self.topic_number = topic_number
        self.topic = None
        self.section = None

# ----------------------------------------------------------------------
# AI Сервис (с защитой от зависаний и Rate Limiting)
# ----------------------------------------------------------------------
class AIService:
    def __init__(self, api_key: str = None, model: str = DEFAULT_MODEL, max_concurrent: int = 30):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("API key not found. Set DEEPSEEK_API_KEY environment variable.")
        self.model = model
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        # Глобальный семафор — защита от 429 Too Many Requests
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def _get_session(self) -> aiohttp.ClientSession:
        # Double-checked locking для безопасного создания сессии
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    # Увеличиваем таймаут для долгих запросов
                    timeout = aiohttp.ClientTimeout(total=180, connect=30)
                    self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        # Ограничиваем количество одновременных запросов через семафор
        async with self._semaphore:
            session = await self._get_session()
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            
            # Механизм повторных попыток с экспоненциальной задержкой
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with session.post(API_URL, headers=headers, json=payload) as resp:
                        if resp.status == 429:
                            retry_after = int(resp.headers.get("Retry-After", 2 ** attempt + 2))
                            logger.warning(f"Rate limit 429. Waiting {retry_after}s. Retry {attempt + 1}/{max_retries}...")
                            await asyncio.sleep(retry_after)
                            continue
                            
                        resp.raise_for_status()
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"].strip()
                        
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"API error: {e}. Retry {attempt + 1}/{max_retries}...")
                    if attempt == max_retries - 1:
                        logger.error(f"API call failed after {max_retries} attempts: {e}")
                        raise
                    await asyncio.sleep(2 ** attempt)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

# ----------------------------------------------------------------------
# Парсер заданий
# ----------------------------------------------------------------------
class TaskParser:
    @staticmethod
    def parse_tsv_line(line: str) -> Optional[Task]:
        """Парсит строку в формате: problem \\t options \\t answer"""
        parts = line.strip().split('\t')
        if len(parts) < 2:
            return None
            
        problem = parts[0].strip()
        options_raw = parts[1].strip() if len(parts) > 1 else "[]"
        answer = parts[2].strip() if len(parts) > 2 else ""
        
        options = TaskParser._parse_options(options_raw)
        answer = TaskParser._normalize_answer(answer)
        
        return Task(
            id=0,
            content=problem,
            answer=answer,
            options=options
        )
    
    @staticmethod
    def _parse_options(raw: str) -> List[str]:
        if not raw or raw in ["[]", "null", ""]:
            return []
        try:
            options = json.loads(raw)
            if isinstance(options, list):
                return [str(opt).strip('"\'') for opt in options]
        except json.JSONDecodeError:
            pass
        options = re.findall(r'"([^"]*)"', raw)
        return options if options else []
    
    @staticmethod
    def _normalize_answer(answer: str) -> str:
        if not answer or answer in ["null", "[]", ""]:
            return ""
        return answer.strip('"\'')

    @staticmethod
    def load_tasks_from_file(filepath: str) -> List[Task]:
        if filepath.endswith('.json'):
            return TaskParser._load_from_json(filepath)
        return TaskParser._load_from_tsv(filepath)

    @staticmethod
    def _load_from_json(filepath: str) -> List[Task]:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        tasks = []
        for i, item in enumerate(data, 1):
            task = Task(
                id=item.get('id', i),
                content=item.get('problem', ''),
                answer=item.get('answer', ''),
                options=item.get('options', []),
                is_open_answer=item.get('is_open', None)
            )
            tasks.append(task)
        return tasks
    
# ----------------------------------------------------------------------
# Классификатор (ПЕРЕПИСАН под жёсткую последовательность фаз)
# ----------------------------------------------------------------------
class TaskClassifier:
    def __init__(self, api_key: str = None):
        self.config = ClassifyConfig()
        self.ai = AIService(api_key=api_key)
        
    @staticmethod
    def _solve_tokens_for(tasks: list) -> int:
        """Расчёт токенов для батча решения на основе сложности."""
        total = 0
        for t in tasks:
            d = t.difficulty if t.difficulty in ClassifyConfig.SOLVE_TOKENS_PER_TASK else 1
            total += ClassifyConfig.SOLVE_TOKENS_PER_TASK[d]
        return max(ClassifyConfig.SOLVE_MIN_TOKENS, min(total, ClassifyConfig.SOLVE_MAX_TOKENS))

    # =========================================================================
    # ФАЗА 1: ОЦЕНКА СЛОЖНОСТИ (отправили ВСЕ батчи → ждём ВСЕ → идём дальше)
    # =========================================================================
    async def phase1_estimate_difficulty(self, tasks: List[Task]) -> Dict[int, int]:
        """
        ФАЗА 1: Оценка сложности всех заданий.
        Разбиваем на батчи, отправляем ВСЕ параллельно, ждём ВСЕ.
        """
        if not tasks:
            return {}
        
        print(f"\n{'='*60}")
        print(f"ФАЗА 1: ОЦЕНКА СЛОЖНОСТИ")
        print(f"Отправка {len(tasks)} заданий батчами по {self.config.ESTIMATE_BATCH_SIZE}...")
        
        # Создаём семафор для этой фазы
        sem = asyncio.Semaphore(self.config.ESTIMATE_MAX_CONCURRENT)
        
        async def estimate_batch(batch: List[Task]) -> Dict[int, int]:
            """Обработка одного батча оценки сложности."""
            async with sem:
                task_blocks = []
                for i, task in enumerate(batch, 1):
                    qtype = "открытый" if task.is_open_answer else "закрытый"
                    block = (
                        f"### Задание {i} (id={task.id}, тип={qtype})\n"
                        f"{task.content[:400]}\n"
                    )
                    task_blocks.append(block)
                
                prompt = (
                    "Оцени сложность КАЖДОГО задания по шкале 1-5, где:\n"
                    "1 — устный счёт / очевидное\n"
                    "2 — базовое, в 1-2 действия\n"
                    "3 — среднее, требует нескольких шагов\n"
                    "4 — сложное, требует хорошего понимания темы\n"
                    "5 — олимпиадное / требует много шагов и нестандартного подхода\n\n"
                    "Верни ТОЛЬКО JSON-массив:\n"
                    '[{"task_id": <id>, "difficulty": <1-5>}, ...]\n\n'
                    + "\n".join(task_blocks)
                )
                
                try:
                    response = await self.ai._chat_completion(
                        system_prompt="Ты оцениваешь сложность математических заданий. Верни ТОЛЬКО валидный JSON-массив.",
                        user_prompt=prompt,
                        temperature=0.0,
                        max_tokens=max(self.config.ESTIMATE_MIN_TOKENS, 
                                     len(batch) * self.config.ESTIMATE_TOKENS_PER_TASK),
                        json_mode=True
                    )
                    
                    result = {}
                    m = re.search(r'\[.*\]', response, re.DOTALL)
                    if m:
                        items = json.loads(m.group())
                        for item in items:
                            tid = item.get("task_id")
                            d = item.get("difficulty")
                            if tid is not None and isinstance(d, int) and 1 <= d <= 5:
                                result[int(tid)] = d
                    return result
                except Exception as e:
                    logger.error(f"Ошибка оценки сложности батча: {e}")
                    return {}
        
        # Разбиваем на батчи
        batch_size = self.config.ESTIMATE_BATCH_SIZE
        batches = [tasks[i:i + batch_size] for i in range(0, len(tasks), batch_size)]
        
        # 🔥 КЛЮЧЕВОЙ МОМЕНТ: asyncio.gather() — ждём ВСЕ батчи!
        print(f"  📤 Запуск {len(batches)} батчей параллельно...")
        batch_results = await asyncio.gather(
            *[estimate_batch(batch) for batch in batches],
            return_exceptions=True  # Не падаем если один батч с ошибкой
        )
        
        # Собираем все результаты
        all_results = {}
        failed_batches = 0
        for i, res in enumerate(batch_results):
            if isinstance(res, Exception):
                logger.error(f"Батч {i+1} упал с ошибкой: {res}")
                failed_batches += 1
            elif isinstance(res, dict):
                all_results.update(res)
        
        print(f"  ✅ Фаза 1 завершена: {len(all_results)}/{len(tasks)} оценено успешно")
        if failed_batches:
            print(f"  ⚠️  {failed_batches} батчей не обработано из-за ошибок")
        
        return all_results

    # =========================================================================
    # ФАЗА 2: РЕШЕНИЕ (отправили ВСЕ батчи → ждём ВСЕ → идём дальше)
    # =========================================================================
    async def phase2_solve_all(self, tasks: List[Task]) -> Dict[int, str]:
        """
        ФАЗА 2: Решение всех заданий.
        Группируем по сложности, формируем ВСЕ батчи,
        отправляем ВСЕ параллельно, ждём ВСЕ.
        """
        if not tasks:
            return {}
        
        print(f"\n{'='*60}")
        print(f"ФАЗА 2: РЕШЕНИЕ ЗАДАНИЙ")
        
        # Группируем по сложности
        by_difficulty = {d: [] for d in range(1, 6)}
        for task in tasks:
            d = task.difficulty if task.difficulty in range(1, 6) else 1
            by_difficulty[d].append(task)
        
        # Создаём семафор для фазы решения
        sem = asyncio.Semaphore(self.config.SOLVE_MAX_CONCURRENT)
        
        async def solve_batch(batch: List[Task], kind: str) -> Dict[int, str]:
            """Решение одного батча (закрытого или открытого)."""
            async with sem:
                if kind == "closed":
                    return await self._solve_closed_batch(batch)
                else:
                    return await self._solve_open_batch(batch)
        
        # Формируем ВСЕ корутины для ВСЕХ батчей
        all_coroutines = []
        batch_info = []  # Для логирования
        
        for diff_level in range(1, 6):
            diff_tasks = by_difficulty[diff_level]
            if not diff_tasks:
                continue
            
            batch_size = self.config.SOLVE_BATCH_SIZES[diff_level]
            
            for i in range(0, len(diff_tasks), batch_size):
                batch = diff_tasks[i:i + batch_size]
                
                # Разделяем на открытые и закрытые в рамках батча
                closed = [t for t in batch if not t.is_open_answer]
                open_tasks = [t for t in batch if t.is_open_answer]
                
                if closed:
                    all_coroutines.append(solve_batch(closed, "closed"))
                    batch_info.append(f"сложность {diff_level}, закрытые x{len(closed)}")
                if open_tasks:
                    all_coroutines.append(solve_batch(open_tasks, "open"))
                    batch_info.append(f"сложность {diff_level}, открытые x{len(open_tasks)}")
        
        print(f"  📤 Запуск {len(all_coroutines)} батчей решения параллельно...")
        for info in batch_info:
            print(f"     • {info}")
        
        # 🔥 КЛЮЧЕВОЙ МОМЕНТ: asyncio.gather() — ждём ВСЕ батчи решения!
        batch_results = await asyncio.gather(
            *all_coroutines,
            return_exceptions=True
        )
        
        # Собираем все ответы
        all_answers = {}
        failed_batches = 0
        for i, res in enumerate(batch_results):
            if isinstance(res, Exception):
                logger.error(f"Батч решения {i+1} упал: {res}")
                failed_batches += 1
            elif isinstance(res, dict):
                all_answers.update(res)
        
        print(f"  ✅ Фаза 2 завершена: {len(all_answers)}/{len(tasks)} решено")
        if failed_batches:
            print(f"  ⚠️  {failed_batches} батчей не решено из-за ошибок")
        
        return all_answers

    # =========================================================================
    # ФАЗА 3: КЛАССИФИКАЦИЯ (отправили ВСЕ → ждём ВСЕ → идём дальше)
    # =========================================================================
    async def phase3_classify_all(self, tasks: List[Task]) -> Dict[int, Dict[str, str]]:
        """
        ФАЗА 3: Классификация всех заданий.
        Отправляем все задания параллельно, ждём ВСЕ.
        """
        if not tasks:
            return {}
        
        print(f"\n{'='*60}")
        print(f"ФАЗА 3: КЛАССИФИКАЦИЯ")
        print(f"  📤 Запуск классификации {len(tasks)} заданий...")
        
        sem = asyncio.Semaphore(self.config.CLASSIFY_MAX_CONCURRENT)
        
        async def classify_one(task: Task) -> tuple:
            """Классификация одного задания. Возвращает (task_id, result)."""
            async with sem:
                try:
                    result = await self._classify_task(task)
                    return (task.id, result)
                except Exception as e:
                    logger.error(f"Ошибка классификации #{task.id}: {e}")
                    return (task.id, None)
        
        # 🔥 КЛЮЧЕВОЙ МОМЕНТ: asyncio.gather() — ждём ВСЕ классификации!
        all_results = await asyncio.gather(
            *[classify_one(task) for task in tasks],
            return_exceptions=True
        )
        
        classifications = {}
        failed = 0
        for res in all_results:
            if isinstance(res, Exception):
                failed += 1
            elif isinstance(res, tuple) and len(res) == 2:
                tid, data = res
                if data:
                    classifications[tid] = data
                else:
                    failed += 1
        
        print(f"  ✅ Фаза 3 завершена: {len(classifications)}/{len(tasks)} классифицировано")
        if failed:
            print(f"  ⚠️  {failed} заданий не классифицировано")
        
        return classifications

    # =========================================================================
    # ГЛАВНЫЙ МЕТОД: жёсткая последовательность фаз
    # =========================================================================
    async def classify_tasks(self, tasks: List[Task]) -> List[Dict[str, Any]]:
        """
        Основной метод классификации.
        СТРОГАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ:
        Фаза 1 → ждём ВСЕ → Фаза 2 → ждём ВСЕ → Фаза 3 → ждём ВСЕ → Результат
        """
        
        print(f"\n{'='*80}")
        print(f"🤖 КЛАССИФИКАЦИЯ УЧЕБНЫХ ЗАДАНИЙ (жёсткая последовательность фаз)")
        print(f"{'='*80}")
        print(f"📝 Модель: {DEFAULT_MODEL}")
        print(f"📊 Всего заданий: {len(tasks)}")
        print(f"📋 Открытых: {sum(1 for t in tasks if t.is_open_answer)}")
        print(f"📋 Закрытых: {sum(1 for t in tasks if not t.is_open_answer)}")
        
        # ============ ФАЗА 1: Оценка сложности ============
        difficulty_map = await self.phase1_estimate_difficulty(tasks)
        
        # Применяем результаты Фазы 1
        for task in tasks:
            if task.id in difficulty_map:
                task.difficulty = difficulty_map[task.id]
            else:
                task.difficulty = 1
        
        # Статистика после Фазы 1
        diff_dist = {}
        for t in tasks:
            d = t.difficulty
            diff_dist[d] = diff_dist.get(d, 0) + 1
        print(f"\n  📊 Распределение сложности после Фазы 1:")
        for d in sorted(diff_dist):
            print(f"     Уровень {d}: {diff_dist[d]} заданий")
        
        # ============ ФАЗА 2: Решение ============
        solutions = await self.phase2_solve_all(tasks)
        
        # Сравниваем ответы
        correct_count = 0
        for task in tasks:
            ai_answer = solutions.get(task.id, "")
            is_correct = self._compare_answer(ai_answer, task.answer)
            if is_correct:
                correct_count += 1
            status = "✅" if is_correct else "❌"
            print(f"  #{task.id}: {task.content} options = {task.options}»")
            print(f"  {status} #{task.id}: AI=«{ai_answer}» | Эталон=«{task.answer}»")
        
        print(f"\n  📊 Правильных ответов: {correct_count}/{len(tasks)} ({100*correct_count/len(tasks):.1f}%)")
        
        # ============ ФАЗА 3: Классификация ============
        classifications = await self.phase3_classify_all(tasks)
        
        # ============ ФОРМИРОВАНИЕ РЕЗУЛЬТАТОВ ============
        results = []
        for task in tasks:
            classification = classifications.get(task.id, {})
            result = {
                "id": task.id,
                "problem": task.content[:200] + "..." if len(task.content) > 200 else task.content,
                "type": "открытый" if task.is_open_answer else "закрытый",
                "difficulty": self._difficulty_label(task.difficulty),
                "difficulty_score": task.difficulty,
                "ai_solution": solutions.get(task.id, ""),
                "correct_answer": task.answer,
                "is_correct": self._compare_answer(solutions.get(task.id, ""), task.answer),
                "topic": classification.get("topic", "Не определена"),
                "section": classification.get("section", ""),
                "classification": f"{classification.get('topic', 'Не определена')}, {classification.get('section', '')}"
            }
            results.append(result)
        
        return results

    # =========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ (без изменений)
    # =========================================================================
    async def _solve_closed_batch(self, tasks: List[Task]) -> Dict[int, str]:
        if not tasks:
            return {}
        
        task_blocks = []
        for i, task in enumerate(tasks, 1):
            opts = "\n".join(f"{j+1}) {opt}" for j, opt in enumerate(task.options))
            block = (
                f"### Задание {i} (id={task.id})\n"
                f"Условие:\n{task.content[:800]}\n"
                f"Варианты ответа:\n{opts}\n"
            )
            task_blocks.append(block)
        
        prompt = (
            "Реши КАЖДОЕ задание и выбери правильный вариант ответа.\n"
            "answer — ТОЛЬКО НОМЕР правильного варианта (1, 2, 3, 4 или 5).\n"
            "Если правильных вариантов несколько, укажи номера через запятую (например: \"1,3\").\n"
            "Формат ответа СТРОГО:\n"
            '[{"task_id": <id>, "answer": "<номер или номера>"}, ...]\n\n'
            + "\n".join(task_blocks)
        )
        
        try:
            response = await self.ai._chat_completion(
                system_prompt="Ты — математик. Реши задания и верни СТРОГО JSON-массив. answer — ТОЛЬКО НОМЕР(А) правильного варианта (1-5), без текста варианта.",
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=self._solve_tokens_for(tasks),
                json_mode=True
            )
            return self._extract_answers(response)
        except Exception as e:
            logger.error(f"Closed batch solve failed: {e}")
            return {}

    async def _solve_open_batch(self, tasks: List[Task]) -> Dict[int, str]:
        if not tasks:
            return {}
        
        task_blocks = []
        for i, task in enumerate(tasks, 1):
            block = (
                f"### Задание {i} (id={task.id})\n"
                f"Условие:\n{task.content[:800]}\n"
            )
            task_blocks.append(block)
        
        prompt = (
            "Реши КАЖДОЕ задание.\n"
            "answer — ТОЛЬКО число (без пробелов, без знаков валют, без единиц измерения, без префиксов).\n"
            "Для дробей используй десятичную запись (например: 0.5 вместо 1/2).\n"
            "Если ответ — комбинация букв и цифр (например: А4Б2В5), запиши точно так же.\n"
            "Если корней нет, напиши \"-\".\n"
            "Формат ответа СТРОГО:\n"
            '[{"task_id": <id>, "answer": "<ответ>"}, ...]\n\n'
            + "\n".join(task_blocks)
        )
        
        try:
            response = await self.ai._chat_completion(
                system_prompt="Ты — математик. Реши задания и верни СТРОГО JSON-массив. answer — только число/выражение без единиц измерения и префиксов.",
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=self._solve_tokens_for(tasks),
                json_mode=True
            )
            return self._extract_answers(response)
        except Exception as e:
            logger.error(f"Open batch solve failed: {e}")
            return {}

    @staticmethod
    def _extract_answers(response: str) -> Dict[int, str]:
        result = {}
        m = re.search(r'\[.*\]', response, re.DOTALL)
        if m:
            try:
                items = json.loads(m.group())
                for item in items:
                    tid = item.get("task_id")
                    ans = item.get("answer")
                    if tid is not None and ans is not None:
                        result[int(tid)] = str(ans).strip()
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to parse answers JSON: {e}")
        return result

    async def _classify_task(self, task: Task) -> Optional[Dict[str, str]]:
        task_type = "open answer" if task.is_open_answer else "multiple choice"
        
        prompt = f"""Classify this math task by topic and section.
Output ONLY a JSON object: {{"topic": "...", "section": "..."}}

=== TASK INFO ===
Type: {task_type}
Difficulty: {task.difficulty}/5
Problem:
{task.content[:600]}

=== CLASSIFICATION GUIDELINES ===
topic - broad category (e.g., "Алгебра", "Геометрия", "Тригонометрия", "Логарифмы", "Прогрессии", "Функции", "Неравенства")
section - specific subtopic (e.g., "Квадратные уравнения", "Площади фигур", "Тригонометрические уравнения", "Стереометрия")

Choose the most specific topic and section that matches this problem."""

        try:
            response = await self.ai._chat_completion(
                system_prompt="You are a strict classifier of math problems. Output valid JSON only, no markdown.",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=self.config.CLASSIFY_TOKENS_PER_TASK,
                json_mode=True
            )
            
            m = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if m:
                data = json.loads(m.group())
                if data.get("topic"):
                    return data
        except Exception as e:
            logger.error(f"Classification failed for task {task.id}: {e}")
        
        return None

    @staticmethod
    def _compare_answer(ai_answer: str, correct_answer: str) -> bool:
        if not ai_answer or not correct_answer:
            return False
        
        def normalize(s: str) -> str:
            s = s.strip().lower()
            s = s.replace(",", ".").replace(" ", "")
            s = re.sub(r'^(x=|y=|ответ:?\s*|answer:?\s*)', '', s)
            s = s.rstrip('.')
            return s
        
        a = normalize(ai_answer)
        b = normalize(correct_answer)
        
        if a == b:
            return True
        
        try:
            fa = float(a)
            fb = float(b)
            return abs(fa - fb) < 1e-9
        except (ValueError, TypeError):
            pass
        
        a_set = set(re.findall(r'-?\d+', a))
        b_set = set(re.findall(r'-?\d+', b))
        if a_set and b_set and a_set == b_set:
            return True
        
        return False

    @staticmethod
    def _difficulty_label(level: int) -> str:
        labels = {1: "лёгкая", 2: "лёгкая", 3: "средняя", 4: "сложная", 5: "сложная"}
        return labels.get(level, "средняя")

# ----------------------------------------------------------------------
# Основная функция
# ----------------------------------------------------------------------
async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Классификация учебных заданий через DeepSeek API")
    parser.add_argument("input", nargs="?", default=INPUT_FILE, help="Входной файл с заданиями (TSV формат)")
    parser.add_argument("--output", "-o", default=OUTPUT_FILE, help="Выходной JSON файл")
    parser.add_argument("--api-key", help="API ключ DeepSeek")
    
    args = parser.parse_args()
    
    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ Ошибка: API-ключ не найден.")
        print("   Установите переменную DEEPSEEK_API_KEY или используйте --api-key")
        sys.exit(1)
    
    if not os.path.exists(args.input):
        print(f"❌ Файл не найден: {args.input}")
        sys.exit(1)
    
    tasks = TaskParser.load_tasks_from_file(args.input)
    
    if not tasks:
        print("❌ Не удалось загрузить задания")
        sys.exit(1)
    
    classifier = TaskClassifier(api_key=api_key)
    
    try:
        start_time = time.time()
        
        # 🔥 Главный вызов — внутри жёсткая последовательность фаз
        results = await classifier.classify_tasks(tasks)
        
        elapsed = time.time() - start_time
        
        # Итоговая статистика
        print(f"\n{'='*80}")
        print(f"📊 ИТОГОВАЯ СТАТИСТИКА")
        print(f"{'='*80}")
        print(f"✅ Всего обработано: {len(results)}")
        print(f"⏱️ Общее время: {elapsed:.2f}с")
        print(f"⏱️ Среднее на задачу: {elapsed/len(results):.2f}с")
        
        # Распределение по сложности
        diff_stats = {}
        for r in results:
            d = r['difficulty']
            diff_stats[d] = diff_stats.get(d, 0) + 1
        print(f"\n📊 Сложность:")
        for d, c in sorted(diff_stats.items()):
            print(f"   {d}: {c} заданий")
        
        # Правильные ответы
        correct = sum(1 for r in results if r['is_correct'])
        print(f"\n🎯 Правильных ответов AI: {correct}/{len(results)} ({100*correct/len(results):.1f}%)")
        
        # Классификация
        topic_stats = {}
        for r in results:
            t = r['topic']
            topic_stats[t] = topic_stats.get(t, 0) + 1
        print(f"\n🏷️ Темы:")
        for t, c in sorted(topic_stats.items(), key=lambda x: -x[1])[:10]:
            print(f"   {t}: {c} заданий")
        
        # Сохраняем результаты
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Результаты сохранены в: {args.output}")
        
        # Краткая таблица
        print(f"\n📋 КРАТКАЯ ТАБЛИЦА:")
        print(f"{'ID':<5} {'Сложность':<10} {'Тип':<10} {'Тема':<20} {'AI ответ':<15} {'Правильно':<10}")
        print("-" * 75)
        for r in results:
            ai_ans = r['ai_solution'][:12] + "..." if len(r['ai_solution']) > 15 else r['ai_solution']
            print(f"{r['id']:<5} {r['difficulty']:<10} {r['type']:<10} {r['topic'][:18]:<20} {ai_ans:<15} {'✅' if r['is_correct'] else '❌':<10}")
        
    finally:
        await classifier.ai.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    asyncio.run(main())