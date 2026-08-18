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
        
        validated = []
        for item in topics:
            name = item.get("name")
            if name and name in topics_structure:
                sections = item.get("sections", [])
                valid_sections = [s for s in sections if s in topics_structure[name]] if sections else []
                validated.append({"name": name, "sections": valid_sections})
            else:
                logger.warning("classify_topics: AI вернул тему '%s', которой нет в БД — отбрасываем", name)
        
        if validated:
            return validated
        
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

    # ── GeoGebra instruction (shared across hint/solution/theory) ──

    GEOGEBRA_INSTRUCTIONS = """
=== GeoGebra (только для визуализации) ===

Генерируй ТОЛЬКО такой JSX:
<GeoGebra setup={`команда1
команда2`} height="ЧИСЛО" />

РАЗРЕШЁННЫЕ КОМАНДЫ В setup (строго по одной на строку):

// Настройки вида и осей
SetPerspective("T")          // "T"=3D, "2"=плоскость XY, "G"=графика+алгебра
CenterView((0,0))            // центр вида 2D
CenterView((0,0,0))          // центр вида 3D
ZoomIn(1)                    // масштаб (1=нормальный, 2=увеличенный)
ZoomIn(2)
ShowAxes(true)               // показать/скрыть оси
ShowAxes(false)
ShowGrid(true)               // показать/скрыть сетку
ShowGrid(false)
AxesVisible(false, false)    // скрыть обе оси

// Объекты
A = (2, 3)                   // точка 2D
B = (5, -1)
O = (0,0,0)                  // точка 3D
c = Circle((0,0), 3)         // окружность (центр, радиус)
s = Sphere((0,0,0), 2)       // сфера 3D (центр, радиус)
f(x) = x^2 + 2x              // функция
g(x) = sin(x)
h(x) = tan(x)                // тангенс (в GeoGebra: tan)
l: y = 2x + 1                // прямая
Line((0,0), (1,1))           // прямая через две точки
Segment(A, B)                 // отрезок
Vector(A, B)                  // вектор
Angle((1,0), (0,0), P)       // угол между точками (вершина в центре)
Intersect(c, l)              // пересечение объектов
Polygon(A, B, C)             // многоугольник
p = Slider(0, 360, 1)        // слайдер (min, max, шаг)
Text("текст", (x,y))          // текст на координатах
Point(Segment)               // точка на отрезке (для 3D слайдера)

// Настройки объектов (применяются ПОСЛЕ объявления)
SetColor(A, "#ff0000")        // цвет объекта
SetCaption(A, "Точка A")      // подпись объекта
ShowLabel(A, true)            // показывать подпись
SetPointSize(A, 5)            // размер точки
SetLineThickness(OA, 3)       // толщина линии
SetFilling(s, 0.3)            // прозрачность заливки (0.0-1.0)

ПРИМЕР 3D СЛАЙДЕРА (сфера с сечением, управление расстоянием d):
<GeoGebra setup={`SetPerspective("T")
CenterView((0,0,0))
ZoomIn(1)
ShowAxes(false)
ShowGrid(false)
R = 3
s = Sphere((0,0,0), R)
SetColor(s, "#38bdf8")
SetFilling(s, 0.12)
H_min = (-5, 0, 0)
H_max = (-5, R, 0)
SliderAxis = Segment(H_min, H_max)
SetColor(SliderAxis, "#9ca3af")
SetLineThickness(SliderAxis, 3)
CapMin = Segment((-5.2, 0, 0), (-4.8, 0, 0))
CapMax = Segment((-5.2, R, 0), (-4.8, R, 0))
SetColor(CapMin, "#9ca3af")
SetColor(CapMax, "#9ca3af")
SetLineThickness(CapMin, 3)
SetLineThickness(CapMax, 3)
H = Point(SliderAxis)
SetColor(H, "#ef4444")
SetPointSize(H, 7)
d = y(H)
TextD = Text("d = " + d, (-5.5, y(H), 0.3))
SetColor(TextD, "#ef4444")
plane = Plane((d, 0, 0), (d, 1, 0), (d, 1, 5))
SetColor(plane, "#fbbf24")
SetFilling(plane, 0.3)
section = Intersect(s, plane)
SetColor(section, "#ef4444")
SetLineThickness(section, 5)
SetFilling(section, 0.4)
O = (0,0,0)
SetColor(O, "#1e293b")
SetPointSize(O, 5)
SetCaption(O, "O")
ShowLabel(O, true)
A = (d, 0, sqrt(R^2 - d^2))
SetColor(A, "#ef4444")
SetPointSize(A, 4)
SetCaption(A, "A")
ShowLabel(A, true)
OA = Segment(O, A)
SetColor(OA, "#22c55e")
SetLineThickness(OA, 3)
SetCaption(OA, "R")
ShowLabel(OA, true)
OH = Segment(O, (d, 0, 0))
SetColor(OH, "#8b5cf6")
SetLineThickness(OH, 3)
SetCaption(OH, "d")
ShowLabel(OH, true)
HA = Segment((d, 0, 0), A)
SetColor(HA, "#f59e0b")
SetLineThickness(HA, 3)
SetCaption(HA, "r")
ShowLabel(HA, true)`} height="450" />

ПРАВИЛА:
- Команды ТОЛЬКО из списка выше
- Для 3D первая команда ВСЕГДА SetPerspective("T")
- Для 2D: SetPerspective("2")
- height: 300, 400, 450 или 500
- НИКАКИХ api.*, JS, комментариев внутри setup
- НИКАКИХ русских символов в именах переменных
- Цвета в HEX: "#3b82f6", "#ef4444", "#22c55e" и т.д.

// 3D СЛАЙДЕР (если нужен интерактив в 3D):
// 1. Создай отрезок-шкалу ВНЕ объекта: SliderAxis = Segment(StartPoint, EndPoint)
// 2. Добавь ограничители на концах: CapMin = Segment(...), CapMax = Segment(...)
// 3. Точка-ползунок: H = Point(SliderAxis)
// 4. Бери нужную координату: d = y(H) или d = x(H) или d = z(H)
// 5. Используй d в вычислениях других объектов
// 6. Текст с текущим значением: TextD = Text("d = " + d, (x, y, z))
// ВАЖНО: слайдер размещай ВНЕ основного объекта (например, слева при x = -5)
// ВАЖНО: d должно быть в диапазоне [0, R] или [min, max] без отрицательных значений
"""

    # ── Prompt builders ──

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

