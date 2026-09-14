"""Собирает HTML-страницу, которая гоняет команды в настоящем апплете GeoGebra.

Ловит то, чего не видят юнит-тесты: команды, которые GeoGebra молча отвергает.
Запуск из корня проекта:

    python tools/geogebra_applet_check.py
    python -m http.server 8777
    открыть http://localhost:8777/tmp_ggb_check.html

Заголовок вкладки станет ALL OK или HAS FAILURES.
"""
import json

from services.geogebra_builder import geogebra_builder as b

V2 = {"use": "view_2d"}
V3 = {"use": "view_3d"}

SPECS = [
    ("квадрат + вписанная", {"app": "geometry", "stack": [
        V2, {"use": "square", "params": {"name": "sq", "a": 6}},
        {"use": "incircle_ngon", "params": {"poly": "sq"}}]}),
    ("квадрат + описанная", {"app": "geometry", "stack": [
        V2, {"use": "square", "params": {"name": "sq", "a": 6}},
        {"use": "circumcircle_ngon", "params": {"poly": "sq"}}]}),
    ("шестиугольник + вписанная", {"app": "geometry", "stack": [
        V2, {"use": "regular_ngon", "params": {"name": "hex", "a": 4, "n": 6}},
        {"use": "incircle_ngon", "params": {"poly": "hex"}}]}),
    ("шестиугольник + описанная", {"app": "geometry", "stack": [
        V2, {"use": "regular_ngon", "params": {"name": "hex", "a": 4, "n": 6}},
        {"use": "circumcircle_ngon", "params": {"poly": "hex"}}]}),
    ("треугольник + вписанная + описанная", {"app": "geometry", "stack": [
        V2, {"use": "triangle", "params": {"bx": 8, "cx": 3, "cy": 6}},
        {"use": "incircle"}, {"use": "circumcircle"}],
        "extra": ["O = Center(circ)", 'SetColor(circ, "#22c55e")']}),
    ("треугольник + высота", {"app": "geometry", "stack": [
        V2, {"use": "triangle", "params": {"bx": 8, "cx": 3, "cy": 5}},
        {"use": "height", "params": {"apex": "C"}}],
        "extra": ['SetColor(hgt, "#ef4444")', 'Text("h = 5", (3.2, 2.5))']}),
    ("трапеция + высота + подписи", {"app": "geometry", "stack": [
        V2, {"use": "trapezoid", "params": {"a": 13, "b": 7, "h": 6}},
        {"use": "height", "params": {"apex": "D", "a": "A", "b": "B"}}],
        "extra": ['a = Text("13", (6.5, -0.7))', 'h = Text("6", (3.3, 3))',
                  'SetColor(hgt, "#ef4444")', "SetFilling(trap, 0.3)"]}),
    ("параллелограмм + диагональ", {"app": "geometry", "stack": [
        V2, {"use": "parallelogram", "params": {"a": 8, "h": 5, "s": 3}},
        {"use": "diagonal", "params": {"a": "A", "b": "C"}}],
        "extra": ['SetColor(diag, "#0066ff")']}),
    ("ромб + обе диагонали", {"app": "geometry", "stack": [
        V2, {"use": "rhombus", "params": {"p": 8, "q": 6}},
        {"use": "diagonal", "params": {"name": "d1", "a": "A", "b": "C"}},
        {"use": "diagonal", "params": {"name": "d2", "a": "B", "b": "D"}}]}),
    ("прямоугольный треугольник + высота к гипотенузе", {"app": "geometry", "stack": [
        V2, {"use": "right_triangle", "params": {"a": 6, "b": 8}},
        {"use": "height", "params": {"apex": "A", "a": "B", "b": "C"}}],
        "extra": ["Angle(B, A, C)"]}),
    ("сектор", {"app": "geometry", "stack": [
        V2, {"use": "sector", "params": {"r": 5, "alpha": 60}}]}),
    ("сегмент круга", {"app": "geometry", "stack": [
        V2, {"use": "circle_segment", "params": {"r": 5, "alpha": 90}}]}),
    ("график + производная", {"app": "graphing", "stack": [
        {"use": "view_graph"}, {"use": "function", "params": {"expr": "x^2-4"}},
        {"use": "derivative", "params": {"f": "f"}}]}),
]

