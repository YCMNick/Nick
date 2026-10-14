"""數字/日期顯示格式（主管閱讀用）。"""
from __future__ import annotations

from .model import Column

MD_ESCAPE = str.maketrans({c: "\\" + c for c in "\\*~`$[]<>{}|^"})


def fmt_cell(value, col: Column) -> str:
    if value is None:
        return ""
    if col.kind in ("number", "percent") and isinstance(value, float):
        if col.kind == "percent":
            return f"{value:,.{col.decimals}f}%"
        if value.is_integer() and col.decimals == 0:
            return f"{int(value):,}"
        return f"{value:,.{col.decimals}f}"
    return str(value)


def is_negative(value) -> bool:
    return isinstance(value, float) and value < 0


def md_escape(s: str) -> str:
    return s.translate(MD_ESCAPE)


def kpi_value(value: float) -> str:
    """大數字縮寫：1,234,567 → 1.23M（主管摘要用，括號保留完整數字）。"""
    a = abs(value)
    if a >= 1e8:
        short = f"{value / 1e8:,.2f} 億"
    elif a >= 1e4:
        short = f"{value / 1e4:,.1f} 萬"
    else:
        short = f"{value:,.0f}"
    return short
