# Инструкция для фронта: Доска

Документ доски хранит сервер. IndexedDB — мгновенный черновик в браузере: линия не ждёт сеть, на сервер уходит уже собранный JSON.

Доска не привязана к занятию и расписанию. Её создаёт учитель: даёт название и выбирает учеников или одну группу. Холст один. Его видят и правят учитель и те, кому доска назначена.

Живых курсоров нет. Один `PUT` заменяет документ целиком. Пока доска открыта, клиент держит поток `events`: сервер присылает только номер новой ревизии, и тогда клиент один раз делает `GET`. Опрашивать доску по таймеру не нужно.

Базовый URL — тот же, что у остального API. Авторизация — `Authorization: Bearer <token>`.

Поля доски в JSON — camelCase (`teacherId`, `groupId`, `studentIds`, `createdAt`).

---

## Документ

`GET` одной доски, создание и успешный `PUT` возвращают одно и то же:

```json
{
  "id": "6f1c2a40-7b1e-4d2a-9c33-0a1b2c3d4e5f",
  "title": "Дроби",
  "teacherId": 7,
  "groupId": null,
  "studentIds": [45, 46],
  "revision": 1,
  "createdAt": "2026-09-28T00:13:00.000Z",
  "updatedAt": "2026-09-28T00:13:00.000Z",
  "camera": { "x": 0, "y": 0, "zoom": 1 },
  "objects": []
}
```

Если доска на группу, `groupId` — id группы, `studentIds` — пустой массив. Состав берётся из группы: ученик, которого добавили позже, увидит доску сам. Если доска на конкретных учеников, `groupId` равен `null`, а `studentIds` — их id.

`id` доски — UUID-строка. `teacherId`, `groupId` и элементы `studentIds` — числа.

`revision` — целое. Сервер увеличивает его на каждый успешный `PUT`. Клиент присылает ту ревизию, которую читал.

`camera` — сдвиг и масштаб мира доски. Координаты объектов — пиксели мира, не экрана.

На `PUT` сервер не меняет, кому доска принадлежит: `teacherId`, `groupId`, `studentIds`, `id`, `createdAt` остаются как в базе. Записываются `title`, `camera`, `objects`. В ответе `revision` на единицу больше, `updatedAt` — время сервера. После `200` локальную копию нужно заменить ответом: сервер мог дописать `ggbBase64` и свежий `src`.

Список досок приходит без `objects`:

```json
{
  "id": "6f1c2a40-7b1e-4d2a-9c33-0a1b2c3d4e5f",
  "title": "Дроби",
  "teacherId": 7,
  "groupId": null,
  "studentIds": [45, 46],
  "updatedAt": "2026-09-28T00:40:12.000Z",
  "objectCount": 4
}
```

---

## Объекты

Каждый элемент `objects` одной формы. Неизвестные ключи в `props` сервер сохраняет.

```json
{
  "id": "b7e1c2d0-1111-4222-8333-444455556666",
  "type": "sticky",
  "x": 120,
  "y": 80,
  "w": 200,
  "h": 160,
  "rotation": 0,
  "props": {}
}
```

`id` объекта — непустая строка. Координаты, размеры и `rotation` — конечные числа.

| `type` | Что лежит в `props` |
| --- | --- |
| `sticky` | `text`, `color` (`#fde68a` и другие), `fontSize` |
| `text` | `text`, `fontSize` |
| `shape` | `shape`: `rect` или `ellipse`, `fill`, `stroke` |
| `arrow` | `x1`, `y1`, `x2`, `y2` относительно рамки, `color`, `width` |
| `draw` | `points`: `[{ "x", "y" }]`, `color`, `width` |
| `image` | `fileId`, `src`, `name` |
| `geogebra` | `appName`: `geometry` или `graphing`, `ggbBase64`, `templateId` |

Лимит: до 200 объектов и до 8 МБ на документ. Иначе `PUT` отвечает `400`.

---

## Сохранение

IndexedDB пишется сразу. `PUT` — примерно раз в 700 мс тишины и при закрытии вкладки.

