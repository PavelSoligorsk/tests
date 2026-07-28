import json
import re
import os
import asyncio
import logging
from typing import List, Dict, Optional, Literal

AIProvider = Literal["mistral", "deepseek"]

logger = logging.getLogger(__name__)


class AIService:
    """Гибкий AI-сервис с поддержкой Mistral (по умолчанию) и DeepSeek.

    Использование:
        ai = AIService()                   # Mistral (backward compatible)
        ai = AIService(provider="mistral") # явно Mistral
        ai = AIService(provider="deepseek")# DeepSeek
    """

    def __init__(self, provider: AIProvider = "mistral"):
        self.provider = provider
        if provider == "deepseek":
            import openai
            self.client = openai.AsyncOpenAI(
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com",
            )
            self.model = "deepseek-v4-pro"
        else:
            from mistralai.client import Mistral
            self.client = Mistral(api_key=os.getenv("MISTRAL_TOKEN"))
            self.model = "ministral-14b-2512"

    async def _chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 800,
        json_mode: bool = False,
        enable_thinking: bool = False,
    ) -> str:
        """Базовый метод — автоматически выбирает API в зависимости от провайдера.

        Args:
            json_mode: If True, sets response_format={'type': 'json_object'} (DeepSeek),
                       which requires "json" in the prompt. Mutually exclusive with enable_thinking.
            enable_thinking: If True, enables DeepSeek thinking/reasoning via extra_body.
                             Use for math solving where step-by-step reasoning improves accuracy.
                             WARNING: thinking tokens count toward max_tokens — ensure budget is adequate
                             (~500-1000 tokens per task with thinking enabled).
        """
        try:
            if self.provider == "deepseek":
                kwargs: dict = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }

                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                elif enable_thinking:
                    kwargs["extra_body"] = {
                        "thinking": {"type": "enabled"},
                        "reasoning_effort": "low",
                    }

                response = await self.client.chat.completions.create(**kwargs)

                content = response.choices[0].message.content
                # Fallback: если thinking съел все токены, content может быть пустым.
                # Пробуем reasoning_content как последнее средство.
                if (not content or not content.strip()) and enable_thinking:
                    reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                    if reasoning:
                        logger.info(
                            "DeepSeek thinking consumed all tokens — falling back to reasoning_content "
                            f"({len(reasoning)} chars)"
                        )
                        content = reasoning
                if not content or not content.strip():
                    logger.warning(
                        f"DeepSeek returned empty content. "
                        f"json_mode={json_mode}, thinking={enable_thinking}, "
                        f"max_tokens={max_tokens}, finish_reason="
                        f"{getattr(response.choices[0], 'finish_reason', '?')}"
                    )
                return content or ""
            else:
                response = await asyncio.to_thread(
                    self.client.chat.complete,
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"AI Error ({self.provider}): {type(e).__name__}: {e}", exc_info=True)
            raise Exception(f"AI Error ({self.provider}): {str(e)}")
    
    async def get_hint(self, task: dict, topic_mastery: Optional[float] = None) -> str:
        """Получить подсказку для задания"""
        prompt = self._build_hint_prompt(task, topic_mastery)
        
        return await self._chat_completion(
            system_prompt="Ты — терпеливый ИИ-репетитор. Помогаешь понять, а не решаешь за студента. ВСЕ математические формулы и выражения ОБЯЗАТЕЛЬНО оформляй в $...$ (строчные) или $$...$$ (вынесенные).",
            user_prompt=prompt,
            temperature=0.7,
            max_tokens=800
        )
    
    async def get_solution(self, task: dict, topic_mastery: Optional[float] = None) -> str:
        """Получить полное решение задачи"""
        prompt = self._build_solution_prompt(task, topic_mastery)
        
        return await self._chat_completion(
            system_prompt="Ты — математический эксперт. Решай задачи подробно, показывай все шаги. В конце обязательно укажи ответ в формате '=== ОТВЕТ === ...'",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=2000
        )
    
    async def get_theory_answer(self, question: str, theory_context: str, topic_name: str = "", section_name: str = "") -> str:
        """Ответить на вопрос по теории"""
        prompt = self._build_theory_prompt(question, theory_context, topic_name, section_name)
        
        return await self._chat_completion(
            system_prompt="Ты — терпеливый ИИ-репетитор по математике. Объясняешь теорию, отвечаешь на вопросы, помогаешь понять материал. ВСЕ математические формулы и выражения ОБЯЗАТЕЛЬНО оформляй в $...$ (строчные) или $$...$$ (вынесенные). НИКОГДА не используй \\(...\\) или \\[...\\].",
            user_prompt=prompt,
            temperature=0.7,
            max_tokens=3000
        )
    
    async def classify_topics(self, user_prompt: str, topics_structure: Dict[str, set]) -> List[Dict]:
        """Классифицировать запрос студента по темам и разделам, только из существующих в БД."""
        hierarchy_context = self._build_hierarchy_context(topics_structure)
        
        prompt = self._build_classification_prompt(user_prompt, hierarchy_context)
        
        response = await self._chat_completion(
            system_prompt="Ты — строгий классификатор. Отвечаешь только валидным JSON без разметки markdown.",
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=500
        )
        
        topics = self._parse_classification_response(response)
        
        # Пост-валидация: отбрасываем темы, которых нет в БД
        validated = []
        for item in topics:
            name = item.get("name")
            if name and name in topics_structure:
                sections = item.get("sections", [])
                # Фильтруем разделы: оставляем только те, что есть в БД
                valid_sections = [s for s in sections if s in topics_structure[name]] if sections else []
                validated.append({"name": name, "sections": valid_sections})
            else:
                logger.warning("classify_topics: AI вернул тему '%s', которой нет в БД — отбрасываем", name)
        
        if validated:
            return validated
        
        # Fallback: если все темы отброшены, ищем по совпадению ключевых слов в названиях
        prompt_lower = user_prompt.lower()
        fallback = []
        for topic_name in topics_structure:
            if any(word in prompt_lower for word in topic_name.lower().split()):
                fallback.append({"name": topic_name, "sections": []})
        if fallback:
            logger.info("classify_topics: fallback по ключевым словам: %s", [t["name"] for t in fallback])
            return fallback
        
        return []
    
    async def select_tasks(self, user_prompt: str, available_tasks: List[Dict], task_count: int, 
                     difficulty_text: str, topics_count: int, topic_stats: Dict[str, int]) -> List[int]:
        """Выбрать лучшие задания из доступных"""
        prompt = self._build_selection_prompt(user_prompt, available_tasks, task_count, 
                                              difficulty_text, topics_count, topic_stats)
        
        response = await self._chat_completion(
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
       return f"""Ты — ИИ-репетитор по математике. Объясняешь теорию, отвечаешь на вопросы, решаешь задачи.

=== ФОРМУЛЫ (ЖЁСТКО) ===
- Строчные: $x^2 + 2x + 1 = 0$
- Вынесенные (центр): $$\\frac{{{{a}}}}{{{{b}}}}$$
- ЗАПРЕЩЕНО: \\(...\\), \\[...\\]

=== ТЕКСТ ===
Без маркеров (*, -). Абзацами. Для шагов можно "1. 2. 3."

=== КАРТИНКИ ===
Если есть в контексте: ![описание](url)

=== GeoGebra (только для визуализации) ===

Генерируй ТОЛЬКО такой JSX:
<GeoGebra setup={{`команда1
команда2`}} height="ЧИСЛО" />

РАЗРЕШЁННЫЕ КОМАНДЫ В setup (строго по одной на строку):

// Настройки вида
perspective: T          // "T"=3D, "G"=графика+алгебра
view: -5,5,-5,5         // xMin,xMax,yMin,yMax
view: -5,5,-5,5,grid,axes  // с сеткой и осями
view: -5,5,-5,5,-2,2    // 3D: +zMin,zMax

// Объекты (стандартный синтаксис GeoGebra)
A = (2, 3)
B = (5, -1)
c = Circle(A, 4)
f(x) = x^2 + 2x
l: y = 2x + 1
v = Vector(A, B)
poly = Polygon(A, B, C)
s = Sphere(A, 3)
plane: z = 0

// Настройки объектов (применяются ПОСЛЕ создания)
show: A, B, c, grid
hide: C, axes
color: A, #ff0000
size: A, 5
label: A, "Точка A"
animate: A, true, 5
animate: A, false

ПРИМЕР 2D:
<GeoGebra setup={{`f(x) = x^2
A = (1, f(1))
l: y = 2x - 1
color: f, #4287f5
color: l, #ff0000
show: f, l, A, grid, axes
view: -3, 3, -1, 6
label: A, "A"`}} height="400" />

ПРИМЕР 3D (первая команда — perspective: T):
<GeoGebra setup={{`perspective: T
f(x,y) = sin(x)*cos(y)
view: -5,5,-5,5,-2,2`}} height="500" />

ПРАВИЛА:
- Команды ТОЛЬКО из списка выше
- Для 3D первая команда ВСЕГДА perspective: T
- view подбирай осмысленно
- height: 300, 400 или 500
- НИКАКИХ api.*, JS, комментариев внутри setup

=== КОНТЕКСТ ===
Тема: {topic_name or '—'}
Раздел: {section_name or '—'}
Материал:
{theory_context}

=== ВОПРОС ===
{question}

=== ЛОГИКА ===
1. Вопрос НЕ по теме → направь к материалу
2. Просят РЕШИТЬ → пошагово с объяснением
3. Просто ВОПРОС → объясни "почему", с примерами. Нужна визуализация → добавь GeoGebra
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