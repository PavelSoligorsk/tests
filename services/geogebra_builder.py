"""Сборка чертежей GeoGebra из кусков YAML + extra-команд."""
from __future__ import annotations

import ast
import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent / "geogebra"
PIECES_DIR = ROOT / "pieces"
WHITELIST_PATH = ROOT / "extra_whitelist.yml"
COMMANDS_PATH = ROOT / "commands.yml"
PARAM_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*=")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
JS_RE = re.compile(r"\bapi\.|javascript:|eval\s*\(", re.IGNORECASE)
FENCE_RE = re.compile(r"```geogebra\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
JSX_RE = re.compile(
    r"<GeoGebra\s+setup=\{`([^`]*)`\}\s+height=\"(\d+)\"\s*/>",
    re.DOTALL,
)
OLD_JSON_RE = re.compile(r"=== GEOGEBRA ===\s*(\{.*?\})", re.DOTALL | re.IGNORECASE)

ALLOWED_HEIGHTS = {"300", "400", "450", "500"}
ALLOWED_APPS = {"geometry", "graphing", "3d"}
GG_KEYWORDS = {
    "true", "false", "x", "y", "z",
    "sin", "cos", "tan", "sqrt", "ln", "log", "exp", "abs", "pi",
}

_BOOL = {"true": True, "false": False, "yes": True, "no": False}

APP_PERSPECTIVE = {
    "geometry": 'SetPerspective("G")',
    "graphing": 'SetPerspective("G")',
    "3d": 'SetPerspective("T")',
}
# G=Graphics, T=3D, A=Algebra, D=Graphics2, C=CAS, S=Spreadsheet, B=Probability, L=Protocol, P=Properties, R=Data
# "2" — устаревший алиас плоского вида, переписывается в G
SET_PERSPECTIVE_OK = re.compile(
    r'^SetPerspective\(\s*"(?:2|[ABCDGLPRST]+)"\s*\)$',
    re.IGNORECASE,
)
SET_PERSPECTIVE_LINE = re.compile(r"^SetPerspective\s*\(", re.IGNORECASE)
BARE_NUMBER_RE = re.compile(r'^-?\d+(\.\d+)?$')
POINT_FIRST_FNS = {
    "RegularPolygon", "Polygon", "Midpoint", "Segment", "Ray", "Line",
    "Angle", "Incircle", "Circumcircle", "AngleBisector", "PerpendicularLine",
    "PerpendicularBisector", "Tangent", "Centroid", "Prism", "Pyramid",
    "Cube", "Tetrahedron", "Cylinder", "Cone",
}


def _placeholder(fig_id: int) -> str:
    return "{{geogebra:" + str(fig_id) + "}}"


def _call_fn_args(expr: str) -> tuple[str, str] | None:
    expr = expr.strip()
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", expr)
    if not match:
        return None
    return match.group(1), match.group(2)


def _syntax_ok(expr: str) -> bool:
    """Отсечь команды, от которых апплет GeoGebra падает в белый экран."""
    parsed = _call_fn_args(expr)
    if not parsed:
        return True
    fn, args = parsed
    if fn.lower() == "setperspective":
        return bool(SET_PERSPECTIVE_OK.match(expr.strip()))
    if fn.lower() == "text":
        lead = args.lstrip()
        if not (lead.startswith('"') or lead.startswith("'")):
            return False
        parts = _split_top_args(args)
        for extra in parts[2:]:
            if extra.strip().lower() not in {"true", "false"}:
                return False
        return True
    if fn.lower() == "setfilling":
        parts = _split_top_args(args)
        if len(parts) < 2:
            return False
        fill = parts[1].strip().strip('"').strip("'")
        return bool(BARE_NUMBER_RE.match(fill))
    if fn in POINT_FIRST_FNS:
        first = args.split(",")[0].strip() if args else ""
        if BARE_NUMBER_RE.match(first):
            return False
    return True


REGULAR_POLYGON_NUMS = re.compile(
    r"^(?:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*)?Polygon\(\s*"
    r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(\d+)\s*\)\s*$"
)
ZERO_PRISM = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Prism\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*0(?:\.0+)?\s*\)\s*$"
)


NAMED_KW = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")


def _split_top_args(args: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    in_str = None
    start = 0
    for i, ch in enumerate(args):
        if in_str:
            if ch == in_str and (i == 0 or args[i - 1] != "\\"):
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(args[start:i].strip())
            start = i + 1
    parts.append(args[start:].strip())
    return [p for p in parts if p]


def _split_first_arg(args: str) -> tuple[str, str]:
    parts = _split_top_args(args)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], ", ".join(parts[1:])


def _strip_named_kwargs_expr(expr: str) -> str:
    """GeoGebra Script не принимает fontSize=3 и прочие name=value."""
    parsed = _call_fn_args(expr)
    if not parsed:
        return expr
    fn, args = parsed
    kept = [p for p in _split_top_args(args) if not NAMED_KW.match(p)]
    return f"{fn}({', '.join(kept)})"


def _strip_named_kwargs_line(line: str) -> str:
    assign = ASSIGN_RE.match(line)
    if not assign:
        return _strip_named_kwargs_expr(line)
    lhs, rhs = line.split("=", 1)
    return f"{lhs.strip()} = {_strip_named_kwargs_expr(rhs.strip())}"