Тело `PUT` — тот же JSON, что вернул `GET`, с текущими `title`, `camera`, `objects` и `revision` последней успешной загрузки или сохранения.

```
PUT /student/boards/{id}
PUT /teacher/boards/{id}
Content-Type: application/json
Authorization: Bearer <token>
```

`200` — новый документ. Подставить его вместо локального, включая `revision`.

`409` — на сервере уже новее. Тело ответа — сам документ, без обёртки `detail`. Показать его и не сливать правки молча.

Остальные ошибки — `{ "detail": "текст" }`.

Учитель и назначенные ученики пишут в один и тот же документ. Чужой — `403`.

---

## Живое обновление

Пока холст открыт, одно соединение. Это SSE: сервер пишет, клиент читает. Сохранение по-прежнему `PUT`.

`EventSource` не подходит: он не умеет заголовок `Authorization`. Открывать через `fetch`.

```
GET /student/boards/{id}/events
GET /teacher/boards/{id}/events
Authorization: Bearer <token>
Accept: text/event-stream
```

Чужая доска — `403`, неизвестный id — `404`. Соединение базу не занимает: проверка доступа один раз в начале.

Первое сообщение — текущая ревизия, без объектов:

```
event: update
data: {"id":"6f1c2a40-7b1e-4d2a-9c33-0a1b2c3d4e5f","revision":4,"updatedAt":"2026-09-28T00:40:12.000Z"}
```

Такое же `update` приходит после каждого успешного `PUT` любого участника. Если `revision` больше локальной и своих неотправленных штрихов нет — один `GET /boards/{id}` и подменить документ. Если `revision` не больше локальной, ничего не качать: это либо то, что уже на экране, либо свой собственный `PUT`.

Если локально есть несохранённые штрихи, холст из потока не затирать. Следующий `PUT` получит `409` и документ с сервера.

Удаление доски:

```
event: delete
data: {"id":"6f1c2a40-7b1e-4d2a-9c33-0a1b2c3d4e5f"}
```

После `delete` поток закрывается.

Раз в 15 секунд сервер пишет комментарий `: ping`. Это не событие, его пропускать. Если поток оборвался, открыть его снова: первое `update` скажет, не устарела ли локальная ревизия.

```javascript
const response = await fetch(`${API}/student/boards/${id}/events`, {
  headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
});
const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const chunks = buffer.split("\n\n");
  buffer = chunks.pop() ?? "";
  for (const chunk of chunks) {
    if (chunk.startsWith(":")) continue;
    const event = chunk.match(/^event: (.+)$/m)?.[1];
    const data = JSON.parse(chunk.match(/^data: (.+)$/m)?.[1] ?? "null");
    if (event === "update" && data.revision > localRevision && !dirty) {
      localRevision = data.revision;
      replaceFrom(await getBoard(id));
    }
    if (event === "delete") closeBoard();
  }
}
```

---

## Учитель

Роль `teacher` или `admin`. Ученик доску не создаёт.

### Создать

```
POST /teacher/boards
Content-Type: application/json
```

Либо ученики, либо одна группа. Оба поля вместе или ни одного — `400`, «Нужны ученики или группа, что-то одно».

```json
{ "title": "Дроби", "studentIds": [45, 46] }
```

```json
{ "title": "Групповая доска", "groupId": 3 }
```

Ученики должны быть привязаны к этому учителю, иначе `400`. Чужая группа — `404`. Пустое название — `400`.

**Ответ 200:** полный пустой документ, `revision` равен `1`.

### Список, открытие, сохранение, удаление

```
GET    /teacher/boards
GET    /teacher/boards/{id}
PUT    /teacher/boards/{id}
DELETE /teacher/boards/{id}
```

`GET /teacher/boards` — доски этого учителя, без `objects`, свежие сверху.

`DELETE` удаляет доску и её картинки.

**Ответ 200:** `{ "ok": true }`.

Чужая доска — `403`. Неизвестный UUID — `404`.

---

## Ученик

Роль в токене — `student`.

