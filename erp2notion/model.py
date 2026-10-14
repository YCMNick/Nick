from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ColumnKind = Literal["text", "number", "percent", "date", "code"]
RowKind = Literal["data", "subtotal", "total", "section"]


@dataclass
class Column:
    name: str
    kind: ColumnKind = "text"
    decimals: int = 0          # 數值欄位顯示小數位數
    source_index: int = 0      # 原始 Excel 欄位 index（0-based）


@dataclass
class Row:
    cells: list[Any]
    kind: RowKind = "data"
    source_row: int = 0        # 原始 Excel 列號（1-based）


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: list[Row] = field(default_factory=list)
    sheet: str = ""

    @property
    def data_rows(self) -> list[Row]:
        return [r for r in self.rows if r.kind == "data"]

    @property
    def total_rows(self) -> list[Row]:
        return [r for r in self.rows if r.kind in ("total", "subtotal")]

    def numeric_columns(self) -> list[int]:
        return [i for i, c in enumerate(self.columns) if c.kind in ("number", "percent")]


@dataclass
class Report:
    title: str
    source_file: str
    meta: dict[str, str] = field(default_factory=dict)   # 公司、期間、幣別、列印日期…
    tables: list[Table] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # 原始標題列 / 頁尾文字，供「原始資料備註」
    warnings: list[str] = field(default_factory=list)    # 辨識過程的提醒，給 Nick 看

    def total_rows_count(self) -> int:
        return sum(len(t.data_rows) for t in self.tables)
