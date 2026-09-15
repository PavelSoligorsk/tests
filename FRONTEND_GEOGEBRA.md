# GeoGebra на фронте: подсказки и решения

Чертежи приходят вместе с AI-подсказкой и AI-решением. Их может быть **несколько**, и каждый стоит **внутри текста** на месте плейсхолдера `{{geogebra:N}}` — не обязательно в конце.

Бэкенд уже вырезал блоки из ответа модели и собрал команды. Фронт только:

1. режет текст по плейсхолдерам;
2. для каждого `{{geogebra:N}}` вставляет апплет с `geogebra[N]`;
3. текстовые куски гоняет через markdown + KaTeX.

Теория (`POST /student/theory/ask-ai`) пока **без** GeoGebra.

---

## Эндпоинты

```http
POST /student/tasks/{taskId}/hint
POST /student/tasks/{taskId}/ai-solve
Authorization: Bearer <student_token>
```

Тело запроса пустое. Ответ — JSON.

| Эндпоинт | Текст с плейсхолдерами | Чертежи |
|----------|------------------------|---------|
| `/hint` | `hint` | `geogebra` |
| `/ai-solve` | `ai_solution` | `geogebra` |

`geogebra` — `GeoGebraFigure[] | null`.  
Если `null` или `[]` — чертежей нет, рендери текст как обычно.

---

## Типы

```ts
type GeoGebraApp = "geometry" | "graphing" | "3d";

type GeoGebraFigure = {
  /** Совпадает с N в {{geogebra:N}} */
  id: number;
  /** GeoGebra appName — не хардкодить "geometry" */
  app: GeoGebraApp;
  /** Строка: "300" | "400" | "450" | "500" */
  height: string;
  /** Команды по порядку — основной источник */
  commands: string[];
  /** Те же команды через \n (запасной вариант) */
  setup: string;
};
```

В апплет передавайте **`figure.commands`**.  
`setup.split("\n")` — только если `commands` пустой.

---

## Пример ответа `/hint`

```json
{
  "task_id": 2,
  "hint": "Сначала окружность:\n\n{{geogebra:0}}\n\nТеперь график:\n\n{{geogebra:1}}\n\nРадиус $R = 2$.",
  "context": {
    "task_class": "10",
    "topic_number": "1",
    "difficulty": 2,
    "topic_mastery_percent": 40.0
  },
  "geogebra": [
    {
      "id": 0,
      "app": "geometry",
      "height": "400",
      "commands": [
        "SetPerspective(\"G\")",
        "ShowAxes(true)",
        "ShowGrid(true)",
        "c = Circle((0,0), 2)",
        "ZoomIn(-3, -3, 3, 3)"
      ],
      "setup": "SetPerspective(\"G\")\nShowAxes(true)\nShowGrid(true)\nc = Circle((0,0), 2)\nZoomIn(-3, -3, 3, 3)"
    },
    {
      "id": 1,
      "app": "graphing",
      "height": "450",
      "commands": [
        "SetPerspective(\"G\")",
        "f(x) = x^2",
        "ZoomIn(-8, -6, 8, 6)"
      ],
      "setup": "SetPerspective(\"G\")\nf(x) = x^2\nZoomIn(-8, -6, 8, 6)"
    }
  ]
}
```

### Пример `/ai-solve` (фрагмент)

```json
{
  "task_id": 2,
  "success": true,
  "verified": true,
  "message": "Решение найдено и проверено. Ответ совпадает.",
  "ai_solution": "Построим фигуру:\n\n{{geogebra:0}}\n\nОбъём равен $60$.\n\n=== ОТВЕТ ===\n60",
  "ai_answer": "60",
  "correct_answer": "60",
  "context": { "...": "..." },
  "geogebra": [
    {
      "id": 0,
      "app": "3d",
      "height": "400",
      "commands": ["SetPerspective(\"T\")", "..."],
      "setup": "..."
    }
  ]
}
```

Плейсхолдер **точно** такой (без пробелов):

```text
{{geogebra:0}}
{{geogebra:1}}
```

---

## Как рендерить текст

1. `split` текста по `{{geogebra:(\d+)}}` **до** markdown/KaTeX.
2. Чётные куски — markdown + KaTeX.
3. Нечётные — id фигуры → `<GeoGebraEmbed figure={...} />`.

```tsx
function renderWithGeoGebra(
  text: string,
  figures: GeoGebraFigure[] | null | undefined
) {
  const byId = new Map((figures ?? []).map((f) => [f.id, f]));
  const parts = text.split(/\{\{geogebra:(\d+)\}\}/);

  return parts.map((part, i) => {
    if (i % 2 === 0) {
      // текст: markdown + KaTeX
      return <MarkdownKatex key={i} text={part} />;
    }
    const figure = byId.get(Number(part));
    if (!figure) return null;
    return <GeoGebraEmbed key={`ggb-${figure.id}`} figure={figure} />;
  });
}

// hint
renderWithGeoGebra(data.hint, data.geogebra);

// solution
renderWithGeoGebra(data.ai_solution, data.geogebra);
```