def _repair_setfilling(line: str) -> list[str]:
    """SetFilling(obj, 0.3) — доля 0..1, не цвет. Hex уходит в SetColor."""
    parsed = _call_fn_args(line)
    if not parsed or parsed[0].lower() != "setfilling":
        return [line]
    parts = _split_top_args(parsed[1])
    if len(parts) < 2:
        return []
    obj = parts[0]
    fill = parts[1].strip().strip('"').strip("'")
    if BARE_NUMBER_RE.match(fill):
        value = float(fill)
        if value < 0 or value > 1:
            fill = "0.3"
        return [f"SetFilling({obj}, {fill})"]
    if re.fullmatch(r"#?[0-9A-Fa-f]{3,8}", fill):
        color = fill if fill.startswith("#") else f"#{fill}"
        return [f'SetColor({obj}, "{color}")', f"SetFilling({obj}, 0.3)"]
    return [f"SetFilling({obj}, 0.3)"]


def _rename_dead_commands(line: str) -> str:
    """RegularPolygon и Circumcircle в GeoGebra не существуют — есть только Polygon и Circle."""
    line = re.sub(r"\bRegularPolygon\s*\(", "Polygon(", line)
    return re.sub(r"\bCircumcircle\s*\(", "Circle(", line)


def _repair_extra_line(line: str) -> list[str]:
    """Починить типичные ошибки модели до валидации."""
    line = _rename_dead_commands(line)
    poly = REGULAR_POLYGON_NUMS.match(line)
    if poly:
        name, side, _side2, n = poly.groups()
        name = name or "base"
        return [
            "A = (0, 0)",
            f"B = ({side}, 0)",
            f"{name} = Polygon(A, B, {n})",
        ]

    text_assign = re.match(
        r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Text\((.*)\)\s*$",
        line,
    )
    text_call = re.match(r"^Text\((.*)\)\s*$", line)
    if text_assign or text_call:
        prefix = f"{text_assign.group(1)} = " if text_assign else ""
        args = (text_assign.group(2) if text_assign else text_call.group(1)).strip()
        if args and not args.startswith(('"', "'")):
            first, rest = _split_first_arg(args)
            first = first.strip().strip('"').strip("'")
            args = f'"{first}"' + (f", {rest}" if rest else "")
        line = _strip_named_kwargs_line(f"{prefix}Text({args})")
        parsed = _call_fn_args(line.split("=", 1)[-1].strip() if "=" in line and ASSIGN_RE.match(line) else line)
        if parsed and parsed[0].lower() == "text":
            parts = _split_top_args(parsed[1])
            kept = []
            for i, part in enumerate(parts):
                if i <= 1:
                    kept.append(part)
                elif part.strip().lower() in {"true", "false"}:
                    kept.append(part)
                else:
                    break
            body = f"Text({', '.join(kept)})"
            if ASSIGN_RE.match(line):
                lhs = line.split("=", 1)[0].strip()
                return [f"{lhs} = {body}"]
            return [body]
        return [line]
    return _repair_setfilling(_strip_named_kwargs_line(line))


CONSTRUCT_CALL = re.compile(
    r"\b(?:Polygon|RegularPolygon|Segment|Prism|Pyramid|Cylinder|Cone|Sphere|"
    r"Circle|Incircle|Circumcircle|CircularSector|CircularArc|Semicircle|Sector|Arc|"
    r"Polyline|Centroid|Line|Ray|Vector|Intersect|Midpoint|Angle|Plane)\s*\("
)
POINT_ASSIGN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\(\s*-?\d"
)
SHOWLABEL = re.compile(r"^ShowLabel\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,")
HARD_RESERVED = {"Label"}
# Имена встроенных функций GeoGebra: присваивание в них молча проваливается.
GG_FUNCTION_NAMES = {
    "ln", "sec", "alt", "abs", "exp", "log", "sgn", "deg", "rad",
    "sin", "cos", "tan", "cot", "csc", "sinh", "cosh", "tanh",
    "asin", "acos", "atan", "sqrt", "cbrt", "floor", "ceil", "round",
    "conjugate", "arg", "random", "nroot", "lg", "ld",
}
CALLED_FN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
BARE_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()")
# GeoGebra сама даёт сторонам многоугольника имена a, b, c...: своё однобуквенное
# имя переопределяет её объект, и команда не выполняется.
SINGLE_LOWER = re.compile(r"^[a-z]$")


def _replace_ident(line: str, old: str, new: str) -> str:
    """Переименование вне строковых литералов — подпись Text("h", ...) не трогаем."""
    pattern = rf"\b{re.escape(old)}\b(?!\s*\()"
    return "".join(
        part if part.startswith('"') else re.sub(pattern, new, part)
        for part in re.split(r'("[^"]*")', line)
    )


def _construction_idents(commands: list[str]) -> set[str]:
    used: set[str] = set()
    for line in commands:
        if not CONSTRUCT_CALL.search(line):
            continue
        rhs = line.split("=", 1)[-1]
        for ident in IDENT_RE.findall(rhs):
            if ident not in GG_KEYWORDS:
                used.add(ident)
    return used


def _is_point_literal(rhs: str) -> bool:
    """(x, y) со строчным именем GeoGebra делает вектором, а не точкой."""
    rhs = rhs.strip()
    if not (rhs.startswith("(") and rhs.endswith(")")):
        return False
    return len(_split_top_args(rhs[1:-1])) in (2, 3)


