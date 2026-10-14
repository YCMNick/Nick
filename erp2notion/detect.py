"""把鼎新 ERP 匯出的 raw grid 辨識成結構化 Table。

鼎新（Workflow ERP / TIPTOP / 智慧 ERP）匯出的 Excel 常見特徵：
  1. 前 1~5 列是「公司名稱 / 報表名稱 / 期間 / 列印日期 / 頁次」等標題列
  2. 表頭可能佔 1~2 列（例如「本期」橫跨「借方、貸方」）
  3. 數字常以文字匯出：'1,234,567.00'、'(1,234)'、'-1,234'、'1,234-'
  4. 日期可能是民國年：'1150930'、'115/09/30'、'115.09.30'
  5. 中間有「小計」列、最後有「合計 / 總計」列
  6. 只有第一欄有字、其餘空白的列 = 分組標題（客戶、科目、部門…）
  7. 頁尾有「製表 / 審核 / 核准」或「第 x 頁」
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .model import Column, ColumnKind, Report, Row, Table
from .reader import Grid

TOTAL_RE = re.compile(r"^(總計|總合計|合\s*計|總\s*額|Grand\s*Total|Total)\s*[:：]?$", re.I)
SUBTOTAL_RE = re.compile(r"(小\s*計|Sub\s*total|小結)", re.I)
TOTAL_ANYWHERE_RE = re.compile(r"(總計|合計|總額|Grand\s*Total|^Total)", re.I)
FOOTER_RE = re.compile(r"(製表|審核|核准|覆核|列印者|列印日期|印表日期|第\s*\d+\s*頁|Page\s*\d+|頁次|報表代號|程式代號)", re.I)
META_KEYS = {
    "期間": re.compile(r"(期間|日期區間|起迄|From|自\s*\d)", re.I),
    "幣別": re.compile(r"(幣別|Currency|NTD|TWD|USD)", re.I),
    "列印日期": re.compile(r"(列印日期|印表日期|Print\s*Date)", re.I),
    "公司": re.compile(r"(公司|股份|有限|Inc\.?|Co\.|Corp)", re.I),
    "報表名稱": re.compile(r"(表|報表|明細|彙總|統計|Report|Statement|Aging)", re.I),
}
NUM_RE = re.compile(r"^\(?-?[\d,]+(\.\d+)?\)?-?%?$")
ROC_DATE_RE = re.compile(r"^(\d{2,3})[/.\-](\d{1,2})[/.\-](\d{1,2})$")
ROC_COMPACT_RE = re.compile(r"^\d{7}$")
ISO_DATE_RE = re.compile(r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})")
CODE_HINT_RE = re.compile(r"(代號|編號|代碼|單號|料號|No\.?|ID|Code)", re.I)
DATE_HINT_RE = re.compile(r"(日期|日|Date)", re.I)
PERCENT_HINT_RE = re.compile(r"(%|率|比例|占比|佔比|Ratio|Rate|Pct)", re.I)


def is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def parse_number(v: Any) -> float | None:
    """'1,234.50' / '(1,234)' / '1,234-' / 12.3 → float；非數字回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace("，", ",").replace("＄", "").replace("$", "").replace("NT", "")
    if not s or not NUM_RE.match(s):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.endswith("%"):
        s = s[:-1]
    s = s.replace(",", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def parse_date(v: Any) -> dt.date | None:
    """西元或民國日期 → date。"""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)) and 1000101 <= v <= 1999999:
        v = str(int(v))
    if not isinstance(v, str):
        return None
    s = v.strip()
    m = ISO_DATE_RE.match(s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _safe_date(y, mo, d)
    m = ROC_DATE_RE.match(s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _safe_date(y + 1911, mo, d)
    if ROC_COMPACT_RE.match(s):
        return _safe_date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    if re.match(r"^\d{8}$", s):
        return _safe_date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return None


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


# ---------- 結構辨識 ----------

def _row_profile(row: list[Any]) -> tuple[int, int, int]:
    """回 (非空格數, 數字格數, 文字格數)。"""
    filled = numeric = text = 0
    for v in row:
        if is_empty(v):
            continue
        filled += 1
        if parse_number(v) is not None:
            numeric += 1
        else:
            text += 1
    return filled, numeric, text


def find_header(grid: Grid, max_scan: int = 25) -> tuple[int, int]:
    """回 (表頭起始列 idx, 表頭列數)。找「文字格最多且後面跟著含數字的資料列」的列。"""
    width = len(grid[0]) if grid else 0
    best, best_score = 0, -1.0
    for i in range(min(max_scan, len(grid))):
        filled, numeric, text = _row_profile(grid[i])
        if filled < 2 or width == 0:
            continue
        # 表頭：文字為主、填滿率高
        score = text / width - numeric * 0.5
        # 後方 1~3 列內有數字資料 → 加分
        look = grid[i + 1 : i + 4]
        if any(_row_profile(r)[1] > 0 for r in look):
            score += 0.5
        if score > best_score:
            best, best_score = i, score
    # 表頭可能延伸：下一列仍全是文字且無數字 → 併入
    span = 1
    while best + span < len(grid):
        filled, numeric, text = _row_profile(grid[best + span])
        if filled >= 2 and numeric == 0 and span < 3 and not _looks_like_section(grid[best + span]):
            span += 1
        else:
            break
    return best, span


def _looks_like_section(row: list[Any]) -> bool:
    filled, _, _ = _row_profile(row)
    return filled == 1 and not is_empty(row[0]) if row else False


def merge_headers(grid: Grid, start: int, span: int) -> list[str]:
    width = len(grid[0])
    names: list[str] = []
    for c in range(width):
        parts: list[str] = []
        for r in range(start, start + span):
            v = grid[r][c]
            if not is_empty(v):
                s = str(v).strip().replace("\n", " ")
                if s not in parts:
                    parts.append(s)
        names.append(" ".join(parts) if parts else f"欄{c + 1}")
    # 重名加序號
    seen: dict[str, int] = {}
    for i, n in enumerate(names):
        if n in seen:
            seen[n] += 1
            names[i] = f"{n}({seen[n]})"
        else:
            seen[n] = 1
    return names


def classify_row(row: list[Any]) -> str:
    filled, numeric, text = _row_profile(row)
    texts = [str(v).strip() for v in row if not is_empty(v) and parse_number(v) is None]
    joined = " ".join(texts)
    if filled == 0:
        return "empty"
    if FOOTER_RE.search(joined) and numeric <= 1:
        return "footer"
    if any(TOTAL_RE.match(t) for t in texts) or (TOTAL_ANYWHERE_RE.search(joined) and numeric > 0 and text <= 2):
        return "total"
    if SUBTOTAL_RE.search(joined) and numeric > 0:
        return "subtotal"
    if _looks_like_section(row):
        return "section"
    return "data"


def infer_column_kind(name: str, values: list[Any]) -> tuple[ColumnKind, int]:
    vals = [v for v in values if not is_empty(v)]
    if not vals:
        return ("text", 0)
    if CODE_HINT_RE.search(name):
        return ("code", 0)
    dates = sum(1 for v in vals if parse_date(v) is not None)
    nums = [parse_number(v) for v in vals]
    num_ok = sum(1 for n in nums if n is not None)
    if DATE_HINT_RE.search(name) and dates / len(vals) >= 0.6:
        return ("date", 0)
    if num_ok / len(vals) >= 0.8:
        if PERCENT_HINT_RE.search(name) or all(isinstance(v, str) and v.strip().endswith("%") for v in vals):
            return ("percent", 2)
        decimals = 0
        for v in vals:
            s = str(v).strip().rstrip("-").strip("()")
            if isinstance(v, float) and not v.is_integer():
                decimals = max(decimals, 2)
            elif "." in s:
                frac = s.split(".")[-1].replace(",", "")
                if frac.strip("0"):
                    decimals = max(decimals, min(len(frac), 4))
        return ("number", decimals)
    if dates / len(vals) >= 0.8:
        return ("date", 0)
    return ("text", 0)


def extract_meta(title_rows: list[list[Any]]) -> tuple[dict[str, str], list[str]]:
    meta: dict[str, str] = {}
    notes: list[str] = []
    for row in title_rows:
        cells: list[str] = []
        for v in row:
            if not is_empty(v) and (not cells or str(v).strip() != cells[-1]):
                cells.append(str(v).strip())   # 合併儲存格補值後會連續重複，去掉
        if not cells:
            continue
        line = "　".join(cells)
        notes.append(line)
        for cell in cells:
            for key, rx in META_KEYS.items():
                if key not in meta and rx.search(cell):
                    # 「期間：2026/09/01~2026/09/30」→ 去掉標籤
                    val = re.sub(r"^[^:：]*[:：]\s*", "", cell) if re.search(r"[:：]", cell) else cell
                    if key == "列印日期":
                        d = parse_date(val)
                        val = d.strftime("%Y/%m/%d") if d else val   # 民國 → 西元
                    meta[key] = val
                    break
    return meta, notes


def build_table(grid: Grid, sheet: str, profile: dict | None = None) -> tuple[Table, dict[str, str], list[str], list[str]]:
    """單一工作表 → Table + meta + notes + warnings。profile 可覆寫 header_row / header_span / rename / kinds / drop_columns。"""
    profile = profile or {}
    warnings: list[str] = []
    if profile.get("header_row") is not None:
        hstart = int(profile["header_row"]) - 1
        hspan = int(profile.get("header_span", 1))
    else:
        hstart, hspan = find_header(grid)
    names = merge_headers(grid, hstart, hspan)
    for old, new in (profile.get("rename") or {}).items():
        names = [new if n == old else n for n in names]

    meta, notes = extract_meta(grid[:hstart])
    body = grid[hstart + hspan :]

    rows: list[Row] = []
    footer_notes: list[str] = []
    for offset, raw in enumerate(body):
        kind = classify_row(raw)
        if kind == "empty":
            continue
        if kind == "footer":
            footer_notes.append("　".join(str(v).strip() for v in raw if not is_empty(v)))
            continue
        rows.append(Row(cells=list(raw), kind=kind, source_row=hstart + hspan + offset + 1))
    notes.extend(footer_notes)

    # 欄位型別：只用 data 列推斷
    data_cells = [r.cells for r in rows if r.kind == "data"]
    columns: list[Column] = []
    for c, name in enumerate(names):
        col_vals = [r[c] for r in data_cells if c < len(r)]
        kind, decimals = infer_column_kind(name, col_vals)
        forced = (profile.get("kinds") or {}).get(name)
        if forced:
            kind = forced
            if kind in ("number", "percent") and decimals == 0:
                decimals = int(profile.get("decimals", 0))
        columns.append(Column(name=name, kind=kind, decimals=decimals, source_index=c))

    # 刪除全空欄 / profile 指定欄
    drop = set(profile.get("drop_columns") or [])
    keep_idx = [
        i for i, col in enumerate(columns)
        if col.name not in drop and any(not is_empty(r.cells[i]) for r in rows if i < len(r.cells))
    ]
    columns = [columns[i] for i in keep_idx]
    for r in rows:
        r.cells = [r.cells[i] if i < len(r.cells) else None for i in keep_idx]

    # 轉值：數字欄 → float、日期欄 → date、其它 → str
    for r in rows:
        for j, col in enumerate(columns):
            v = r.cells[j]
            if is_empty(v):
                r.cells[j] = None
                continue
            if col.kind in ("number", "percent"):
                n = parse_number(v)
                if n is None and r.kind == "data":
                    warnings.append(f"[{sheet}] 第 {r.source_row} 列「{col.name}」= {v!r} 不是數字，保留原文")
                    r.cells[j] = str(v).strip()
                else:
                    r.cells[j] = n if n is not None else str(v).strip()
            elif col.kind == "date":
                d = parse_date(v)
                r.cells[j] = d.isoformat() if d else str(v).strip()
            else:
                r.cells[j] = str(v).strip() if not isinstance(v, (int, float)) else _fmt_plain(v)

    # 合計列檢核：和 data 列加總比對（主管看的數字不能錯）
    for ti, tr in enumerate(rows):
        if tr.kind != "total":
            continue
        for j, col in enumerate(columns):
            if col.kind != "number" or not isinstance(tr.cells[j], float):
                continue
            s = sum(r.cells[j] for r in rows if r.kind == "data" and isinstance(r.cells[j], float))
            if abs(s - tr.cells[j]) > 0.5 and s != 0:
                warnings.append(
                    f"[{sheet}] 合計列（第 {tr.source_row} 列）「{col.name}」= {tr.cells[j]:,.2f}，"
                    f"但明細加總 = {s:,.2f}，差 {tr.cells[j] - s:,.2f}（可能含小計重複或有隱藏列）"
                )
            break  # 檢查一欄就夠當提醒

    table_name = profile.get("table_name") or meta.get("報表名稱") or sheet
    if not rows:
        warnings.append(f"[{sheet}] 沒有辨識到資料列，請確認表頭位置（可用 profile 指定 header_row）")
    return Table(name=table_name, columns=columns, rows=rows, sheet=sheet), meta, notes, warnings


def _fmt_plain(v: int | float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def build_report(sheets: dict[str, Grid], source_file: str, profile: dict | None = None,
                 title: str | None = None) -> Report:
    profile = profile or {}
    report = Report(title=title or "", source_file=source_file)
    sheet_profiles = profile.get("sheets") or {}
    only = profile.get("only_sheets")
    for sheet, grid in sheets.items():
        if only and sheet not in only:
            continue
        sp = {**{k: v for k, v in profile.items() if k != "sheets"}, **sheet_profiles.get(sheet, {})}
        table, meta, notes, warns = build_table(grid, sheet, sp)
        report.tables.append(table)
        for k, v in meta.items():
            report.meta.setdefault(k, v)
        report.notes.extend(n for n in notes if n not in report.notes)
        report.warnings.extend(warns)
    if not report.title:
        base = report.meta.get("報表名稱") or (report.tables[0].name if report.tables else source_file)
        period = report.meta.get("期間")
        report.title = f"{base}｜{period}" if period else base
    report.meta.setdefault("資料來源", profile.get("source_label", "鼎新 ERP 匯出"))
    return report