```
GET /student/boards
GET /student/boards/{id}
PUT /student/boards/{id}
```

В списке доски, где ученик указан в `studentIds`, и доски групп, в которых он сейчас состоит. Без `objects`, свежие сверху. Общей кнопки «новая доска» нет.

`PUT` пишет в тот же документ, что и учитель.

---

## Картинки

Файл в JSON доски не класть: ни base64, ни `data:`. Сначала загрузка, потом `fileId` в объекте.

```
POST /student/boards/images
POST /teacher/boards/images
Content-Type: multipart/form-data
```

Поле файла — `file`. Форматы: jpeg, png, webp. До 10 МБ. Тип определяется по содержимому.

**Ответ 200:**

```json
{
  "fileId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "чертёж.png",
  "src": "https://…/boards/a1b2c3d4-e5f6-7890-abcd-ef1234567890.png"
}
```

`src` — публичный адрес, как у картинок заданий. `<img>` открывает его без `Authorization`.

При каждом `GET` и успешном `PUT` сервер заново пишет `src` по `fileId`. Если такого файла нет, `src` — пустая строка.

Удаление объекта с холста файл не стирает. Файл уходит, когда учитель удаляет доску, к которой картинка уже была привязана сохранением.

---

## Шаблоны GeoGebra

Четыре id на клиенте (`right-triangle`, `circle`, `coordinates`, `parabola`) сервер сам не создаёт. Пока учитель не залил `.ggb` с таким `id`, в `props.ggbBase64` пусто и апплет не монтируется.

`ggbBase64` — файл `.ggb` в base64, параметр `ggbBase64` у `GGBApplet`.

Пустая геометрия и пустые графики — не шаблоны. У них `templateId` равен `""`. Сервер такое поле не подменяет.

### Список и один шаблон

```
GET /board/geogebra-templates
GET /board/geogebra-templates/{id}?lessonId=123
```

Токен ученика или учителя. Список без base64, у каждого элемента есть `teacherId`.

`lessonId` необязателен и к доске не относится: это только способ взять шаблон учителя конкретного занятия. Без него ученик получает любой совпавший шаблон своих учителей, с меньшим `teacherId`. Учитель без `lessonId` получает свой.

На `PUT` доски, если у объекта `templateId` непустой, а `ggbBase64` пустой, сервер подставляет шаблон учителя этой доски (`teacherId` документа). Уже заполненный `ggbBase64` не затирается.

### Учитель заводит шаблон

```
POST /teacher/geogebra-templates
Content-Type: multipart/form-data
```

| Поле | |
| --- | --- |
| `file` | файл `.ggb`, до 8 МБ |
| `id` | латиница, цифры, дефис и `_`, до 64 символов |
| `title` | до 255 символов |
| `appName` | `geometry` или `graphing` |

Такой `id` у этого учителя уже есть — `409`.

```
PUT    /teacher/geogebra-templates/{id}
DELETE /teacher/geogebra-templates/{id}
```

`PUT` принимает любое из полей `title`, `appName`, `file`. `DELETE` отвечает `{ "ok": true }`.

---

## Сценарий

1. Учитель жмёт «новая доска», вводит название и выбирает учеников или группу: `POST /teacher/boards`.
2. Ученик видит её в `GET /student/boards` и открывает `GET /student/boards/{id}`.
3. Ответ `GET` кладётся в IndexedDB. Сразу открывается `GET .../boards/{id}/events`. Штрихи пишутся локально. Раз в ~700 мс и при `pagehide` уходит `PUT` с последней `revision`.
4. `200` — взять документ из ответа. `409` — заменить холст телом ответа.
5. Второй участник на том же `events` получает `update` с новой `revision` и один раз делает `GET`. Таймера опроса нет.
6. Картинку сначала `POST .../boards/images`, потом `fileId` в объект, потом `PUT` доски.
7. Шаблон: `GET /board/geogebra-templates/{id}`, base64 в объект, потом `PUT`. Либо оставить `ggbBase64` пустым: сервер подставит шаблон учителя доски.
