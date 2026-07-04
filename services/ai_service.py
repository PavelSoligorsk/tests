import json
import re
import os
from mistralai.client import Mistral
from typing import List, Dict, Optional

class AIService:
    def __init__(self):
        self.client = Mistral(api_key=os.getenv("MISTRAL_TOKEN"))
        self.model = "ministral-8b-2512"
    
    def _chat_completion(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 800) -> str:
        """Базовый метод для отправки запросов в Mistral"""
        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"AI Error: {str(e)}")
    
    def get_hint(self, task: dict, topic_mastery: Optional[float] = None) -> str:
        """Получить подсказку для задания"""
        prompt = self._build_hint_prompt(task, topic_mastery)
        
        return self._chat_completion(
            system_prompt="Ты — терпеливый ИИ-репетитор. Помогаешь понять, а не решаешь за студента. ВСЕ математические формулы и выражения ОБЯЗАТЕЛЬНО оформляй в $...$ (строчные) или $$...$$ (вынесенные).",
            user_prompt=prompt,
            temperature=0.7,
            max_tokens=800
        )
    
    def get_solution(self, task: dict, topic_mastery: Optional[float] = None) -> str:
        """Получить полное решение задачи"""
        prompt = self._build_solution_prompt(task, topic_mastery)
        
        return self._chat_completion(
            system_prompt="Ты — математический эксперт. Решай задачи подробно, показывай все шаги. В конце обязательно укажи ответ в формате '=== ОТВЕТ === ...'",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=2000
        )
    
    def get_theory_answer(self, question: str, theory_context: str, topic_name: str = "", section_name: str = "") -> str:
        """Ответить на вопрос по теории"""
        prompt = self._build_theory_prompt(question, theory_context, topic_name, section_name)
        
        return self._chat_completion(
            system_prompt="Ты — терпеливый ИИ-репетитор по математике. Объясняешь теорию, отвечаешь на вопросы, помогаешь понять материал. ВСЕ математические формулы и выражения ОБЯЗАТЕЛЬНО оформляй в $...$ (строчные) или $$...$$ (вынесенные). НИКОГДА не используй \\(...\\) или \\[...\\].",
            user_prompt=prompt,
            temperature=0.7,
            max_tokens=3000
        )
    
    def classify_topics(self, user_prompt: str, topics_structure: Dict[str, set]) -> List[Dict]:
        """Классифицировать запрос студента по темам и разделам"""
        hierarchy_context = self._build_hierarchy_context(topics_structure)
        
        prompt = self._build_classification_prompt(user_prompt, hierarchy_context)
        
        response = self._chat_completion(
            system_prompt="Ты — строгий классификатор. Отвечаешь только валидным JSON без разметки markdown.",
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=500
        )
        
        return self._parse_classification_response(response)
    
    def select_tasks(self, user_prompt: str, available_tasks: List[Dict], task_count: int, 
                     difficulty_text: str, topics_count: int, topic_stats: Dict[str, int]) -> List[int]:
        """Выбрать лучшие задания из доступных"""
        prompt = self._build_selection_prompt(user_prompt, available_tasks, task_count, 
                                              difficulty_text, topics_count, topic_stats)
        
        response = self._chat_completion(
            system_prompt='Ты — эксперт. Отвечай ТОЛЬКО JSON: {"task_ids": [1,2,3]}',
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=800
        )
        
        return self._parse_task_ids(response)
    
    def _build_hint_prompt(self, task: dict, topic_mastery: Optional[float]) -> str:
        prompt = f"""Ты — AI-репетитор по математике. Студент решает задание и просит подсказку.
НЕ ДАВАЙ ГОТОВЫЙ ОТВЕТ. Объясни подход, метод, наведи на мысль.

=== ФОРМАТ ФОРМУЛ ===
- Для формул внутри строки используй $...$ (например, $ax^2 + bx + c = 0$)
- Для вынесенных формул и выражений используй $$...$$ (например, $$\\int_{{a}}^{{b}} f(x) dx$$)
- Все математические записи ОБЯЗАТЕЛЬНО заключай в $...$ или $$...$$

=== ЗАДАНИЕ ===
Класс: {task.get('task_class')}
Тема №: {task.get('topic_number')}
Тема: {task.get('topic', 'Не указана')}
Раздел: {task.get('section', 'Не указан')}
Сложность (1-5): {task.get('difficulty')}
Тип: {'открытый ответ' if task.get('is_open_answer') else 'выбор варианта'}

Условие:
{task.get('content')}

Варианты: {task.get('options', 'Нет (открытый вопрос)')}
"""
        
        if topic_mastery is not None:
            prompt += f"""
=== УСВОЕНИЕ ТЕМЫ ===
Решено задач по этой теме: {task.get('same_topic_total')}
Правильно: {task.get('same_topic_correct')} ({topic_mastery}%)
"""
        
        prompt += self._get_format_instructions()
        return prompt
    
    def _build_solution_prompt(self, task: dict, topic_mastery: Optional[float]) -> str:
        prompt = f"""Ты — AI-репетитор по математике. Реши задачу и дай полное, подробное решение.

=== ФОРМАТ ФОРМУЛ ===
- Для формул внутри строки используй $...$ (например, $ax^2 + bx + c = 0$)
- Для вынесенных формул и выражений используй $$...$$ (например, $$\\int_{{a}}^{{b}} f(x) dx$$)
- Все математические записи ОБЯЗАТЕЛЬНО заключай в $...$ или $$...$$

=== ЗАДАНИЕ ===
Класс: {task.get('task_class')}
Тема №: {task.get('topic_number')}
Тема: {task.get('topic', 'Не указана')}
Раздел: {task.get('section', 'Не указан')}
Сложность (1-5): {task.get('difficulty')}
Тип: {'открытый ответ' if task.get('is_open_answer') else 'выбор варианта'}

Условие:
{task.get('content')}

Варианты ответа: {task.get('options', 'Нет (открытый вопрос)')}
"""
        
        if topic_mastery is not None:
            prompt += f"""
=== УСВОЕНИЕ ТЕМЫ ===
Решено задач по этой теме: {task.get('same_topic_total')}
Правильно: {task.get('same_topic_correct')} ({topic_mastery}%)
"""
        
        prompt += self._get_solution_requirements()
        return prompt
    
    def _build_theory_prompt(self, question: str, theory_context: str, topic_name: str, section_name: str) -> str:
        return f"""Ты — AI-репетитор по математике. Студент изучает теорию и задаёт вопрос.
Твоя задача — объяснить материал понятно, с примерами, но не давать готовых ответов, если студент не просит решить задачу.

=== ФОРМАТ ФОРМУЛ ===
- Для формул внутри строки используй $...$ (например, $ax^2 + bx + c = 0$)
- Для вынесенных формул и выражений используй $$...$$ (например, $$\\frac{{a}}{{b}}$$)
- Все математические записи ОБЯЗАТЕЛЬНО заключай в $...$ или $$...$$
- НИКОГДА не используй \\( ... \\) или \\[ ... \\]

=== ТЕОРЕТИЧЕСКИЙ МАТЕРИАЛ ===
Тема: {topic_name or 'Не указана'}
Раздел: {section_name or 'Не указан'}

Содержание теории:
{theory_context}

=== ВОПРОС СТУДЕНТА ===
{question}

=== ИНСТРУКЦИЯ ДЛЯ AI ===
1. Отвечай простыми, понятными предложениями
2. Используй примеры для иллюстрации
3. Объясняй «почему», а не только «как»
4. Если вопрос не по теме — вежливо направь к материалу
5. ВСЕ математические выражения оформляй в $...$ или $$...$$
6. Не используй списки с маркерами, пиши связным текстом
7. Если студент просит решить задачу — реши пошагово с объяснениями
8. Используй картинки по смыслу, которые есть в контексте. Просто вставляй их, как в обычный маркдаун 
9. При необходимости визуализации используй GeoGebra: <GeoGebra setup= команды />
10. Для 3D графики первой командой пиши SetPerspective("5")
11. Не злоупотребляй GeoGebra, только когда это действительно нужно
12*** Используй только те команды Geogebra, которые даны в примерах!!!
"""
    
    def _build_hierarchy_context(self, topics_structure: Dict[str, set]) -> List[str]:
        hierarchy_context = []
        for topic, sections in topics_structure.items():
            hierarchy_context.append(f"- Тема: {topic}")
            if sections:
                hierarchy_context.append(f"  Разделы: {', '.join(sorted(sections))}")
        return hierarchy_context
    
    def _build_classification_prompt(self, user_prompt: str, hierarchy_context: List[str]) -> str:
        return f"""Ты — классификатор учебных заданий по математике.
Анализируй запрос студента и сопоставляй его исключительно с ТЕМАМИ и РАЗДЕЛАМИ из реальной структуры базы данных ниже.

=== РЕАЛЬНАЯ СТРУКТУРА БАЗЫ ДАННЫХ ===
{chr(10).join(hierarchy_context)}

=== ЗАПРОС СТУДЕНТА ===
{user_prompt}

=== ПОДРОБНАЯ ИНСТРУКЦИЯ ===

1. **Анализ запроса:**
   - Внимательно прочитай запрос студента
   - Определи, о каких математических темах идёт речь

2. **Правила выбора тем:**
   - Если студент пишет "отработка уравнений" → возьми ВСЕ темы из раздела "Уравнения и неравенства", которые содержат слово "уравнение"
   - Если "дроби" → возьми тему "Числа и вычисления" с разделами про дроби
   - Если "геометрия" → возьми тему "Геометрия" со всеми её разделами
   - Если "стереометрия" → возьми тему "Геометрия" с разделами по стереометрии
   - Если запрос общий и охватывает много тем → выбери ВСЕ подходящие темы

3. **Правила выбора разделов:**
   - Если запрос точный ("квадратные уравнения") → укажи конкретный раздел
   - Если запрос общий ("уравнения") → укажи ВСЕ разделы, где есть слово "уравнение" в названии
   - Если запрос очень общий ("математика") → выбери 3-5 основных тем

4. **Если точного совпадения нет:**
   - Выбери максимально близкие по смыслу темы и разделы
   - Лучше выбрать БОЛЬШЕ тем, чем пропустить что-то важное

=== ВАЖНО ===
- sections можно оставить пустым массивом [], если нужно взять ВСЕ разделы темы
- Если тема не указана в структуре БД, НЕ придумывай её
- Количество тем НЕ ограничено — выбери все, что подходят под запрос

Верни ТОЛЬКО JSON строго в формате:
{{
  "topics": [
    {{"name": "Название темы 1", "sections": ["Раздел 1", "Раздел 2"]}},
    {{"name": "Название темы 2", "sections": []}}
  ]
}}
"""
    
    def _parse_classification_response(self, response: str) -> List[Dict]:
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                classification = json.loads(json_match.group())
                return classification.get("topics", [])
        except Exception as e:
            print(f"[ERROR] AI classification parsing failed: {e}")
        return []
    
    def _build_selection_prompt(self, user_prompt: str, available_tasks: List[Dict], 
                               task_count: int, difficulty_text: str, 
                               topics_count: int, topic_stats: Dict[str, int]) -> str:
        stats_context = "\n".join([f"- {t}: {c} заданий" for t, c in topic_stats.items()])
        
        return f"""Ты — эксперт по подбору учебных заданий по математике.

=== ЗАПРОС СТУДЕНТА ===
{user_prompt}

=== ПАРАМЕТРЫ ===
Нужно выбрать заданий: {task_count}
Сложность: {difficulty_text}
Определено тем: {topics_count}

=== СТАТИСТИКА ДОСТУПНЫХ ЗАДАНИЙ ПО ТЕМАМ ===
{stats_context}

=== ОТФИЛЬТРОВАННЫЕ ЗАДАНИЯ ===
Всего доступно: {len(available_tasks)} заданий

Список заданий:
{chr(10).join(available_tasks)}

=== ИНСТРУКЦИЯ ===
1. Проанализируй запрос студента: "{user_prompt}"
2. Из предложенных заданий выбери РОВНО {task_count} НАИБОЛЕЕ ПОДХОДЯЩИХ
3. Если тем несколько — распредели задания МЕЖДУ ВСЕМИ темами пропорционально их важности для запроса
4. Внутри каждой темы выбирай задания с РАЗНОЙ сложностью (если доступны)
5. Учитывай содержание задания, тему, сложность
6. Верни ТОЛЬКО JSON: {{"task_ids": [45, 67, 123, ...]}}
7. Если подходящих меньше {task_count} — верни сколько есть
"""
    
    def _parse_task_ids(self, response: str) -> List[int]:
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group())
                return result_data.get("task_ids", [])
        except Exception as e:
            print(f"[ERROR] AI task selection parsing failed: {e}")
        return []
    
    def _get_format_instructions(self) -> str:
        return """
=== ИНСТРУКЦИЯ ДЛЯ AI ===

Ты помогаешь студенту решить задачу, но НЕ даёшь готовый ответ.

Правила оформления:
1. Пиши простыми, понятными предложениями (3-6 предложений)
2. Используй переносы строк между смысловыми блоками
3. Выражения в тексте оформляй как $...$ (например, $c^2$, $a^3$, $x^2$)
4. КЛЮЧЕВОЕ ПРАВИЛО: все формулы, преобразования, вычисления и промежуточные шаги выноси на отдельную строку с центрированием через $$...$$. ДО и ПОСЛЕ каждой формулы ОБЯЗАТЕЛЬНО ставь пустую строку.
5. Показывай каждый шаг преобразования отдельной формулой
6. Не используй звёздочки, списки, маркеры и нумерацию — пиши связным текстом

НЕ пиши: "Ответ: ..." или "Правильный вариант — ..."
НЕ решай полностью — только направляй, показывая примеры преобразований.
"""
    
    def _get_solution_requirements(self) -> str:
        return """
=== ТРЕБОВАНИЯ ДЛЯ KATEX ===
1. Реши задачу пошагово
2. В конце напиши: "=== ОТВЕТ === ..."
3. Используй ТОЛЬКО $...$ для формул внутри текста
4. Используй ТОЛЬКО $$...$$ для вынесенных формул
5. НЕ ИСПОЛЬЗУЙ \\(...\\) и \\[...\\] — они НЕ РАБОТАЮТ в KaTeX
6. Для дробей пиши \\frac{числитель}{знаменатель}
7. Не используй списки, маркеры, звёздочки
8. Пиши связным текстом с выделением шагов
9. Для вопроса с варианатми ответа - в ответе укажи номер или номера правильных вариантов. Если без вариантов - число
10. Используй картинки по смыслу, которые есть в контексте. Просто вставляй их, как в обычный маркдаун 

ЗАПОМНИ: используй ТОЛЬКО $...$ и $$...$$, НИКОГДА не используй \\( ... \\) или \\[ ... \\]
"""