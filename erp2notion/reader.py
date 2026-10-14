"""讀取 .xlsx / .xls / .csv，輸出每個工作表的二維 grid（已把合併儲存格的值往右/往下補齊）。"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

Grid = list[list[Any]]

CSV_ENCODINGS = ("utf-8-sig", "cp950", "big5hkscs", "utf-16", "gb18030")


def read_workbook(path: str | Path) -> dict[str, Grid]:
    """回傳 {sheet_name: grid}。不存在/空白的工作表會被略過。"""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xltx"):
        return _read_xlsx(path)
    if suffix == ".xls":
        return _read_xls(path)
    if suffix in (".csv", ".txt", ".tsv"):
        return {path.stem: _read_csv(path)}
    raise ValueError(f"不支援的檔案格式：{suffix}（支援 .xlsx .xls .csv）")


def _read_xlsx(path: Path) -> dict[str, Grid]:
    import openpyxl

    # data_only=True：公式取已計算值（鼎新匯出通常是值，不是公式）
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    sheets: dict[str, Grid] = {}
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        grid: Grid = [[c.value for c in row] for row in ws.iter_rows()]
        # 合併儲存格：把左上角的值補到整個範圍（表頭常見「本期」橫跨兩欄）
        for rng in ws.merged_cells.ranges:
            top = grid[rng.min_row - 1][rng.min_col - 1] if rng.min_row - 1 < len(grid) else None
            for r in range(rng.min_row - 1, min(rng.max_row, len(grid))):
                for c in range(rng.min_col - 1, rng.max_col):
                    if c < len(grid[r]):
                        grid[r][c] = top
        grid = _trim(grid)
        if grid:
            sheets[ws.title] = grid
    return sheets


def _read_xls(path: Path) -> dict[str, Grid]:
    try:
        import xlrd
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("讀 .xls 需要 xlrd：pip install xlrd") from e
    wb = xlrd.open_workbook(str(path), formatting_info=False)
    sheets: dict[str, Grid] = {}
    for ws in wb.sheets():
        grid: Grid = []
        for r in range(ws.nrows):
            row = []
            for c in range(ws.ncols):
                cell = ws.cell(r, c)
                v = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    import datetime as dt
                    v = dt.datetime(*xlrd.xldate_as_tuple(v, wb.datemode))
                elif cell.ctype == xlrd.XL_CELL_EMPTY:
                    v = None
                row.append(v)
            grid.append(row)
        grid = _trim(grid)
        if grid:
            sheets[ws.name] = grid
    return sheets


def _read_csv(path: Path) -> Grid:
    raw = path.read_bytes()
    text = None
    for enc in CSV_ENCODINGS:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    rows = [[(c if c != "" else None) for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    return _trim(rows)


def _trim(grid: Grid) -> Grid:
    """去掉全空的尾端列與尾端欄，並把每列補齊到同寬。"""
    def empty(v: Any) -> bool:
        return v is None or (isinstance(v, str) and v.strip() == "")

    while grid and all(empty(v) for v in grid[-1]):
        grid.pop()
    if not grid:
        return []
    width = max(len(r) for r in grid)
    grid = [list(r) + [None] * (width - len(r)) for r in grid]
    while width > 0 and all(empty(r[width - 1]) for r in grid):
        width -= 1
    return [r[:width] for r in grid]