**Не** парсите на фронте:

- ограды ` ```geogebra `
- JSX `<GeoGebra setup=... />`

Бэк уже всё вырезал.

**Не** прогоняйте весь `hint` / `ai_solution` через markdown целиком — плейсхолдер сломается или останется сырым текстом.

---

## Скрипт GeoGebra

Один раз на страницу / в `index.html`:

```html
<script src="https://www.geogebra.org/apps/deployggb.js"></script>
```

| Нужно | Не нужно |
|-------|----------|
| `https://www.geogebra.org/apps/deployggb.js` | `https://www.geogebra.org/apps/embed` |

`apps/embed` — чужой iframe, **не** API для своих команд.

---

## Компонент апплета (React)

Команды выполняйте **только в `appletOnLoad`**. До загрузки апплета `evalCommand` даёт пустой чертёж.

```tsx
import { useEffect, useId, useRef } from "react";

declare global {
  interface Window {
    GGBApplet: new (
      params: Record<string, unknown>,
      html5: boolean
    ) => { inject: (el: string | HTMLElement) => void };
  }
}

type GeoGebraFigure = {
  id: number;
  app: "geometry" | "graphing" | "3d";
  height: string;
  commands: string[];
  setup: string;
};

export function GeoGebraEmbed({ figure }: { figure: GeoGebraFigure }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const uid = useId().replace(/:/g, "");
  const height = Number(figure.height) || 400;
  const commands = (
    figure.commands?.length
      ? figure.commands
      : (figure.setup || "").split("\n")
  ).filter((c) => c.trim());

  useEffect(() => {
    const el = boxRef.current;
    if (!el || typeof window.GGBApplet !== "function") return;

    el.innerHTML = "";
    const applet = new window.GGBApplet(
      {
        appName: figure.app, // geometry | graphing | 3d
        id: `ggb${uid}`,
        width: Math.max(el.clientWidth || 640, 320),
        height,
        language: "ru",
        showMenuBar: false,
        showAlgebraInput: false,
        showToolBar: true,
        showResetIcon: true,
        enable3d: figure.app === "3d",
        appletOnLoad(api: { evalCommand: (cmd: string) => boolean }) {
          for (const cmd of commands) {
            api.evalCommand(cmd);
          }
        },
      },
      true
    );
    applet.inject(el);

    return () => {
      el.innerHTML = "";
    };
  }, [figure.id, figure.app, height, commands.join("\n"), uid]);

  return (
    <div
      ref={boxRef}
      style={{ width: "100%", height, margin: "12px 0" }}
    />
  );
}
```

### Важно

- Каждый `{{geogebra:N}}` — **отдельный** апплет со своим `id` (`ggb…`).
- Не склеивайте `commands` разных фигур.
- Не используйте глобальный `ggbApplet`, если на экране несколько чертежей.
- Для стереометрии `appName` должен быть `"3d"`. Если всегда `"geometry"`, пирамида / цилиндр / призма не появятся.

---

## Почему апплет пустой (частые ошибки)

1. **`geogebra` — массив.** Старый код `data.geogebra.setup` / `data.geogebra.commands` даёт `undefined`. Нужно `data.geogebra[i]` или фигура по `id`.
2. Подключён **`apps/embed`** вместо **`deployggb.js`**.
3. Всегда `appName: "geometry"` при `figure.app === "3d"`.
4. `evalCommand` вызвали **до** `appletOnLoad`.
5. Markdown прогнали по всему тексту **до** split по плейсхолдерам.

---

## Чего в ответе больше не будет

- объекта `geogebra: { setup, height }` без `id` и без массива;
- сырого JSX `<GeoGebra setup={\`...\`} />` в тексте;
- ограды ` ```geogebra ` в `hint` / `ai_solution`.

Старый паттерн «в конце карточки `geogebra && <Embed geogebra={geogebra} />`» не работает: нужен split текста.

---

## Чеклист

- [ ] скрипт `deployggb.js`, не `apps/embed`
- [ ] `geogebra` обрабатывается как **массив**
- [ ] split `hint` / `ai_solution` по `{{geogebra:N}}` **до** markdown/KaTeX
- [ ] в embed идёт **одна** фигура `figure` с `id === N`
- [ ] `appName={figure.app}` (`"3d"` для стереометрии)
- [ ] команды из `figure.commands` внутри `appletOnLoad`
- [ ] KaTeX только на текстовых кусках
- [ ] несколько чертежей на странице — разные `id` апплетов
