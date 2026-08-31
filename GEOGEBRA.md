# 📐 GeoGebra — Документация

GeoGebra используется **только для визуализации** математических построений. Компонент рендерит интерактивный апплет по набору команд GeoGebra Script.

---

## 🧩 Формат компонента

Генерируй ТОЛЬКО такой JSX:

```jsx
<GeoGebra setup={`команда1
команда2`} height="ЧИСЛО" />
```

### Допустимые значения `height`

| Значение |
|----------|
| `300`    |
| `400`    |
| `450`    |
| `500`    |

---

## ⚙️ Разрешённые команды в `setup`

Команды задаются **строго по одной на строку**. Разрешены только команды из списков ниже.

### 🎛 Настройки вида и осей

| Команда | Описание |
|---------|----------|
| `SetPerspective("T")` | Перспектива 3D |
| `SetPerspective("2")` | Перспектива: плоскость XY |
| `SetPerspective("G")` | Графика + алгебра |
| `CenterView((0,0))` | Центр вида 2D |
| `CenterView((0,0,0))` | Центр вида 3D |
| `ZoomIn(1)` | Масштаб (1 = нормальный) |
| `ZoomIn(2)` | Увеличенный масштаб |
| `ShowAxes(true)` | Показать оси |
| `ShowAxes(false)` | Скрыть оси |
| `ShowGrid(true)` | Показать сетку |
| `ShowGrid(false)` | Скрыть сетку |
| `AxesVisible(false, false)` | Скрыть обе оси |

### 📦 Объекты

| Команда | Описание |
|---------|----------|
| `A = (2, 3)` | Точка 2D |
| `B = (5, -1)` | Точка 2D |
| `O = (0,0,0)` | Точка 3D |
| `c = Circle((0,0), 3)` | Окружность (центр, радиус) |
| `s = Sphere((0,0,0), 2)` | Сфера 3D (центр, радиус) |
| `f(x) = x^2 + 2x` | Функция |
| `g(x) = sin(x)` | Функция (синус) |
| `h(x) = tan(x)` | Тангенс (в GeoGebra: `tan`) |
| `l: y = 2x + 1` | Прямая |
| `Line((0,0), (1,1))` | Прямая через две точки |
| `Segment(A, B)` | Отрезок |
| `Vector(A, B)` | Вектор |
| `Angle((1,0), (0,0), P)` | Угол между точками (вершина в центре) |
| `Intersect(c, l)` | Пересечение объектов |
| `Polygon(A, B, C)` | Многоугольник |
| `p = Slider(0, 360, 1)` | Слайдер (min, max, шаг) |
| `Text("текст", (x,y))` | Текст на координатах |
| `Point(Segment)` | Точка на отрезке (для 3D слайдера) |
| `plane = Plane((x1,y1,z1), (x2,y2,z2), (x3,y3,z3))` | Плоскость 3D через три точки |

### ➗ Математические операции и присваивания (используются внутри команд)

| Операция / Конструкция | Описание |
|------------------------|----------|
| `R = 3` | Присваивание значения переменной |
| `s = Sphere((0,0,0), R)` | Переменная в качестве параметра |
| `d = y(H)` | Взять координату точки (`x(H)`, `y(H)` или `z(H)`) |
| `sqrt(R^2 - d^2)` | Квадратный корень |
| `R^2` | Возведение в степень |
| `"d = " + d` | Конкатенация строк в `Text(...)` |

### 🎨 Настройки объектов (применяются ПОСЛЕ объявления)

| Команда | Описание |
|---------|----------|
| `SetColor(A, "#ff0000")` | Цвет объекта |
| `SetCaption(A, "Точка A")` | Подпись объекта |
| `ShowLabel(A, true)` | Показывать подпись |
| `SetPointSize(A, 5)` | Размер точки |
| `SetLineThickness(OA, 3)` | Толщина линии |
| `SetFilling(s, 0.3)` | Прозрачность заливки (0.0–1.0) |

---

## ✅ Правила

- Команды **ТОЛЬКО** из списка выше.
- Для 3D первая команда **ВСЕГДА** `SetPerspective("T")`.
- Для 2D — `SetPerspective("2")`.
- `height`: только `300`, `400`, `450` или `500`.
- **НИКАКИХ** `api.*`, JS-кода или комментариев внутри `setup`.
- **НИКАКИХ** русских символов в именах переменных.
- Цвета в HEX-формате: `"#3b82f6"`, `"#ef4444"`, `"#22c55e"` и т.д.

