# Инструкция для фронта: AI-чертежи GeoGebra

Чертежи приходят в **подсказке** и **решении**. Их может быть несколько, и они стоят **в любом месте текста**, не только в конце.

Теория (`POST /student/theory/ask-ai`) пока **без** этого формата.

---

## Эндпоинты

```
POST /student/tasks/{taskId}/hint
POST /student/tasks/{taskId}/ai-solve
Authorization: Bearer <student_token>
```

Тело запроса пустое.

---

## Ломающее изменение

Раньше `geogebra` был **одним объектом** (или `null`), апплет рисовали после текста.

Теперь:

| Поле | Было | Стало |
|------|------|--------|
| `geogebra` | `object \| null` | `GeoGebraFigure[] \| null` |
| место в UI | всегда в конце | плейсхолдер `{{geogebra:N}}` внутри markdown |

Если `geogebra === null` или `[]` — чертежей нет, текст как обычно (KaTeX / markdown).

---

## Ответ hint

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
        "c = Circle((0,0), 2)"
      ],
      "setup": "SetPerspective(\"G\")\nShowAxes(true)\nc = Circle((0,0), 2)"
    },
    {
      "id": 1,
      "app": "graphing",
      "height": "450",
      "commands": ["SetPerspective(\"G\")", "f(x) = x^2"],
      "setup": "SetPerspective(\"G\")\nf(x) = x^2"
    }
  ]
}
```

Решение (`ai-solve`) — то же поле `geogebra`, плейсхолдеры внутри `ai_solution`.

---

## Почему апплет пустой

Старый код ломается на трёх вещах сразу:

1. `geogebra` теперь **массив**. `data.geogebra.setup` и `data.geogebra.commands` — `undefined`. Нужна фигура `data.geogebra[i]`.
2. Скрипт **не** `https://www.geogebra.org/apps/embed` (это iframe чужого материала). Нужен `https://www.geogebra.org/apps/deployggb.js` и `new GGBApplet(...)`.
3. Для стереометрии `appName` должен быть `"3d"`. Если всегда `"geometry"`, `Prism` / `Pyramid` / `Cylinder` не рисуются.

Катеx/markdown гоняйте **только по текстовым кускам** после split. Если прогнать весь `hint` целиком, плейсхолдер `{{geogebra:0}}` пропадёт или останется текстом.

---

## Как рендерить

Плейсхолдер **точно** такой (без пробелов):

```text
{{geogebra:0}}
{{geogebra:1}}
```

```js
const GEOGEBRA_RE = /\{\{geogebra:(\d+)\}\}/;
```

`split` с группой даёт: текст, id, текст, id, текст.

```tsx
function renderWithGeoGebra(text: string, figures: GeoGebraFigure[] | null) {
  const byId = new Map((figures ?? []).map((f) => [f.id, f]));
  const parts = text.split(/\{\{geogebra:(\d+)\}\}/);

  return parts.map((part, i) => {
    if (i % 2 === 0) {
      return <MarkdownKatex key={i} text={part} />;
    }
    const figure = byId.get(Number(part));
    if (!figure) return null;
    return <GeoGebraEmbed key={`ggb-${figure.id}`} figure={figure} />;
  });
}
```

Не парсите ` ```geogebra ` и JSX `<GeoGebra setup=...>`. Бэк уже вырезал блоки.

---

## Поля фигуры

```ts
type GeoGebraFigure = {
  id: number;          // совпадает с N в {{geogebra:N}}
  app: "geometry" | "graphing" | "3d";
  height: "300" | "400" | "450" | "500"; // строка
  commands: string[];  // исполнять по порядку
  setup: string;       // те же команды через \n
};
```

В апплет передавайте **`figure.commands`**. `setup.split("\n")` — только запасной вариант.

`figure.app` — это уже GeoGebra `appName`. Не хардкодьте `"geometry"`.

---

## Рабочий embed

Один раз на страницу подключите скрипт (в `index.html` или динамически):

```html
<script src="https://www.geogebra.org/apps/deployggb.js"></script>
```

Команды выполняйте **только в `appletOnLoad`**. Если вызвать `evalCommand` до готовности апплета — чертёж пустой.

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

export function GeoGebraEmbed({ figure }: { figure: GeoGebraFigure }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const uid = useId().replace(/:/g, "");
  const height = Number(figure.height) || 400;
  const commands = (figure.commands?.length
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
          for (const cmd of commands) api.evalCommand(cmd);
        },
      },
      true
    );
    applet.inject(el);

    return () => {
      el.innerHTML = "";
    };
  }, [figure.id, figure.app, figure.setup, height, commands.join("\n"), uid]);

  return <div ref={boxRef} style={{ width: "100%", height }} />;
}
```

Каждый `{{geogebra:N}}` — **отдельный** апплет со своим `id`. Не склеивайте команды разных фигур. Не используйте глобальный `ggbApplet`, если на странице несколько чертежей.

---

## Кадры, которых ждать не надо

- В тексте больше не будет `<GeoGebra setup={\`...\`} />`.
- Не будет ограды ` ```geogebra `.
- `geogebra` больше не объект `{ setup, height }` без `id`.

Старый код `geogebra && <Embed geogebra={geogebra} />` в конце карточки не работает: `geogebra` — массив.

---

## Краткий чеклист

- [ ] скрипт `deployggb.js`, не `apps/embed`
- [ ] `geogebra` — массив, в embed идёт **один** элемент `figure`
- [ ] сплит `hint` / `ai_solution` по `{{geogebra:N}}` **до** markdown
- [ ] `appName={figure.app}` (`3d` для стереометрии)
- [ ] `evalCommand` внутри `appletOnLoad`
- [ ] KaTeX только на текстовых кусках