SPECS_3D = [
    ("пирамида", {"app": "3d", "stack": [
        V3, {"use": "regular_pyramid", "params": {"a": 6, "h": 5, "n": 4}}],
        "extra": ['Text("h = 5", (0, 0, 2.5))']}),
    ("цилиндр", {"app": "3d", "stack": [
        V3, {"use": "cylinder", "params": {"r": 3}}],
        "extra": ['Text("r = 3", (3, 0, 0))']}),
    ("параллелепипед + диагональ", {"app": "3d", "stack": [
        V3, {"use": "parallelepiped", "params": {"a": 2, "b": 3, "c": 6}}],
        "extra": ["d = Segment(A, G)", 'SetColor(d, "#0066ff")']}),
]


def build(specs):
    out = []
    for title, spec in specs:
        r = b.render_spec(spec)
        out.append({"title": title, "app": r["app"], "commands": r["commands"]})
    return out


cases = build(SPECS)
cases3d = build(SPECS_3D)

html = """<!doctype html>
<html><head><meta charset="utf-8">
<script src="https://www.geogebra.org/apps/deployggb.js"></script>
<style>body{font-family:system-ui;margin:12px}
#report{white-space:pre-wrap;font:13px/1.5 monospace;border:1px solid #ccc;padding:10px}
.ok{color:#15803d}.bad{color:#b91c1c;font-weight:700}</style>
</head><body>
<h3>Проверка команд в апплете</h3>
<div id="report">запуск...</div>
<div id="app2d"></div><div id="app3d"></div>
<script>
const CASES_2D = __C2D__;
const CASES_3D = __C3D__;
const lines = [];
let done2d = false, done3d = false;

function runAll(api, cases, label) {
  for (const c of cases) {
    api.newConstruction();
    const failed = [];
    for (const cmd of c.commands) {
      let ok = false;
      try { ok = api.evalCommand(cmd); } catch (e) { ok = false; }
      // Команды вида SetColor/ZoomIn штатно возвращают false — судим по объекту.
      const m = cmd.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=/);
      if (m) { if (!api.exists(m[1])) failed.push(cmd); }
      else if (ok === false && !/^(Set|Show|Zoom|Center|Axes)/.test(cmd)) failed.push(cmd);
    }
    if (failed.length === 0) lines.push(`OK   [${label}] ${c.title}`);
    else lines.push(`FAIL [${label}] ${c.title}\\n       ` + failed.join('\\n       '));
  }
}

function render() {
  if (!done2d || !done3d) return;
  document.getElementById('report').innerHTML = lines
    .map(l => `<div class="${l.startsWith('OK') ? 'ok' : 'bad'}">${l}</div>`).join('');
  document.title = lines.some(l => l.startsWith('FAIL')) ? 'HAS FAILURES' : 'ALL OK';
}

new GGBApplet({appName: 'geometry', width: 400, height: 300, showToolBar: false,
  showAlgebraInput: false, showMenuBar: false, errorDialogsActive: false,
  appletOnLoad: api => { runAll(api, CASES_2D, '2D'); done2d = true; render(); }
}, true).inject('app2d');

new GGBApplet({appName: '3d', width: 400, height: 300, showToolBar: false,
  showAlgebraInput: false, showMenuBar: false, errorDialogsActive: false,
  appletOnLoad: api => { runAll(api, CASES_3D, '3D'); done3d = true; render(); }
}, true).inject('app3d');
</script></body></html>
"""

html = html.replace("__C2D__", json.dumps(cases, ensure_ascii=False))
html = html.replace("__C3D__", json.dumps(cases3d, ensure_ascii=False))
with open("tmp_ggb_check.html", "w", encoding="utf-8") as fh:
    fh.write(html)
print("cases:", len(cases), "+", len(cases3d))