{self.GEOGEBRA_INSTRUCTIONS}

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
    
    # ── Helpers ──

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

1. **Анализ запроса:** внимательно прочитай запрос студента, определи математические темы.

2. **Правила выбора тем:**
   - "отработка уравнений" → ВСЕ темы из "Уравнения и неравенства"
   - "дроби" → тема "Числа и вычисления" с разделами про дроби
   - "геометрия" → тема "Геометрия" со всеми разделами
   - "стереометрия" → тема "Геометрия" с разделами по стереометрии

3. **Правила выбора разделов:** точный запрос → конкретный раздел; общий → все разделы.

4. **Если точного совпадения нет:** выбери максимально близкие темы. Лучше БОЛЬШЕ.

=== ВАЖНО ===
- sections можно оставить пустым массивом [], если нужно взять ВСЕ разделы темы
- Если тема не указана в структуре БД, НЕ придумывай её

Верни ТОЛЬКО JSON:
{{"topics": [{{"name": "Название темы 1", "sections": ["Раздел 1"]}}, {{"name": "Название темы 2", "sections": []}}]}}
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
1. Из предложенных заданий выбери РОВНО {task_count} НАИБОЛЕЕ ПОДХОДЯЩИХ
2. Если тем несколько — распредели задания МЕЖДУ ВСЕМИ темами
3. Внутри каждой темы выбирай задания с РАЗНОЙ сложностью
4. Верни ТОЛЬКО JSON: {{"task_ids": [45, 67, 123, ...]}}
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
""" + self.GEOGEBRA_INSTRUCTIONS
    
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
9. Используй картинки по смыслу, которые есть в контексте. Просто вставляй их, как в обычный маркдаун

=== ФОРМАТ ОТВЕТА (после "=== ОТВЕТ ===") ===
Для ОТКРЫТОГО вопроса (is_open_answer=True):
- Одно число: 5 или -3.14
- Несколько чисел через запятую: 1,2,3 или x=2,x=-1
- Никаких пробелов вокруг запятых

Для ЗАКРЫТОГО вопроса (выбор варианта, is_open_answer=False):
- Один вариант: номер (например: 2)
- Несколько вариантов: номера через запятую БЕЗ пробелов (например: 1,3)
- Соответствие (А1Б3В2): последовательность пар БУКВА+ЦИФРА слитно

ЗАПОМНИ: используй ТОЛЬКО $...$ и $$...$$, НИКОГДА не используй \\( ... \\) или \\[ ... \\]
""" + self.GEOGEBRA_INSTRUCTIONS