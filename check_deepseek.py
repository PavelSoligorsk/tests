"""DeepSeek API smoke test — Полный пайплайн обработки математических задач (асинхронный)."""

import asyncio
import json
import sys
import time
import re
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import aiohttp
import math


class DeepSeekTester:
    """Асинхронный тестер DeepSeek API через aiohttp."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1"
        self.model = "deepseek-chat"
        self.results = []
        self.batch_results = {}
        self.difficulty_stats = defaultdict(lambda: {"total": 0, "correct": 0})
        self.semaphore = asyncio.Semaphore(5)  # Ограничиваем количество параллельных запросов
    
    async def chat_completion(self, 
                             system_prompt: str,
                             user_prompt: str,
                             temperature: float = 0.0,
                             max_tokens: int = 8000,
                             json_mode: bool = False) -> str:
        """Асинхронное выполнение запроса к DeepSeek API."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        if json_mode:
            data["response_format"] = {"type": "json_object"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"API Error: {response.status} - {text}")
                
                result = await response.json()
                return result["choices"][0]["message"]["content"]
    
    def extract_json(self, text: str):
        """Извлечение JSON из текста с обработкой ошибок."""
        # Пробуем найти JSON объект или массив
        try:
            parsed = json.loads(text)
            return parsed
        except:
            pass
        
        # Пробуем найти объект в фигурных скобках
        brace_count = 0
        start_idx = -1
        
        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    json_str = text[start_idx:i+1]
                    try:
                        return json.loads(json_str)
                    except:
                        continue
                    start_idx = -1
        
        # Пробуем найти массив в квадратных скобках
        bracket_count = 0
        start_idx = -1
        
        for i, char in enumerate(text):
            if char == '[':
                if bracket_count == 0:
                    start_idx = i
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1
                if bracket_count == 0 and start_idx != -1:
                    json_str = text[start_idx:i+1]
                    try:
                        return json.loads(json_str)
                    except:
                        continue
                    start_idx = -1
        
        return None
    
    def normalize_response(self, data):
        """Нормализация ответа: если пришел массив, преобразуем в объект с ключом results."""
        if isinstance(data, list):
            return {"results": data}
        return data
    
    async def estimate_difficulty_batch(self, tasks: List[Dict]) -> Dict:
        """Пакетная оценка сложности задач (по 20 штук)."""
        print(f"\n{'='*60}")
        print("📊 ПАКЕТНАЯ ОЦЕНКА СЛОЖНОСТИ (по 20 задач)")
        print('='*60)
        
        batch_size = 20
        all_results = []
        
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            print(f"\n📦 Пакет {i//batch_size + 1}: задачи {i+1}-{min(i+batch_size, len(tasks))}")
            
            tasks_json = []
            for idx, task in enumerate(batch, 1):
                tasks_json.append({
                    "id": idx,
                    "problem": task["problem"]
                })
            
            system_prompt = """Оцени сложность каждой задачи по шкале от 1 до 5.
            Ответь ТОЛЬКО JSON массивом: [{"id": 1, "complexity": 3}]"""
            
            try:
                async with self.semaphore:
                    t0 = time.monotonic()
                    response = await self.chat_completion(
                        system_prompt=system_prompt,
                        user_prompt=json.dumps(tasks_json, ensure_ascii=False),
                        temperature=0.0,
                        max_tokens=4000,
                        json_mode=True
                    )
                    t = time.monotonic() - t0
                
                print(f"  ✅ За {t:.2f}s, длина: {len(response)} символов")
                
                data = self.extract_json(response)
                
                if data:
                    data = self.normalize_response(data)
                    results = data.get("results", []) if isinstance(data, dict) else data
                    
                    if results:
                        for result in results:
                            task_id = result.get("id") - 1
                            if 0 <= task_id < len(batch):
                                difficulty = result.get("complexity") or result.get("difficulty") or 3
                                batch[task_id]["estimated_difficulty"] = difficulty
                                all_results.append({
                                    "problem": batch[task_id]["problem"][:50],
                                    "difficulty": difficulty
                                })
                        
                        print(f"  ✅ Оценено {len(results)} задач")
                    else:
                        print(f"  ❌ Нет результатов")
                else:
                    print(f"  ❌ Не удалось извлечь JSON")
                    
            except Exception as e:
                print(f"  ❌ Ошибка: {type(e).__name__}: {e}")
        
        return all_results

    async def solve_batch_by_difficulty(self, tasks: List[Dict]) -> Dict:
        print(f"\n{'='*60}")
        print("🧮 ПАКЕТНОЕ РЕШЕНИЕ ПО СЛОЖНОСТИ (только ответы)")
        print('='*60)

        grouped = defaultdict(list)
        for task in tasks:
            diff = task.get("estimated_difficulty", 3)
            grouped[diff].append(task)

        batch_sizes = {1: 20, 2: 10, 3: 7, 4: 4, 5: 2}

        for difficulty in sorted(grouped.keys()):
            task_list = grouped[difficulty]
            batch_size = batch_sizes.get(difficulty, 5)

            print(f"\n📊 Сложность {difficulty}/5: {len(task_list)} задач (пакет по {batch_size})")

            for i in range(0, len(task_list), batch_size):
                batch = task_list[i:i+batch_size]
                # Сохраняем эталонные ответы до отправки
                expected_answers = [task.get("answer") for task in batch]

                tasks_json = []
                for idx, task in enumerate(batch, 1):
                    task_data = {"id": idx, "problem": task["problem"]}
                    if task.get("options"):
                        task_data["options"] = task["options"]
                    tasks_json.append(task_data)

                system_prompt = f"Реши задачи (сложность {difficulty}/5). Верни ТОЛЬКО JSON массивом с ответами (без решений): [{{\"id\": 1, \"answer\": \"ответ\"}}]"

                try:
                    async with self.semaphore:
                        response = await self.chat_completion(
                            system_prompt=system_prompt,
                            user_prompt=json.dumps(tasks_json, ensure_ascii=False),
                            temperature=0.1,
                            max_tokens=4000,
                            json_mode=True
                        )

                    data = self.extract_json(response)
                    if data:
                        data = self.normalize_response(data)
                        results = data.get("results", []) if isinstance(data, dict) else data
                        if results:
                            for result in results:
                                task_id = result.get("id") - 1
                                if 0 <= task_id < len(batch):
                                    predicted = result.get("answer", "")
                                    true_answer = expected_answers[task_id]
                                    batch[task_id]["model_answer"] = predicted
                                    # Нормализованное сравнение
                                    is_correct = self.compare_answers(predicted, true_answer)
                                    batch[task_id]["is_correct"] = is_correct
                            correct_count = sum(1 for r in batch if r.get("is_correct", False))
                            print(f"  ✅ {len(results)} задач, правильных: {correct_count}")
                        else:
                            print(f"  ❌ Нет результатов")
                    else:
                        print(f"  ❌ Не удалось извлечь JSON")
                except Exception as e:
                    print(f"  ❌ Ошибка: {type(e).__name__}: {e}")

        # Возвращаем словарь с результатами, если нужен
        return {}  # или можно вернуть что-то полезное
   
    async def classify_tasks(self, tasks: List[Dict]) -> Dict:
        """Классификация задач по типу (только ответы)."""
        print(f"\n{'='*60}")
        print("🏷️ КЛАССИФИКАЦИЯ ЗАДАЧ")
        print('='*60)
        
        solved_tasks = [t for t in tasks if "answer" in t]
        
        if not solved_tasks:
            print("❌ Нет решенных задач для классификации")
            return {}
        
        print(f"📝 Найдено {len(solved_tasks)} решенных задач")
        
        batch_size = 10
        classification_results = {}
        
        for i in range(0, len(solved_tasks), batch_size):
            batch = solved_tasks[i:i+batch_size]
            print(f"\n📦 Пакет {i//batch_size + 1}: {len(batch)} задач")
            
            tasks_json = []
            for idx, task in enumerate(batch, 1):
                tasks_json.append({
                    "id": idx,
                    "problem": task["problem"],
                    "answer": task.get("answer", "")
                })
            
            system_prompt = """Классифицируй задачи по типу.
            Верни ТОЛЬКО JSON массивом: [{"id": 1, "type": "Алгебра"}]"""
            
            try:
                async with self.semaphore:
                    t0 = time.monotonic()
                    response = await self.chat_completion(
                        system_prompt=system_prompt,
                        user_prompt=json.dumps(tasks_json, ensure_ascii=False),
                        temperature=0.0,
                        max_tokens=3000,
                        json_mode=True
                    )
                    t = time.monotonic() - t0
                
                print(f"  ✅ За {t:.2f}s")
                
                data = self.extract_json(response)
                
                if data:
                    data = self.normalize_response(data)
                    results = data.get("results", []) if isinstance(data, dict) else data
                    
                    if results:
                        for result in results:
                            task_id = result.get("id") - 1
                            if 0 <= task_id < len(batch):
                                task_type = result.get("type", "unknown")
                                batch[task_id]["classified_type"] = task_type
                                classification_results[task_type] = classification_results.get(task_type, 0) + 1
                        
                        print(f"  ✅ Классифицировано {len(results)} задач")
                    else:
                        print(f"  ❌ Нет результатов")
                else:
                    print(f"  ❌ Не удалось извлечь JSON")
                    
            except Exception as e:
                print(f"  ❌ Ошибка: {type(e).__name__}: {e}")
    
        return classification_results
    
    def print_final_statistics(self, tasks: List[Dict]):
        """Вывод статистики в формате: условие, варианты, правильный ответ, классификация."""
        print(f"\n{'='*60}")
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print('='*60)
        
        # Вывод в формате датасета
        print("\n📝 ДАННЫЕ ДЛЯ ДАТАСЕТА:")
        print("-" * 80)
        
        for i, task in enumerate(tasks, 1):
            problem = task.get("problem", "")
            options = task.get("options", [])
            correct_answer = task.get("answer", "")
            task_type = task.get("classified_type", task.get("type", "unknown"))
            difficulty = task.get("estimated_difficulty", "?")
            
            print(f"\n--- Задача {i} ---")
            print(f"📌 Условие: {problem}")
            
            if options:
                print(f"📋 Варианты ответов:")
                for j, opt in enumerate(options, 1):
                    print(f"   {j}) {opt}")
            else:
                print(f"📋 Варианты ответов: нет")
            
            print(f"✅ Правильный ответ: {correct_answer}")
            print(f"🏷️ Классификация: {task_type}")
            print(f"📊 Сложность: {difficulty}/5")
            print(f"🎯 Результат: {'✅ Правильно' if task.get('is_correct', False) else '❌ Неправильно'}")
            
            if task.get("model_answer"):
                print(f"🤖 Ответ модели: {task.get('model_answer')}")
            
            print("-" * 40)
        
        # Статистика
        print("\n" + "="*60)
        print("📈 СТАТИСТИКА")
        print('='*60)
        
        total = len(tasks)
        correct = sum(1 for t in tasks if t.get("is_correct", False))
        
        # По сложности
        diff_stats = defaultdict(lambda: {"total": 0, "correct": 0})
        for task in tasks:
            diff = task.get("estimated_difficulty", 0)
            if diff > 0:
                diff_stats[diff]["total"] += 1
                if task.get("is_correct", False):
                    diff_stats[diff]["correct"] += 1
        
        print("\n📊 По сложности:")
        if diff_stats:
            for diff in sorted(diff_stats.keys()):
                stats = diff_stats[diff]
                rate = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
                print(f"   Сложность {diff}/5: {stats['correct']}/{stats['total']} ({rate:.1f}%)")
        
        # По типам
        type_stats = defaultdict(lambda: {"total": 0, "correct": 0})
        for task in tasks:
            task_type = task.get("classified_type", task.get("type", "unknown"))
            if task_type != "unknown":
                type_stats[task_type]["total"] += 1
                if task.get("is_correct", False):
                    type_stats[task_type]["correct"] += 1
        
        print("\n🏷️ По типам задач:")
        if type_stats:
            for task_type in sorted(type_stats.keys()):
                stats = type_stats[task_type]
                rate = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
                print(f"   {task_type}: {stats['correct']}/{stats['total']} ({rate:.1f}%)")
        
        print(f"\n📊 Общая статистика:")
        print(f"   Всего задач: {total}")
        print(f"   Правильно решено: {correct} ({correct/total*100:.1f}%)")

    def compare_answers(self, predicted, true_answer):
        """Умное сравнение с учётом разных форматов."""
        # Приводим к строкам и убираем пробелы
        pred = str(predicted).strip()
        true = str(true_answer).strip()
        if pred == true:
            return True

        # Если оба числа – сравниваем с погрешностью
        try:
            p_num = float(pred.replace(',', '.'))
            t_num = float(true.replace(',', '.'))
            return abs(p_num - t_num) < 1e-6
        except:
            pass

    # Если ответ – комбинация (например, "А3Б1В2") – нормализуем
    # Удаляем лишние символы, сортируем части и сравниваем
    def normalize_combination(s):
        # Убираем пробелы, запятые, точки с запятой
        s = re.sub(r'[,\s;]', '', s)
        # Разбиваем на части по буквам или цифрам, сортируем и склеиваем
        parts = re.findall(r'[А-Яа-я]?\d+|[А-Яа-я]+', s)
        parts.sort()
        return ''.join(parts)

        if re.search(r'[А-Яа-я]\d', pred) and re.search(r'[А-Яа-я]\d', true):
            return normalize_combination(pred) == normalize_combination(true)

        # Для задач с вариантами (номер ответа) – если модель выдала текст варианта,
        # а эталон – номер, можно попробовать сопоставить
        # (здесь нужно реализовать по необходимости)

        return False