def _postprocess_commands(commands: list[str], reserved: set[str] | None = None) -> list[str]:
    """Кавычки в Text, Prism(poly, 0), зарезервированные имена, лишние точки."""
    aliases: dict[str, str] = {}
    expanded: list[str] = []
    for raw in commands:
        for line in _repair_extra_line(raw):
            zero = ZERO_PRISM.match(line)
            if zero:
                aliases[zero.group(1)] = zero.group(2)
                continue
            expanded.append(line)

    reserved_names = set(reserved or set()) | HARD_RESERVED
    mapping: dict[str, str] = dict(aliases)
    renamed: list[str] = []
    for line in expanded:
        for old, new in aliases.items():
            line = re.sub(rf"\b{re.escape(old)}\b", new, line)
        assign = ASSIGN_RE.match(line)
        if assign:
            name = assign.group(1)
            rhs = line.split("=", 1)[1].strip()
            new = None
            if name in reserved_names or name.lower() in GG_FUNCTION_NAMES:
                new = "obj_" + name.lower()
            elif _is_point_literal(rhs) and name[0].islower():
                new = "Pt_" + name
            if new:
                mapping[name] = new
                line = f"{new} = {rhs}"
        renamed.append(line)

    after_map: list[str] = []
    for line in renamed:
        for old, new in mapping.items():
            if old != new:
                line = _replace_ident(line, old, new)
        after_map.append(line)

    needed = _construction_idents(after_map)
    has_solid = any(CONSTRUCT_CALL.search(line) for line in after_map)
    dropped: set[str] = set()
    cleaned: list[str] = []
    seen: set[str] = set()
    for line in after_map:
        if line in seen:
            continue
        point = POINT_ASSIGN.match(line)
        if (
            point
            and has_solid
            and len(point.group(1)) == 1
            and point.group(1) not in needed
        ):
            dropped.add(point.group(1))
            continue
        show = SHOWLABEL.match(line)
        if show and show.group(1) in dropped:
            continue
        seen.add(line)
        cleaned.append(line)
    return cleaned


def _ensure_perspective(commands: list[str], app: str) -> list[str]:
    """Одна перспектива первой: G для 2D/графиков, T для 3D."""
    wanted = APP_PERSPECTIVE.get(app, APP_PERSPECTIVE["geometry"])
    rest = [c for c in commands if not SET_PERSPECTIVE_LINE.match(c)]
    return [wanted, *rest]


POINT_2D_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*\((.+)\)\s*$")
ZOOM_IN_ANY = re.compile(r"^ZoomIn\s*\(", re.IGNORECASE)
CENTER_VIEW_ORIGIN = re.compile(
    r"^CenterView\(\s*\(\s*0(?:\.0+)?\s*,\s*0(?:\.0+)?(?:\s*,\s*0(?:\.0+)?)?\s*\)\s*\)\s*$",
    re.IGNORECASE,
)
ROUND_CALL = re.compile(
    r"(?:^[A-Za-z_][A-Za-z0-9_]*\s*=\s*)?"
    r"(Circle|Circumcircle|Incircle|CircularSector|CircularArc|Semicircle)\((.*)\)\s*$",
    re.IGNORECASE,
)
REGULAR_POLYGON_CALL = re.compile(
    r"(?:^[A-Za-z_][A-Za-z0-9_]*\s*=\s*)?RegularPolygon\((.*)\)\s*$",
    re.IGNORECASE,
)
POLYGON_CALL = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*Polygon\((.*)\)\s*$",
    re.IGNORECASE,
)
_MATH_FNS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan}
_MATH_CONSTS = {"pi": math.pi}


def _fmt_num(value: float) -> str:
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def _eval_num(expr: str) -> float | None:
    """Посчитать числовое выражение вида 8/2, sqrt(25-9), 4*cos(60*pi/180)."""
    try:
        tree = ast.parse(expr.strip().replace("^", "**"), mode="eval")
    except SyntaxError:
        return None

    def walk(node: ast.AST) -> float | None:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            return _MATH_CONSTS.get(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            inner = walk(node.operand)
            if inner is None:
                return None
            return inner if isinstance(node.op, ast.UAdd) else -inner
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if left is None or right is None:
                return None
            try:
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right
                if isinstance(node.op, ast.Pow):
                    return left ** right
            except (ZeroDivisionError, ValueError, OverflowError):
                return None
            return None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = _MATH_FNS.get(node.func.id)
            if fn is None or len(node.args) != 1:
                return None
            arg = walk(node.args[0])
            if arg is None:
                return None
            try:
                return fn(arg)
            except ValueError:
                return None
        return None

    return walk(tree)


def _eval_point(expr: str) -> tuple[float, float] | None:
    parts = _split_top_args(expr)
    if len(parts) != 2:
        return None
    x, y = _eval_num(parts[0]), _eval_num(parts[1])
    if x is None or y is None:
        return None
    return x, y


def _resolve_point(
    token: str,
    coords: dict[str, tuple[float, float]],
    polys: dict[str, list[tuple[float, float]]] | None = None,
):
    token = token.strip()
    if token in coords:
        return coords[token]
    if token.startswith("(") and token.endswith(")"):
        inner = _eval_point(token[1:-1])
        if inner:
            return inner
    call = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", token, re.S)
    if not call:
        return None
    fn, args = call.group(1).lower(), _split_top_args(call.group(2))
    if fn == "midpoint" and len(args) == 2:
        a = _resolve_point(args[0], coords, polys)
        b = _resolve_point(args[1], coords, polys)
        if a and b:
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if fn == "centroid" and len(args) == 1 and polys:
        pts = polys.get(args[0].strip())
        if pts:
            return (
                sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts),
            )
    if fn == "vertex" and len(args) == 2 and polys:
        pts = polys.get(args[0].strip())
        idx = _eval_num(args[1])
        if pts and idx is not None and 1 <= int(idx) <= len(pts):
            return pts[int(idx) - 1]
    return None


