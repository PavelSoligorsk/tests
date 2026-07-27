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
        self.model = "deepseek-v4-flash"
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
    
    all_tasks = [
    {
        "id": 101,
        "problem": "Разложите многочлен на множители $2x^2 - 18$.",
        "options": ["$2(x-3)(x+3)$", "$2(x-9)(x+9)$", "$(2x-6)(x+3)$", "$2(x^2-9)$"],
        "answer": 1
    },
    {
        "id": 102,
        "problem": "Представьте число $0,53$ в стандартном виде и найдите порядок числа.",
        "options": [],
        "answer": "-1"
    },
    {
        "id": 103,
        "problem": "Найдите сумму всех целых чисел из области определения функции $y = \\sqrt[6]{\\frac{7 - 6x - x^2}{(x + 5)^2}}$.",
        "options": [],
        "answer": "-22"
    },
    {
        "id": 104,
        "problem": "Вокруг прямоугольного треугольника описана окружность радиусом $5\\sqrt{5}$. Один катет в два раза ближе к центру окружности, чем другой. Найдите меньший катет.",
        "options": ["$8$", "$9$", "$10$", "$11$", "$12$"],
        "answer": 3
    },
    {
        "id": 105,
        "problem": "Среди чисел $-5$; $5$; $0,5$; $\\sqrt{5}$; $5^{-1}$ укажите то, которое не входит в область определения выражения $\\frac{17}{x+5}$.",
        "options": ["$-5$", "$5$", "$0,5$", "$\\sqrt{5}$", "$5^{-1}$"],
        "answer": 1
    },
    {
        "id": 106,
        "problem": "Установите соответствие между выражением и значением.\n| Выражение | Значение |\n|-----------|----------|\n| А) $\\sqrt[3]{1000 \\cdot 0,027}$ | $1$) $10$ |\n| Б) $\\sqrt[4]{10^8 \\cdot 0,0001}$ | $2$) $3$ |\n| В) $\\sqrt[3]{2^6 \\cdot 5^3}$ | $3$) $20$ |",
        "options": [],
        "answer": "А2Б1В3"
    },
    {
        "id": 107,
        "problem": "Представьте в виде степени $(a^{\\frac{1}{4}})^3 \\cdot \\sqrt[8]{a}$.",
        "options": ["$a^{\\frac{7}{8}}$", "$a^{\\frac{3}{4}}$", "$a^{\\frac{5}{8}}$", "$a^{\\frac{1}{2}}$", "$a^{\\frac{3}{8}}$"],
        "answer": 1
    },
    {
        "id": 108,
        "problem": "Найдите значение выражения $x_1 + x_2 - 7x_1x_2$, если $x_1$ и $x_2$ — корни уравнения $-5x^2 + 2x + 9 = 0$.",
        "options": [],
        "answer": "13"
    },
    {
        "id": 109,
        "problem": "Решите неравенство $\\log_{1/2}(x-1) < \\log_{1/2}5 - \\log_{1/2}(x-5)$. Найдите наименьшее целое решение.",
        "options": [],
        "answer": "7"
    },
    {
        "id": 110,
        "problem": "Определите знак выражения $\\sin \\frac{8\\pi}{7} \\cdot \\sin \\frac{13\\pi}{6} \\cdot \\sin \\frac{3\\pi}{5}$.",
        "options": ["положительный", "отрицательный", "равен $0$", "невозможно определить"],
        "answer": 2
    },
    {
        "id": 111,
        "problem": "Решите уравнение $\\cos x = \\frac{\\sqrt{2}}{2}$ на промежутке $[-180^\\circ; 180^\\circ]$. В ответ запишите сумму корней.",
        "options": [],
        "answer": "0"
    },
    {
        "id": 112,
        "problem": "Какие из функций являются логарифмическими?",
        "options": ["$y = x \\cdot \\log_5 4$", "$y = 5^x$", "$y = \\log_2 x$", "$y = \\log_{0,3} x$", "$y = \\sqrt{x}$"],
        "answer": "3,4"
    },
    {
        "id": 113,
        "problem": "Найдите произведение наименьшего целого решения на количество всех целых решений неравенства $\\left(\\frac{1}{14}\\right)^{\\frac{x-5}{x+7}} + \\left(\\frac{1}{28}\\right)^{\\frac{x-5}{x+7}} \\le 2 \\cdot \\left(\\frac{1}{56}\\right)^{\\frac{x-5}{x+7}}$.",
        "options": [],
        "answer": "-72"
    },
    {
        "id": 114,
        "problem": "На рисунке изображены графики движения трех пешеходов. Определите скорость движения (в м/мин) того пешехода, который идет с наибольшей скоростью.",
        "options": ["$60$", "$45$", "$30$", "$50$", "$40$"],
        "answer": 1
    },
    {
        "id": 115,
        "problem": "Бригада рабочих должна была отремонтировать участок дороги длиной $240$ метров за определённое количество дней. Ежедневно перевыполняя план на $6$ метров, бригада закончила работу на $2$ дня раньше срока. За сколько дней по плану должна была быть выполнена работа?",
        "options": [],
        "answer": "10"
    },
    {
        "id": 116,
        "problem": "Через вершину $A$ квадрата $ABCD$ проведена прямая $AO \\perp$ его плоскости. $OA = 16$ см, $AB = 8$ см. Найдите расстояние от $O$ до прямой $BC$ (в ответе укажите коэффициент перед $\\sqrt{5}$).",
        "options": [],
        "answer": "8"
    },
    {
        "id": 117,
        "problem": "Диагональ прямоугольника $12$ см, угол между диагональю и стороной $30^\\circ$. Найдите периметр в см (в ответе укажите коэффициент перед скобкой).",
        "options": [],
        "answer": "12"
    },
    {
        "id": 118,
        "problem": "Найдите произведение наименьшего целого решения на количество всех целых решений неравенства $\\frac{(x^3 - x - 169 + (x - 12)^2)(x + 5)}{x^2 - 13x + 40} \\le 0$.",
        "options": [],
        "answer": "-45"
    },
    {
        "id": 119,
        "problem": "На пастбище квадратной формы загон для скота огорожен так, как показано на рисунке. Все размеры указаны в метрах. Найдите площадь загона (в м²), если площадь пастбища в $32$ раза больше площади загона.",
        "options": [],
        "answer": "800"
    },
    {
        "id": 120,
        "problem": "Катеты прямоугольного треугольника $6$ см и $8$ см. Плоскость через гипотенузу образует угол $30^\\circ$ с плоскостью треугольника. Найдите расстояние от вершины прямого угла до этой плоскости (в см, десятичной дробью).",
        "options": [],
        "answer": "2,4"
    },
    {
        "id": 121,
        "problem": "Радиус основания конуса равен $3\\sqrt{5}$, площадь его осевого сечения равна $9\\sqrt{5}$. Найдите значение выражения $\\frac{V}{\\pi}$, где $V$ – объем конуса.",
        "options": [],
        "answer": "45"
    },
    {
        "id": 122,
        "problem": "В окружность радиусом $6\\sqrt{2}$ см вписан квадрат. Найдите периметр квадрата.",
        "options": [],
        "answer": "48"
    },
    {
        "id": 123,
        "problem": "Упростите выражение $10(2(0,3a - 1) - 0,4(3a - 5))$ при $a = -2$.",
        "options": [],
        "answer": "12"
    },
    {
        "id": 124,
        "problem": "В равнобедренном треугольнике $ABC$ с прямым углом $A$ точки $K$ и $E$ — середины боковых сторон. Из $K$ опущен перпендикуляр $KM$ на гипотенузу. Найдите $KM$, если $OC = 8$ см ($O$ — точка на гипотенузе).",
        "options": ["$6$", "$7$", "$8$", "$9$", "$10$"],
        "answer": 3
    },
    {
        "id": 125,
        "problem": "Найдите $\\log_2 g\\left(\\frac{1}{2}\\right)$, если $g(x) = 2^x$.",
        "options": [],
        "answer": "0,5"
    },
    {
        "id": 126,
        "problem": "Найдите произведение наибольшего целого решения на количество всех целых решений неравенства $(x + \\log_{0,5} 64)^2 (x-3)(x+13) \\leq 0$.",
        "options": [],
        "answer": "108"
    },
    {
        "id": 127,
        "problem": "Дана арифметическая прогрессия $(a_n)$, у которой $a_{12} - a_5 = 28$, $a_{14} = 34$. Определите наибольшее количество членов этой арифметической прогрессии, которые нужно взять (начиная с первого), чтобы их сумма была меньше $400$.",
        "options": [],
        "answer": "19"
    },
    {
        "id": 128,
        "problem": "Через две образующие конуса проведено сечение, основание которого — хорда, длина которой $16$ см. Вычислите площадь полной поверхности конуса, если радиус его основания равен $10$ см, а угол наклона плоскости сечения к плоскости основания равен $60^\\circ$. Найдите $\\frac{S}{(5+2\\sqrt{13})\\pi}$.",
        "options": [],
        "answer": "20"
    },
    {
        "id": 129,
        "problem": "Найдите сумму всех целых отрицательных решений неравенства $5^{x^3+4x^2} \\geq (\\sqrt{5})^{24x}$.",
        "options": [],
        "answer": "-21"
    },
    {
        "id": 130,
        "problem": "Решите квадратное неравенство $18x^2 - 2 < 0$. В ответ запишите наибольшее целое решение.",
        "options": [],
        "answer": "0"
    },
    {
        "id": 131,
        "problem": "Стороны прямоугольника относятся как $5:6$. Найдите отношение периметра к большей стороне (в ответе укажите знаменатель).",
        "options": [],
        "answer": "3"
    },
    {
        "id": 132,
        "problem": "Найдите (в градусах) наименьший положительный корень уравнения $4 \\sin \\frac{x}{7} \\cos \\frac{x}{7} = \\sqrt{3}$.",
        "options": [],
        "answer": "210"
    },
    {
        "id": 133,
        "problem": "Два угла относятся как $1:3$, третий на $20^\\circ$ больше суммы первых двух. Найдите наибольший угол (в градусах).",
        "options": [],
        "answer": "100"
    },
    {
        "id": 134,
        "problem": "Найдите наименьшее значение $f(x) = -\\frac{12}{x}$ на $[-6; -0,5]$.",
        "options": ["$2$", "$24$", "$-24$", "$-2$", "$12$"],
        "answer": 1
    },
    {
        "id": 135,
        "problem": "Плоскость, параллельная основанию конуса, делит его высоту в отношении $2:5$ (от вершины). Площадь сечения меньше площади основания на $270\\pi$. Образующая образует с основанием угол $\\operatorname{arctg}\\frac{5}{7}$. Найдите $\\frac{\\sqrt{6} \\cdot V}{\\pi}$ ($V$ – объем).",
        "options": [],
        "answer": "2940"
    },
    {
        "id": 136,
        "problem": "Избавьтесь от иррациональности в знаменателе $\\frac{4}{\\sqrt{13} - \\sqrt{11}}$.",
        "options": ["$2\\sqrt{13} + 2\\sqrt{11}$", "$\\sqrt{13} + \\sqrt{11}$", "$2\\sqrt{13} - 2\\sqrt{11}$", "$\\sqrt{13} - \\sqrt{11}$"],
        "answer": 1
    },
    {
        "id": 137,
        "problem": "Укажите номера функций, которые убывают на промежутке $[-6; -4]$.",
        "options": ["$y = \\sqrt{x+6}$", "$y = \\cos x$", "$y = -3x+10$", "$y = -x^2+3$", "$y = \\frac{6}{x}$"],
        "answer": "2,3,5"
    },
    {
        "id": 138,
        "problem": "$SABC$ — тетраэдр. Медианы грани $ABC$ пересекаются в $O$. $P$, $E$, $D$ — середины $SC$, $SA$, $SB$. Найдите угол между $BC$ и $PE$ (в градусах).",
        "options": [],
        "answer": "60"
    },
    {
        "id": 139,
        "problem": "Среди выражений $\\sqrt{4}$; $\\log_6 6$; $\\cos\\left(-\\frac{\\pi}{3}\\right)$; $\\sqrt[3]{27}$; $4^{-1}$ укажите то, значение которого наименьшее.",
        "options": ["$\\sqrt{4}$", "$\\log_6 6$", "$\\cos\\left(-\\frac{\\pi}{3}\\right)$", "$\\sqrt[3]{27}$", "$4^{-1}$"],
        "answer": 5
    },
    {
        "id": 140,
        "problem": "На рисунке изображена треугольная пирамида SABC. Точка K принадлежит ребру SC. Среди прямых SB; AK; SC; BK; BA укажите прямую, по которой пересекаются плоскости BKA и SBC.",
        "options": ["SB", "AK", "SC", "BK", "BA"],
        "answer": 4
    },
    {
        "id": 141,
        "problem": "В треугольнике $ABC$ проведена высота $BH$. Биссектриса угла $A$ делит высоту $BH$ в отношении $13:5$, считая от точки $B$. Найдите $BH$, если $AB = 26$ см.",
        "options": ["$20$", "$22$", "$24$", "$26$", "$28$"],
        "answer": 3
    },
    {
        "id": 142,
        "problem": "Найдите сумму всех натуральных решений совокупности неравенств $\\left[\\begin{matrix}0,4x - 2 \\le 0 \\\\ 2 - x > 0\\end{matrix}\\right.$.",
        "options": [],
        "answer": "15"
    },
    {
        "id": 143,
        "problem": "$f(x) = x^2 + 4x$. При каких $x$ значение равно $5$? В ответе положительный корень.",
        "options": [],
        "answer": "1"
    },
    {
        "id": 144,
        "problem": "Диагонали параллелограмма относятся как $2:3$, стороны равны $11$ см и $23$ см. Найдите большую диагональ (в см).",
        "options": [],
        "answer": "30"
    },
    {
        "id": 145,
        "problem": "Упростите выражение $-(a - 2)(7 - 2a) - 2a^2$ при $a = -3$.",
        "options": [],
        "answer": "47"
    },
    {
        "id": 146,
        "problem": "Найдите $\\frac{\\log_3 16}{\\log_3 48 - 1}$.",
        "options": ["$\\frac{1}{2}$", "$1$", "$2$", "$\\frac{3}{2}$", "$\\frac{4}{3}$"],
        "answer": 2
    },
    {
        "id": 147,
        "problem": "Решите уравнение $0,01^x = 10$. В ответ запишите $2x_0$, где $x_0$ корень данного уравнения.",
        "options": [],
        "answer": "-1"
    },
    {
        "id": 148,
        "problem": "Длины всех сторон треугольника являются целыми числами. Длина одной стороны треугольника равна 1, а другой – 3. Установите соответствие.\n| Начало предложения | Окончание предложения |\n|---------------------|------------------------|\n| А) Периметр треугольника равен ... | $1$) $6$ |\n| Б) Площадь треугольника равна ... | $2$) $\\frac{\\sqrt{35}}{8}$ |\n| В) Косинус большего угла треугольника равен ... | $3$) $7$ |\n| | $4$) $\\frac{17}{18}$ |\n| | $5$) $\\frac{1}{6}$ |\n| | $6$) $\\frac{\\sqrt{35}}{4}$ |",
        "options": [],
        "answer": "А3Б6В5"
    },
    {
        "id": 149,
        "problem": "Методом замены переменной решите уравнение $(x^2 + x)^2 + 3(x^2 + x) - 10 = 0$. В ответ запишите сумму корней.",
        "options": [],
        "answer": "-1"
    },
    {
        "id": 150,
        "problem": "При пересечении двух прямых сумма трёх углов равна $250^\\circ$. Найдите больший из четырёх углов.",
        "options": ["$100^\\circ$", "$105^\\circ$", "$110^\\circ$", "$115^\\circ$", "$120^\\circ$"],
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