---

## 🎯 Пример: 3D слайдер

Сфера с сечением, управление расстоянием `d`:

```jsx
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
```

---

## 📐 Пример 2D: треугольник в окружности

```jsx
<GeoGebra setup={`SetPerspective("2")
ShowAxes(true)
ShowGrid(true)
O = (0, 0)
SetColor(O, "#1e293b")
SetPointSize(O, 4)
SetCaption(O, "O")
ShowLabel(O, true)
c = Circle(O, 4)
SetColor(c, "#3b82f6")
SetLineThickness(c, 2)
A = (4, 0)
B = (-2, 3.46)
C = (-2, -3.46)
Polygon(A, B, C)
SetColor(Polygon(A, B, C), "#22c55e")
SetFilling(Polygon(A, B, C), 0.15)
SetPointSize(A, 4)
SetPointSize(B, 4)
SetPointSize(C, 4)
SetColor(A, "#ef4444")
SetColor(B, "#f59e0b")
SetColor(C, "#8b5cf6")
SetCaption(A, "A")
SetCaption(B, "B")
SetCaption(C, "C")
ShowLabel(A, true)
ShowLabel(B, true)
ShowLabel(C, true)`} height="400" />
```

---

## 📐 Пример 3D: сфера с осями

```jsx
<GeoGebra setup={`SetPerspective("T")
CenterView((0,0,0))
ZoomIn(1)
ShowAxes(true)
ShowGrid(false)
O = (0,0,0)
SetColor(O, "#1e293b")
SetPointSize(O, 5)
SetCaption(O, "O")
ShowLabel(O, true)
s = Sphere(O, 2)
SetColor(s, "#3b82f6")
SetFilling(s, 0.15)
A = (2, 0, 0)
B = (0, 2, 0)
C = (0, 0, 2)
SetColor(A, "#ef4444")
SetColor(B, "#22c55e")
SetColor(C, "#38bdf8")
SetPointSize(A, 5)
SetPointSize(B, 5)
SetPointSize(C, 5)
SetCaption(A, "A")
SetCaption(B, "B")
SetCaption(C, "C")
ShowLabel(A, true)
ShowLabel(B, true)
ShowLabel(C, true)
OA = Segment(O, A)
OB = Segment(O, B)
OC = Segment(O, C)
SetColor(OA, "#ef4444")
SetColor(OB, "#22c55e")
SetColor(OC, "#38bdf8")
SetLineThickness(OA, 3)
SetLineThickness(OB, 3)
SetLineThickness(OC, 3)`} height="450" />
```

---

## 🕹 Как сделать интерактивный слайдер в 3D

1. Создай отрезок-шкалу **ВНЕ** объекта:
   ```
   SliderAxis = Segment(StartPoint, EndPoint)
   ```
2. Добавь ограничители на концах:
   ```
   CapMin = Segment(...)
   CapMax = Segment(...)
   ```
3. Точка-ползунок:
   ```
   H = Point(SliderAxis)
   ```
4. Бери нужную координату:
   ```
   d = y(H)   // или x(H), или z(H)
   ```
5. Используй `d` в вычислениях других объектов.
6. Текст с текущим значением:
   ```
   TextD = Text("d = " + d, (x, y, z))
   ```

### ⚠️ Важно для слайдера

- Слайдер размещай **ВНЕ** основного объекта (например, слева при `x = -5`).
- `d` должно быть в диапазоне `[0, R]` или `[min, max]` **без отрицательных значений**.

---

## 🔗 Примечание по рендерингу

В фронтенде апплет исполняет компонент `GeoGebraEmbed`, который принимает проп:

```jsx
<GeoGebraEmbed geogebra={{ commands: ["A=(0,0)", "B=(4,0)", "Polygon(A,B,C)"] }} />
```

Команды из `setup` передаются как массив строк в `geogebra.commands` и выполняются последовательно через JavaScript API GeoGebra (`https://www.geogebra.org/apps/embed`). Параметры апплета: `appName: 'geometry'`, `language: 'ru'`, отключены меню и правое поле ввода алгебры, включены панель инструментов и кнопка сброса.