def _resolve_num(
    token: str,
    coords: dict[str, tuple[float, float]],
    polys: dict[str, list[tuple[float, float]]] | None = None,
) -> float | None:
    """Число либо Distance(P, Q) — радиус вписанной/описанной окружности."""
    value = _eval_num(token)
    if value is not None:
        return value
    call = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", token.strip(), re.S)
    if not call or call.group(1).lower() != "distance":
        return None
    args = _split_top_args(call.group(2))
    if len(args) != 2:
        return None
    a = _resolve_point(args[0], coords, polys)
    b = _resolve_point(args[1], coords, polys)
    return math.dist(a, b) if a and b else None


def _rotate(point, center, angle):
    dx, dy = point[0] - center[0], point[1] - center[1]
    return (
        center[0] + dx * math.cos(angle) - dy * math.sin(angle),
        center[1] + dx * math.sin(angle) + dy * math.cos(angle),
    )


def _regular_polygon_vertices(
    p: tuple[float, float], q: tuple[float, float], n: int
) -> list[tuple[float, float]]:
    """Вершины RegularPolygon(P, Q, n). GeoGebra строит против часовой от P к Q."""
    side = math.dist(p, q)
    if side < 1e-9:
        return [p]
    apothem = side / (2 * math.tan(math.pi / n))
    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    ux, uy = (q[0] - p[0]) / side, (q[1] - p[1]) / side
    center = (mid[0] - uy * apothem, mid[1] + ux * apothem)
    step = 2 * math.pi / n
    return [_rotate(p, center, k * step) for k in range(n)]


def _arc_points(
    center: tuple[float, float], p: tuple[float, float], q: tuple[float, float]
) -> list[tuple[float, float]]:
    """Точки дуги против часовой от P к Q — чтобы кадр не брал всю окружность."""
    r = math.dist(center, p)
    if r < 1e-9:
        return [center]
    start = math.atan2(p[1] - center[1], p[0] - center[0])
    end = math.atan2(q[1] - center[1], q[0] - center[0])
    sweep = (end - start) % (2 * math.pi)
    steps = 24
    return [
        (
            center[0] + r * math.cos(start + sweep * i / steps),
            center[1] + r * math.sin(start + sweep * i / steps),
        )
        for i in range(steps + 1)
    ]


def _2d_bounds(commands: list[str]) -> tuple[float, float, float, float] | None:
    coords: dict[str, tuple[float, float]] = {}
    polys: dict[str, list[tuple[float, float]]] = {}
    xs: list[float] = []
    ys: list[float] = []

    def add(x: float, y: float) -> None:
        xs.append(x)
        ys.append(y)

    def add_disc(center: tuple[float, float], r: float) -> None:
        add(center[0] - r, center[1] - r)
        add(center[0] + r, center[1] + r)

    for line in commands:
        point = POINT_2D_ASSIGN.match(line)
        if point:
            xy = _eval_point(point.group(1))
            if xy:
                name = ASSIGN_RE.match(line)
                if name:
                    coords[name.group(1)] = xy
                add(*xy)
                continue

        ngon = REGULAR_POLYGON_CALL.match(line)
        if ngon:
            args = _split_top_args(ngon.group(1))
            if len(args) == 3:
                p = _resolve_point(args[0], coords, polys)
                q = _resolve_point(args[1], coords, polys)
                n = _eval_num(args[2])
                if p and q and n and n >= 3:
                    verts = _regular_polygon_vertices(p, q, int(n))
                    name = ASSIGN_RE.match(line)
                    if name:
                        polys[name.group(1)] = verts
                    for vx, vy in verts:
                        add(vx, vy)
            continue

        poly = POLYGON_CALL.match(line)
        if poly:
            name = ASSIGN_RE.match(line)
            args = _split_top_args(poly.group(1))
            verts: list[tuple[float, float]] = []
            if len(args) == 3 and _eval_num(args[2]) is not None:
                # Polygon(P, Q, n) — правильный n-угольник по стороне PQ.
                p = _resolve_point(args[0], coords, polys)
                q = _resolve_point(args[1], coords, polys)
                n = _eval_num(args[2])
                if p and q and n and n >= 3:
                    verts = _regular_polygon_vertices(p, q, int(n))
            else:
                verts = [
                    pt for pt in (_resolve_point(a, coords, polys) for a in args) if pt
                ]
            if len(verts) >= 3:
                if name:
                    polys[name.group(1)] = verts
                for vx, vy in verts:
                    add(vx, vy)
            continue

        round_call = ROUND_CALL.match(line)
        if round_call:
            fn = round_call.group(1).lower()
            args = _split_top_args(round_call.group(2))
            if fn == "circle" and len(args) == 2:
                center = _resolve_point(args[0], coords, polys)
                edge = _resolve_point(args[1], coords, polys)
                radius = _resolve_num(args[1], coords, polys)
                if center and radius is not None:
                    add_disc(center, abs(radius))
                elif center and edge:
                    add_disc(center, math.dist(center, edge))
            elif fn in {"circle", "circumcircle", "incircle"} and len(args) == 3:
                pts = [_resolve_point(a, coords, polys) for a in args]
                if all(pts):
                    for pt in pts:
                        add(*pt)
                    # Circle(A, B, C) — окружность через три точки, она шире треугольника.
                    if fn != "incircle":
                        circum = _circumcircle(*pts)
                        if circum:
                            add_disc(*circum)
            elif fn in {"circularsector", "circulararc", "semicircle"} and len(args) >= 2:
                center = _resolve_point(args[0], coords, polys)
                start = _resolve_point(args[1], coords, polys)
                end = _resolve_point(args[2], coords, polys) if len(args) > 2 else None
                if center and start and end:
                    for pt in _arc_points(center, start, end):
                        add(*pt)
                elif center and start:
                    add_disc(center, math.dist(center, start))
            continue

    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _circumcircle(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-9:
        return None
    ux = (
        (a[0] ** 2 + a[1] ** 2) * (b[1] - c[1])
        + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1])
        + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])
    ) / d
    uy = (
        (a[0] ** 2 + a[1] ** 2) * (c[0] - b[0])
        + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0])
        + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])
    ) / d
    return (ux, uy), math.dist((ux, uy), a)