async def main():
    print("🧮 DeepSeek API тест — Полный пайплайн обработки задач\n")
    
    api_key = "sk-da80a2413e884d7082d1ff8f0de811c9"
    if not api_key:
        print("❌ DEEPSEEK_API_KEY не задан")
        return 1
    
    tester = DeepSeekTester(api_key)
    
    # Все 65 задач (полный список)
    all_tasks = [
    {
        "id": 51,
        "problem": "Установите соответствие между выражением и его значением.\n| Выражение | Значение |\n|-----------|----------|\n| А) $\\lg 4 + 2\\lg 5$ | $1$) $4$ |\n| Б) $\\log_2 48 - \\frac{1}{2}\\log_2 9$ | $2$) $3$ |\n| В) $3\\lg 5 + 0,5\\lg 64$ | $3$) $2$ |",
        "options": [],
        "answer": "ХУЙ ЖОПА ПИЗДА"
    },
    {
        "id": 52,
        "problem": "Представьте в виде корня $\\sqrt[8]{2} \\cdot \\sqrt[12]{3}$.",
        "options": ["$\\sqrt[24]{6}$", "$\\sqrt[24]{72}$", "$\\sqrt[96]{6}$", "$\\sqrt[24]{12}$", "$\\sqrt[96]{72}$"],
        "answer": 2
    },
    {
        "id": 53,
        "problem": "Образующая конуса равна $17$, а высота — $8$. Найдите площадь боковой поверхности конуса.",
        "options": ["$153\\pi$", "$255\\pi$", "$127,5\\pi$", "$510\\pi$", "$136\\pi$"],
        "answer": 2
    },
    {
        "id": 54,
        "problem": "Решите уравнение $2^{x+5} - 3 = 2^{x+3}$.",
        "options": [],
        "answer": "-3"
    },
    {
        "id": 55,
        "problem": "Решите уравнение $\\sin x \\sin 3x = \\cos 3x \\cos x$ на промежутке $[0; 180^\\circ]$. В ответ запишите сумму корней.",
        "options": [],
        "answer": "360"
    },
    {
        "id": 56,
        "problem": "Найдите сумму всех целых решений системы неравенств:\n$\\begin{cases} (x-2)^2 + 23 > (x+3)^2 - 2 \\\\ 1,6x \\geq 0,9x - 6,3 \\end{cases}$",
        "options": [],
        "answer": "-44"
    },
    {
        "id": 57,
        "problem": "Решите совокупность неравенств $\\frac{x(x-5)(2x-7)}{x+3} > 0$. В ответ запишите сумму всех целых решений.",
        "options": [],
        "answer": "7"
    },
    {
        "id": 58,
        "problem": "Чему равна сумма всех внешних углов треугольника (в градусах)?",
        "options": [],
        "answer": "720"
    },
    {
        "id": 59,
        "problem": "Сколько целых чисел из $[-101; 45]$ входит в ООФ $y = \\sqrt{x^2 - x + 1} + \\frac{2}{\\sqrt{x^2 + 1}}$?",
        "options": ["$145$", "$146$", "$147$", "$148$", "все"],
        "answer": 3
    },
    {
        "id": 60,
        "problem": "Решите уравнение $(7x - 2)(x + 1) = 5x + 19$. В ответ запишите произведение корней.",
        "options": [],
        "answer": "-3"
    },
    {
        "id": 61,
        "problem": "Найдите сумму целых чисел из промежутков возрастания $f(x)=\\frac{33+2x^2}{2-x}$.",
        "options": [],
        "answer": "16"
    },
    {
        "id": 62,
        "problem": "Решите уравнение $81^{5x-4} = \\frac{1}{27}$. В ответ запишите $20x_0$, где $x_0$ корень данного уравнения.",
        "options": [],
        "answer": "13"
    },
    {
        "id": 63,
        "problem": "$ABCDA_1B_1C_1D_1$ — куб. Отрезок $BD_1$ является диагональю куба. Выберите верные утверждения.\n| № | Утверждение |\n|----|--------------|\n| 1 | прямая $BD_1$ лежит в плоскости $DD_1C_1$ |\n| 2 | прямая $BD_1$ пересекает плоскость $BB_1A_1$ |\n| 3 | прямая $BD_1$ лежит в плоскости $B_1BD$ |\n| 4 | прямые $BD_1$ и $C_1D_1$ являются скрещивающимися |\n| 5 | прямая $BD_1$ пересекает прямую $AC_1$ |\n| 6 | прямая $BD_1$ пересекает прямую $A_1B_1$ |",
        "options": [],
        "answer": "235"
    },
    {
        "id": 64,
        "problem": "Периметр прямоугольника $17,6$ см. Одна сторона $0,45$ дм. Найдите площадь в дм².",
        "options": ["$0,1835$", "$0,1885$", "$0,1935$", "$0,1985$", "$0,2035$"],
        "answer": 3
    }
]

    print(f"📝 Всего задач: {len(all_tasks)}")
    
    # ШАГ 1: Пакетная оценка сложности (по 20 штук)
    print("\n" + "="*60)
    print("ЭТАП 1: ПАКЕТНАЯ ОЦЕНКА СЛОЖНОСТИ")
    print("="*60)
    difficulty_results = await tester.estimate_difficulty_batch(all_tasks)
    
    # ШАГ 2: Пакетное решение по сложности
    print("\n" + "="*60)
    print("ЭТАП 2: ПАКЕТНОЕ РЕШЕНИЕ ПО СЛОЖНОСТИ")
    print("="*60)
    await tester.solve_batch_by_difficulty(all_tasks)
    
    # ШАГ 3: Классификация решенных задач
    print("\n" + "="*60)
    print("ЭТАП 3: КЛАССИФИКАЦИЯ ЗАДАЧ")
    print("="*60)
    classification_results = await tester.classify_tasks(all_tasks)
    
    # ШАГ 4: Вывод итоговой статистики
    tester.print_final_statistics(all_tasks)
    
    print(f"\n{'='*60}")
    print("🏁 РАБОТА ЗАВЕРШЕНА")
    print('='*60)
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))