"""Report → Notion-flavored Markdown（給 Notion MCP create-pages / update-page 用）。

版面（主管視角）：
  1. Callout：資料來源 / 期間 / 幣別 / 更新時間 / 筆數
  2. 重點摘要：合計列的數字做成 KPI 欄位（3 欄）
  3. 每張表：heading + table（表頭列、第一欄凍結、合計列灰底粗體、負數紅字、分組列藍底）
  4. Toggle：原始資料備註（標題列、頁尾、辨識提醒）
"""
from __future__ import annotations

import datetime as dt

from .format import fmt_cell, is_negative, kpi_value, md_escape
from .model import Report, Row, Table

MAX_ROWS_PER_TABLE = 100   # Notion 單一 table block 建議上限；超過就分段放進 toggle


def render_report(report: Report, max_rows: int = MAX_ROWS_PER_TABLE, include_notes: bool = True) -> str:
    out: list[str] = []
    out.append(_callout(report))
    kpis = _kpi_block(report)
    if kpis:
        out.append("## 重點摘要")
        out.append(kpis)
    for t in report.tables:
        if not t.rows:
            continue
        out.append(f"## {md_escape(t.name)}")
        out.append(_table_blocks(t, max_rows))
    if include_notes and (report.notes or report.warnings):
        out.append(_notes_toggle(report))
    return "\n".join(out)


def _callout(report: Report) -> str:
    lines = [f"**{md_escape(report.title)}**"]
    order = ["資料來源", "公司", "期間", "幣別", "列印日期"]
    for k in order:
        if k in report.meta:
            lines.append(f"{k}：{md_escape(report.meta[k])}")
    lines.append(f"明細筆數：{report.total_rows_count():,}　｜　匯入時間：{dt.datetime.now():%Y-%m-%d %H:%M}")
    body = "\n\t".join(lines)
    return f'<callout icon="📊" color="blue_bg">\n\t{body}\n</callout>'


def _kpi_block(report: Report) -> str:
    """從每張表的最後一列 total 抓數值欄，做 columns KPI（最多 6 個）。"""
    items: list[tuple[str, float]] = []
    for t in report.tables:
        totals = [r for r in t.rows if r.kind == "total"]
        if not totals:
            continue
        tr = totals[-1]
        for j in t.numeric_columns():
            v = tr.cells[j]
            if isinstance(v, float) and t.columns[j].kind == "number":
                items.append((t.columns[j].name, v))
    items = items[:6]
    if not items:
        return ""
    cols = []
    for name, v in items:
        color = "red" if v < 0 else "default"
        cols.append(
            "\t<column>\n"
            f"\t\t### <span color=\"{color}\">{md_escape(kpi_value(v))}</span>\n"
            f"\t\t{md_escape(name)}　{md_escape(f'{v:,.0f}')}\n"
            "\t</column>"
        )
    # 每 3 個一組
    groups = [cols[i : i + 3] for i in range(0, len(cols), 3)]
    return "\n".join("<columns>\n" + "\n".join(g) + "\n</columns>" for g in groups)


def _table_blocks(t: Table, max_rows: int) -> str:
    rows = t.rows
    if len(rows) <= max_rows:
        return _table(t, rows)
    # 分段：每段一個 toggle heading，合計列獨立放最後
    body = [r for r in rows if r.kind != "total"]
    totals = [r for r in rows if r.kind == "total"]
    parts: list[str] = []
    for i in range(0, len(body), max_rows):
        chunk = body[i : i + max_rows]
        first = i + 1
        last = i + len(chunk)
        parts.append(f"### 第 {first:,}–{last:,} 筆（共 {len(body):,} 筆） {{toggle=\"true\"}}")
        parts.append(_indent(_table(t, chunk), 1))
    if totals:
        parts.append("### 合計")
        parts.append(_table(t, totals))
    return "\n".join(parts)


def _table(t: Table, rows: list[Row]) -> str:
    lines = ['<table fit-page-width="true" header-row="true" header-column="true">']
    lines.append("\t<tr>" + "".join(f"<td>**{md_escape(c.name)}**</td>" for c in t.columns) + "</tr>")
    for r in rows:
        row_color = ""
        if r.kind == "total":
            row_color = ' color="gray_bg"'
        elif r.kind == "subtotal":
            row_color = ' color="gray_bg"'
        elif r.kind == "section":
            row_color = ' color="blue_bg"'
        cells = []
        for j, col in enumerate(t.columns):
            v = r.cells[j] if j < len(r.cells) else None
            text = md_escape(fmt_cell(v, col))
            if r.kind in ("total", "subtotal", "section") and text:
                text = f"**{text}**"
            if is_negative(v):
                text = f'<span color="red">{text}</span>'
            cells.append(f"<td>{text}</td>")
        lines.append(f"\t<tr{row_color}>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _notes_toggle(report: Report) -> str:
    lines = ["<details>", "<summary>原始資料備註（鼎新匯出標題列 / 頁尾 / 辨識提醒）</summary>"]
    lines.append(f"- 來源檔案：{md_escape(report.source_file)}")
    for n in report.notes:
        lines.append(f"- {md_escape(n)}")
    for w in report.warnings:
        lines.append(f"- ⚠️ {md_escape(w)}")
    lines.append("</details>")
    return "\n".join(lines)


def _indent(block: str, level: int) -> str:
    pad = "\t" * level
    return "\n".join(pad + line for line in block.splitlines())