def _ensure_fit_2d(commands: list[str], app: str) -> list[str]:
    """Для geometry/graphing один ZoomIn(xmin,ymin,xmax,ymax) в конце, по всей фигуре."""
    if app not in {"geometry", "graphing"}:
        return commands
    rest = [
        c for c in commands
        if not ZOOM_IN_ANY.match(c) and not CENTER_VIEW_ORIGIN.match(c)
    ]
    bounds = _2d_bounds(rest)
    if bounds is None:
        if app == "graphing":
            return [*rest, "ZoomIn(-8, -6, 8, 6)"]
        return rest
    pad = 1.0
    xmin, ymin, xmax, ymax = bounds
    if xmin == xmax:
        xmin -= 1
        xmax += 1
    if ymin == ymax:
        ymin -= 1
        ymax += 1
    return [
        *rest,
        f"ZoomIn({_fmt_num(xmin - pad)}, {_fmt_num(ymin - pad)}, "
        f"{_fmt_num(xmax + pad)}, {_fmt_num(ymax + pad)})",
    ]


SCALAR_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^=(].*)$")
PAREN_GROUP = re.compile(r"\(([^()]*)\)")
SEQUENCE_RADIUS = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*cos\(", re.IGNORECASE)


def _3d_bounds(commands: list[str]) -> tuple[float, float, float, float, float, float] | None:
    """Габариты 3D-сцены по числовым точкам, радиусам и высотам тел."""
    scalars: dict[str, float] = {}
    pts: list[tuple[float, float, float]] = []

    def resolve(token: str) -> float | None:
        token = token.strip()
        if token in scalars:
            return scalars[token]
        return _eval_num(token)

    for line in commands:
        # (x, y, z) в любом месте строки: вершины, центры, концы осей тел.
        for group in PAREN_GROUP.findall(line):
            args = _split_top_args(group)
            if len(args) != 3:
                continue
            vals = [resolve(a) for a in args]
            if all(v is not None for v in vals):
                pts.append(tuple(vals))  # type: ignore[arg-type]

        scalar = SCALAR_ASSIGN.match(line)
        if scalar:
            value = _eval_num(scalar.group(2))
            if value is None:
                value = resolve(scalar.group(2))
            if value is not None:
                scalars[scalar.group(1)] = value

        call = _call_fn_args(line.split("=", 1)[1].strip() if ASSIGN_RE.match(line) else line)
        if not call:
            continue
        fn, raw_args = call[0].lower(), _split_top_args(call[1])
        if fn in {"cylinder", "cone"} and len(raw_args) == 3:
            r = resolve(raw_args[2])
            if r is not None:
                for group in PAREN_GROUP.findall(raw_args[0] + " " + raw_args[1]):
                    args = _split_top_args(group)
                    vals = [resolve(a) for a in args]
                    if len(vals) == 3 and all(v is not None for v in vals):
                        pts.append((vals[0] - r, vals[1] - r, vals[2]))  # type: ignore[operator]
                        pts.append((vals[0] + r, vals[1] + r, vals[2]))  # type: ignore[operator]
        elif fn == "sphere" and len(raw_args) == 2:
            r = resolve(raw_args[1])
            for group in PAREN_GROUP.findall(raw_args[0]):
                args = _split_top_args(group)
                vals = [resolve(a) for a in args]
                if r is not None and len(vals) == 3 and all(v is not None for v in vals):
                    pts.append((vals[0] - r, vals[1] - r, vals[2] - r))  # type: ignore[operator]
                    pts.append((vals[0] + r, vals[1] + r, vals[2] + r))  # type: ignore[operator]
        elif fn == "prism" and len(raw_args) == 2:
            h = resolve(raw_args[1])
            if h is not None:
                pts.append((0.0, 0.0, h))
        elif fn in {"cube", "tetrahedron"}:
            edge = resolve(raw_args[-1]) if raw_args else None
            if edge is not None:
                pts.append((edge, edge, edge))

        radius = SEQUENCE_RADIUS.search(line)
        if radius:
            r = scalars.get(radius.group(1))
            if r is not None:
                pts.append((-r, -r, 0.0))
                pts.append((r, r, 0.0))

    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _ensure_fit_3d(commands: list[str], app: str) -> list[str]:
    """Для 3D один ZoomIn(xmin,ymin,zmin,xmax,ymax,zmax) в конце."""
    if app != "3d":
        return commands
    rest = [c for c in commands if not ZOOM_IN_ANY.match(c)]
    bounds = _3d_bounds(rest)
    if bounds is None:
        return [*rest, "ZoomIn(-6, -6, -6, 6, 6, 6)"]
    xmin, ymin, zmin, xmax, ymax, zmax = bounds
    pad = 1.5
    # Куб обзора: у 3D-вида равные масштабы осей, иначе фигуру сплющит.
    half = max(xmax - xmin, ymax - ymin, zmax - zmin) / 2 + pad
    cx, cy, cz = (xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2
    return [
        *rest,
        f"ZoomIn({_fmt_num(cx - half)}, {_fmt_num(cy - half)}, {_fmt_num(cz - half)}, "
        f"{_fmt_num(cx + half)}, {_fmt_num(cy + half)}, {_fmt_num(cz + half)})",
    ]


def _subst(text: str, params: dict[str, Any]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            return match.group(0)
        val = params[key]
        if isinstance(val, bool):
            return "true" if val else "false"
        if val is None:
            return ""
        return str(val)

    return PARAM_RE.sub(repl, text)


def _as_bool(val: Any) -> Any:
    if isinstance(val, str) and val.lower() in _BOOL:
        return _BOOL[val.lower()]
    return val


def _norm_height(value: Any) -> str:
    raw = str(value or "400")
    return raw if raw in ALLOWED_HEIGHTS else "400"


def _norm_app(value: Any, fallback: str = "geometry") -> str:
    raw = str(value or fallback).lower()
    if raw in ("t", "3d", "spatial"):
        return "3d"
    if raw in ("g", "graphing", "graph"):
        return "graphing"
    if raw in ALLOWED_APPS:
        return raw
    return fallback if fallback in ALLOWED_APPS else "geometry"


class GeoGebraBuilder:
    def __init__(self, pieces_dir: Path | None = None, whitelist_path: Path | None = None):
        self.pieces_dir = pieces_dir or PIECES_DIR
        self.whitelist_path = whitelist_path or WHITELIST_PATH
        self.commands_path = COMMANDS_PATH
        self.pieces: dict[str, dict] = {}
        self.extra_commands: set[str] = set()
        self.extra_free: set[str] = set()
        self.forbidden: set[str] = set()
        self.command_categories: dict[str, list[str]] = {}
        self.reload()

    def reload(self) -> None:
        self.pieces = {}
        if self.pieces_dir.exists():
            for path in sorted(self.pieces_dir.glob("*.yml")):
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                piece_id = data.get("id") or path.stem
                self.pieces[piece_id] = data
        whitelist = {}
        if self.whitelist_path.exists():
            whitelist = yaml.safe_load(self.whitelist_path.read_text(encoding="utf-8")) or {}
        self.extra_commands = {str(x) for x in whitelist.get("commands", [])}
        self.extra_free = {str(x) for x in whitelist.get("free", [])}
        self.forbidden = {str(x) for x in whitelist.get("forbidden", [])}
        self.command_categories = {}
        if COMMANDS_PATH.exists():
            catalog = yaml.safe_load(COMMANDS_PATH.read_text(encoding="utf-8")) or {}
            self.forbidden.update(str(x) for x in catalog.get("forbidden", []))
            self.extra_free.update(str(x) for x in catalog.get("free", []))
            categories = catalog.get("categories") or {}
            self.command_categories = {
                str(cat): [str(n) for n in names] for cat, names in categories.items()
            }
            for names in self.command_categories.values():
                self.extra_commands.update(names)
        self.extra_commands.update(self.extra_free)

    def catalog_text(self) -> str:
        lines = []
        for piece_id, piece in self.pieces.items():
            params = piece.get("params") or {}
            keys = ", ".join(params.keys()) or "—"
            summary = (piece.get("summary") or "").strip()
            app = piece.get("app")
            app_bit = f" app={app}." if app else ""
            lines.append(f"- {piece_id}: {summary} params: {keys}.{app_bit}")
        return "\n".join(lines)

    def extra_catalog_text(self) -> str:
        if not self.command_categories:
            return ""
        lines = []
        for cat, names in self.command_categories.items():
            lines.append(f"- {cat}: {', '.join(names)}")
        return "\n".join(lines)

    def prompt_instructions(self) -> str:
        return f"""
=== ЧЕРТЕЖИ GeoGebra ===
Если визуализация помогает — вставь блок ТАМ, где он должен стоять в тексте (не обязательно в конце).
Чертежей может быть несколько. Если не нужен — блоков нет.

Формат строго такой (JSON внутри ограды):

```geogebra
{{"app":"geometry","height":400,"stack":[{{"use":"view_2d","params":{{}}}},{{"use":"point","params":{{"name":"A","at":"(2,0)"}}}},{{"use":"fit_2d","params":{{"xmin":-2,"ymin":-2,"xmax":6,"ymax":4}}}}],"extra":["SetColor(A, \\"#ef4444\\")","ShowLabel(A, true)"]}}
```

Поля блока:
- app: geometry | graphing | 3d
- height: 300, 400, 450 или 500
- stack: массив кусков {{"use":"...","params":{{...}}}} из каталога, сколько угодно
- extra: команды GeoGebra Script ПОСЛЕ стека. Синтаксис английский со скобками: Circle(A, 3), не Circle[<А>, <r>] и не русские имена (Точка, Прямая).
- extra без лимита строк. Нельзя: Execute, api.*, JS.

ПЛАНИМЕТРИЯ (app=geometry, сначала view_2d, потом фигура). Готовый кусок вместо ручных точек:
- квадрат — square (a); прямоугольник — rectangle (a, b)
- параллелограмм — parallelogram (a, h, s); ромб — rhombus (p, q — диагонали)
- трапеция равнобедренная — trapezoid (a, b, h); прямоугольная — right_trapezoid (a, b, h)
- треугольник прямоугольный — right_triangle (a, b); равнобедренный — isosceles_triangle (a, h); правильный — equilateral_triangle (a)
- треугольник остроугольный/тупоугольный — triangle (ax,ay,bx,by,cx,cy). Тупой угол: вынеси C за основание, например cx=-3, cy=4
- правильный n-угольник (шестиугольник) — regular_ngon (a, n). Не задавай точки вручную
- окружность — circle (center, r)
- вписанная/описанная ТРЕУГОЛЬНИКА — incircle / circumcircle (a, b, c — вершины)
- вписанная/описанная КВАДРАТА или правильного n-угольника — incircle_ngon / circumcircle_ngon (poly — имя многоугольника). Incircle(A,B,C) берёт только три точки, для квадрата она не годится
- сектор — sector (r, alpha в градусах); сегмент круга — circle_segment (r, alpha)
У всех этих кусков вершины называются A, B, C, D (у сектора O, P, Q) — используй их в extra: Segment(A, C) для диагонали, Angle(A, B, C), Text("a = 6", (3, -0.7))

ДОСТРОЙКИ К ФИГУРЕ (высота, диагональ) — куском stack, не вручную:
- высота — height (apex — вершина, a и b — концы основания): даёт отрезок hgt и основание высоты hgt_foot
- диагональ — diagonal (a, b): например A и C
- медиана — Segment(C, Midpoint(A, B)) в extra; биссектриса — angle_bisector
- НЕ строй высоту через Line + PerpendicularLine + Intersect: бесконечная прямая останется на чертеже

СТЕРЕОМЕТРИЯ (app=3d, сначала view_3d):
- правильная призма — regular_prism (a, h, n); пирамида — regular_pyramid (a, h, n)
- параллелепипед — parallelepiped (a, b, c), диагональ Segment(A, G)
- цилиндр — cylinder (a, b, r); конус — cone; сфера — sphere; куб — cube; тетраэдр — tetrahedron
- Prism(многоугольник, высота) — высота числом > 0. Не Prism(основание, 0)
- extra в 3D — только подписи и стиль, НЕ вторая копия фигуры точками A,B,C,D,V

ГРАФИКИ (app=graphing): view_graph + function (expr без y=, например x^2-4). Производная/интеграл — derivative, integral.

ОБЩИЕ ПРАВИЛА:
- ТОЧКИ ТОЛЬКО С ЗАГЛАВНОЙ БУКВЫ: M = (3, 0) — точка, а m = (3, 0) — вектор, и всё построенное по нему разваливается
- ИМЕНА фигур: минимум две буквы (hgt, diag, med, lab_a). Однобуквенные строчные a, b, c, d, h, r GeoGebra уже заняла под стороны многоугольника — такое имя ломает чертёж.
- Запрещённые имена (это функции GeoGebra): ln, sec, alt, abs, exp, log, deg, rad, sin, cos, tan, sqrt
- Подпись — это Text, а не имя: Text("h = 6", (3, 2.5)), а не h = Text(...)
- Команд RegularPolygon и Circumcircle в GeoGebra НЕТ. Правильный n-угольник — Polygon(A, B, n) (две точки и число вершин). Описанная окружность — Circle(A, B, C) (три точки)
- Polygon(A, B, n) работает только в 2D. В 3D правильное основание — куском regular_prism / regular_pyramid
- Text только Text("подпись", (x,y)) или Text("...", (x,y,z)). Не 0.5, "top", "right", fontSize
- SetFilling(obj, 0.3) — число от 0 до 1, не цвет. Цвет: SetColor(obj, "#3b82f6")
- SetPerspective: 2D/графики SetPerspective("G") (Graphics). 3D SetPerspective("T"). Не "2" и не "T" на плоский чертёж.
- ОБЯЗАТЕЛЬНО для каждого 2D и графика: последним в stack use fit_2d (xmin,ymin,xmax,ymax = габариты фигуры плюс запас ~1). 3D — fit_2d не ставить.
- НЕ пиши JSX <GeoGebra setup=...>. НЕ пиши команды вне блока ```geogebra.
- Один app на один блок: не мешай 2D и 3D в одном чертеже.

КАТАЛОГ use (stack):
{self.catalog_text()}

КОМАНДЫ extra (английские имена):
{self.extra_catalog_text()}
"""

    def render_spec(self, spec: dict) -> Optional[dict]:
        stack = spec.get("stack") or []
        extra = spec.get("extra") or []
        if isinstance(extra, str):
            extra = extra.splitlines()

        commands: list[str] = []
        declared: set[str] = set()
        app = _norm_app(spec.get("app"))
        height = _norm_height(spec.get("height"))

        for item in stack:
            if not isinstance(item, dict):
                continue
            use = item.get("use")
            piece = self.pieces.get(use)
            if not piece:
                logger.warning("Unknown GeoGebra piece: %s", use)
                continue
            params = self._merge_params(piece, item.get("params") or {})
            added: list[str] = []
            for raw in piece.get("commands") or []:
                line = _subst(str(raw), params).strip()
                if line and "{{" not in line:
                    commands.append(line)
                    added.append(line)
            for created in piece.get("creates") or []:
                name = _subst(str(created), params).strip()
                if name:
                    declared.add(name)
            for line in added:
                assign = ASSIGN_RE.match(line)
                if assign:
                    declared.add(assign.group(1))
            piece_app = piece.get("app")
            if piece_app:
                app = _norm_app(spec.get("app") or piece_app, fallback=str(piece_app))

        renames: dict[str, str] = {}
        for raw in extra:
            for line in _repair_extra_line(str(raw).strip()):
                if not line:
                    continue
                ok, new_names, line = self._validate_extra(line, declared, renames)
                if not ok:
                    logger.info("Dropped extra GeoGebra command: %s", raw)
                    continue
                commands.append(line)
                declared.update(new_names)

        commands = _postprocess_commands(commands, self.extra_commands)
        commands = _ensure_perspective(commands, app)
        commands = _ensure_fit_2d(commands, app)
        commands = _ensure_fit_3d(commands, app)
        if not commands:
            return None
        return {
            "app": app,
            "height": height,
            "commands": commands,
            "setup": "\n".join(commands),
        }

    def process_text(self, text: str) -> tuple[str, list[dict]]:
        """Вырезать блоки чертежей из текста, собрать команды, вставить плейсхолдеры."""
        if not text:
            return text, []

        figures: list[dict] = []
        out = text

        def _replace_fence(match: re.Match) -> str:
            spec = self._parse_json_object(match.group(1))
            if spec is None:
                return ""
            rendered = self.render_spec(spec)
            if not rendered:
                return ""
            fig_id = len(figures)
            figures.append({"id": fig_id, **rendered})
            return _placeholder(fig_id)

        out = FENCE_RE.sub(_replace_fence, out)

        def _replace_jsx(match: re.Match) -> str:
            setup = match.group(1)
            height = _norm_height(match.group(2))
            commands = [ln.strip() for ln in setup.splitlines() if ln.strip()]
            if not commands:
                return ""
            fig_id = len(figures)
            figures.append({
                "id": fig_id,
                "app": "geometry",
                "height": height,
                "commands": commands,
                "setup": "\n".join(commands),
            })
            return _placeholder(fig_id)

        out = JSX_RE.sub(_replace_jsx, out)

        def _replace_old(match: re.Match) -> str:
            spec = self._parse_json_object(match.group(1))
            if spec is None:
                return ""
            if "stack" in spec or "extra" in spec:
                rendered = self.render_spec(spec)
            else:
                commands = spec.get("commands") or []
                if isinstance(commands, str):
                    commands = [ln.strip() for ln in commands.splitlines() if ln.strip()]
                setup = spec.get("setup")
                if setup and not commands:
                    commands = [ln.strip() for ln in str(setup).splitlines() if ln.strip()]
                if not commands:
                    return ""
                rendered = {
                    "app": _norm_app(spec.get("app")),
                    "height": _norm_height(spec.get("height")),
                    "commands": commands,
                    "setup": "\n".join(commands),
                }
            if not rendered:
                return ""
            fig_id = len(figures)
            figures.append({"id": fig_id, **rendered})
            return _placeholder(fig_id)

        out = OLD_JSON_RE.sub(_replace_old, out)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out, figures

    def _merge_params(self, piece: dict, incoming: dict) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for key, meta in (piece.get("params") or {}).items():
            if isinstance(meta, dict) and "default" in meta:
                params[key] = meta["default"]
            else:
                params[key] = meta
        if isinstance(incoming, dict):
            for key, val in incoming.items():
                params[key] = _as_bool(val)
        return params

    def _refs_ok(self, expr: str, declared: set[str]) -> bool:
        """Вложенные вызовы — по каталогу, остальные имена — по уже объявленным."""
        expr = re.sub(r'"[^"]*"', '""', expr)
        called = set(CALLED_FN.findall(expr))
        if not called.issubset(self.extra_commands | GG_KEYWORDS):
            return False
        bare = {i for i in BARE_IDENT.findall(expr) if i not in GG_KEYWORDS}
        return bare.issubset(declared)

    def _safe_name(self, name: str, rhs: str = "") -> str:
        if (
            name in self.extra_commands
            or name in HARD_RESERVED
            or name.lower() in GG_FUNCTION_NAMES
            or SINGLE_LOWER.match(name)
        ):
            name = "obj_" + name.lower()
        if _is_point_literal(rhs) and name[0].islower():
            return "Pt_" + name
        return name

    def _validate_extra(
        self, line: str, declared: set[str], renames: dict[str, str] | None = None
    ) -> tuple[bool, set[str], str]:
        if renames:
            for old, new in renames.items():
                line = _replace_ident(line, old, new)
        stripped = re.sub(r'"[^"]*"', '""', line)
        if JS_RE.search(line) or CYRILLIC_RE.search(stripped):
            return False, set(), line
        if "\n" in line:
            return False, set(), line
        idents = set(IDENT_RE.findall(stripped))
        if idents & self.forbidden:
            return False, set(), line

        assign = ASSIGN_RE.match(line)
        if assign:
            name = assign.group(1)
            rhs = line.split("=", 1)[1].strip()
            if not _syntax_ok(rhs):
                return False, set(), line
            call = _call_fn_args(rhs)
            if call:
                fn, _args = call
                if fn not in self.extra_commands:
                    return False, set(), line
                if fn not in self.extra_free and not self._refs_ok(rhs, declared):
                    return False, set(), line
            out_name = self._safe_name(name, rhs)
            out_line = line if out_name == name else f"{out_name} = {rhs}"
            if renames is not None and out_name != name:
                renames[name] = out_name
            return True, {out_name}, out_line

        if not _syntax_ok(line):
            return False, set(), line
        fn_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if not fn_match:
            return False, set(), line
        fn = fn_match.group(1)
        if fn not in self.extra_commands:
            return False, set(), line
        if fn in self.extra_free:
            return True, set(), line
        if not self._refs_ok(line, declared):
            return False, set(), line
        return True, set(), line

    @staticmethod
    def _parse_json_object(raw: str) -> Optional[dict]:
        blob = (raw or "").strip()
        if not blob:
            return None
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            start = blob.find("{")
            end = blob.rfind("}")
            if start < 0 or end <= start:
                logger.warning("GeoGebra block is not JSON")
                return None
            try:
                data = json.loads(blob[start:end + 1])
            except json.JSONDecodeError:
                logger.warning("Failed to parse GeoGebra JSON")
                return None
        return data if isinstance(data, dict) else None


geogebra_builder = GeoGebraBuilder()
