import re
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from pathlib import Path
from typing import List, Dict, Optional
import json

class RTParser:
    """Парсер для репетиционных тестов (РТ) с математикой"""
    
    def __init__(self):
        self.model_dict = create_model_dict()
        self.converter = PdfConverter(
            artifact_dict=self.model_dict,
            processor_config={
                "extract_equations": True,   # извлекаем LaTeX
                "ocr_language": "rus",       # русский + формулы
                "ocr_all_pages": False,
            }
        )
    
    def pdf_to_markdown(self, pdf_path: str) -> str:
        """Конвертируем PDF в Markdown с сохранением LaTeX"""
        print(f"📄 Конвертация {pdf_path}...")
        rendered = self.converter(pdf_path)
        return rendered.markdown
    
    def parse_tasks(self, markdown_text: str) -> List[Dict]:
        """Парсит задачи из текста"""
        tasks = []
        
        # Паттерн для поиска заданий (A4, A5, B1, B2 и т.д.)
        # В твоём документе задания начинаются с буквы и цифры в начале строки
        task_pattern = r'^([A-B]\d+)\.\s+(.+?)(?=^[A-B]\d+\.|\Z)'
        
        # Разбиваем по заданиям
        matches = re.finditer(task_pattern, markdown_text, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            task_id = match.group(1)
            content = match.group(2)
            
            task = {
                "id": task_id,
                "condition": "",
                "solution": "",
                "answer": "",
                "sources": []
            }
            
            # Извлекаем условие (до "Решение:" или "Комментарий")
            condition_match = re.search(r'^(.*?)(?:Решение:|Комментарий и решение)', content, re.DOTALL)
            if condition_match:
                task["condition"] = self._clean_text(condition_match.group(1))
            
            # Извлекаем решение
            solution_match = re.search(r'(?:Решение:|Комментарий и решение задания)(.*?)(?=Ответ:|Учебное издание|\*\*|$)', content, re.DOTALL)
            if solution_match:
                task["solution"] = self._clean_text(solution_match.group(1))
            
            # Извлекаем ответ (Ответ: X или Ответ: 1,3,5)
            answer_match = re.search(r'Ответ:\s*(.+?)(?=\n|$)', content)
            if answer_match:
                task["answer"] = self._clean_text(answer_match.group(1))
            
            # Извлекаем учебные источники
            sources_match = re.search(r'(?:Учебное издание|\*{0,2}Учебное издание\*{0,2})(.*?)(?=$|\n[А-Я])', content, re.DOTALL)
            if sources_match:
                sources_text = sources_match.group(1)
                # Ищем названия книг с годом
                book_matches = re.findall(r'([А-Я][^.]+\d{4}[^.]*\.)', sources_text)
                task["sources"] = [self._clean_text(b) for b in book_matches]
            
            tasks.append(task)
        
        return tasks
    
    def _clean_text(self, text: str) -> str:
        """Очистка текста от лишних символов"""
        # Удаляем спецсимволы Marker
        text = re.sub(r'•|♦|~', '', text)
        # Нормализуем пробелы
        text = re.sub(r'\s+', ' ', text)
        # Удаляем номера страниц в виде "Page X"
        text = re.sub(r'===== Page \d+ =====', '', text)
        # Сохраняем LaTeX формулы
        return text.strip()
    
    def extract_all_math(self, tasks: List[Dict]) -> Dict:
        """Извлекает все математические формулы из задач"""
        math_by_task = {}
        
        for task in tasks:
            formulas = {
                "inline": [],
                "display": [],
                "inline_raw": [],
                "display_raw": []
            }
            
            full_text = task["condition"] + " " + task["solution"]
            
            # Ищем \( ... \) — inline формулы
            inline_matches = re.findall(r'\\\((.*?)\\\)', full_text)
            formulas["inline_raw"] = inline_matches
            formulas["inline"] = [f"${m}$" for m in inline_matches]
            
            # Ищем \[ ... \] — display формулы
            display_matches = re.findall(r'\\\[(.*?)\\\]', full_text, re.DOTALL)
            formulas["display_raw"] = display_matches
            formulas["display"] = [f"$${m}$$" for m in display_matches]
            
            # Также ищем классические $...$ и $$...$$
            dollar_inline = re.findall(r'\$([^\$]+?)\$', full_text)
            formulas["inline"].extend([f"${m}$" for m in dollar_inline])
            
            dollar_display = re.findall(r'\$\$([^\$]+?)\$\$', full_text, re.DOTALL)
            formulas["display"].extend([f"$${m}$$" for m in dollar_display])
            
            math_by_task[task["id"]] = formulas
        
        return math_by_task


# ============ ИСПОЛЬЗОВАНИЕ ============

def main():
    # Путь к твоему PDF
    pdf_file = "Рт 2024 Этап 1 в1.pdf"
    
    # Создаем парсер
    parser = RTParser()
    
    # 1. Конвертируем PDF в Markdown
    markdown_text = parser.pdf_to_markdown(pdf_file)
    
    # Сохраняем сырой Markdown (для отладки)
    with open("output_raw.md", "w", encoding="utf-8") as f:
        f.write(markdown_text)
    print("✅ Сырой Markdown сохранён в output_raw.md")
    
    # 2. Парсим задачи
    tasks = parser.parse_tasks(markdown_text)
    print(f"\n📊 Найдено задач: {len(tasks)}")
    
    # 3. Извлекаем математику
    math_by_task = parser.extract_all_math(tasks)
    
    # 4. Выводим результаты
    for task in tasks[:5]:  # первые 5 задач для примера
        print(f"\n{'='*60}")
        print(f"📌 Задание {task['id']}")
        print(f"{'='*60}")
        print(f"📖 Условие:\n{task['condition'][:300]}...")
        print(f"\n💡 Решение:\n{task['solution'][:300]}...")
        print(f"\n✅ Ответ: {task['answer']}")
        
        # Показываем формулы
        math = math_by_task[task["id"]]
        if math["inline"]:
            print(f"\n📐 Inline формулы ({len(math['inline'])}):")
            for f in math["inline"][:3]:
                print(f"   {f}")
        if math["display"]:
            print(f"\n📏 Display формулы ({len(math['display'])}):")
            for f in math["display"][:2]:
                print(f"   {f}")
    
    # 5. Сохраняем всё в JSON
    output = {
        "tasks": tasks,
        "math_by_task": math_by_task
    }
    
    with open("parsed_tasks.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n✅ Все данные сохранены в parsed_tasks.json")


if __name__ == "__main__":
    main()