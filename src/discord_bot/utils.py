from __future__ import annotations

import ast
import math
import operator
from collections.abc import Iterable
from typing import Any


EMBED_COLOR = 0xD2ACE3


def chunk_text(text: str, limit: int = 1_000) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    return [text[index : index + limit] for index in range(0, len(text), limit)] or [""]


def chunk_lines(lines: Iterable[str], limit: int = 1_024) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}{line}\n"
        if current and len(candidate) > limit:
            chunks.append(current.rstrip())
            current = f"{line}\n"
        else:
            current = candidate
    if current:
        chunks.append(current.rstrip())
    return chunks


def first_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for child in value.values():
            found = first_list(child)
            if found:
                return found
    return []


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lng / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log10,
    "ln": math.log,
}


def safe_calculate(expression: str) -> int | float:
    tree = ast.parse(expression.replace("^", "**"), mode="eval")

    def evaluate(node: ast.AST, depth: int = 0) -> int | float:
        if depth > 20:
            raise ValueError("運算式過於複雜")
        if isinstance(node, ast.Expression):
            return evaluate(node.body, depth + 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate(node.left, depth + 1)
            right = evaluate(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("指數過大")
            return _BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](evaluate(node.operand, depth + 1))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS
            and len(node.args) == 1
            and not node.keywords
        ):
            return _FUNCTIONS[node.func.id](evaluate(node.args[0], depth + 1))
        raise ValueError("包含不支援的運算")

    result = evaluate(tree)
    if not math.isfinite(float(result)):
        raise ValueError("結果不是有限數值")
    return result

