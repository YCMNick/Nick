"""Report → 單檔 HTML 預覽（Nick 在寫進 Notion 前先看一眼；版面模擬 Notion 效果）。"""
from __future__ import annotations

import datetime as dt
import html

from .format import fmt_cell, is_negative, kpi_value
from .model import Report, Table

CSS = """
:root{--bg:#fff;--fg:#37352f;--muted:#787774;--line:#e9e9e7;--gray:#f1f1ef;--blue:#e7f3f8;--red:#e03e3e;--callout:#e7f3f8}
@media (prefers-color-scheme:dark){:root{--bg:#191919;--fg:#d4d4d4;--muted:#9b9b9b;--line:#333;--gray:#2a2a2a;--blue:#1e2a33;--callout:#1e2a33}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"Segoe UI","Noto Sans TC","PingFang TC",sans-serif;max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:28px;margin:0 0 16px}h2{font-size:20px;margin:28px 0 8px}
.callout{background:var(--callout);border-radius:6px;padding:14px 16px;display:flex;gap:12px}.callout .ic{font-size:22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:8px 0 20px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:12px 14px}.kpi .v{font-size:24px;font-weight:600}.kpi .n{color:var(--muted);font-size:13px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:left}th{background:var(--gray);font-weight:600;position:sticky;top:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}td.neg{color:var(--red)}
tr.total td,tr.subtotal td{background:var(--gray);font-weight:600}tr.section td{background:var(--blue);font-weight:600}
td:first-child,th:first-child{position:sticky;left:0;background:var(--gray)}
details{margin-top:24px;color:var(--muted)}summary{cursor:pointer}.warn{color:#d9730d}
.meta{color:var(--muted);font-size:13px}
"""


def render_html(report: Report) -> str:
    parts = [f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>{html.escape(report.title)}</title><style>{CSS}</style></head><body>"]
    parts.append(f"<h1>📊 {html.escape(report.title)}</h1>")
    meta = "　｜　".join(f"{html.escape(k)}：{html.escape(v)}" for k, v in report.meta.items())
    parts.append(f"<div class='callout'><div class='ic'>📊</div><div>{meta}<br><span class='meta'>明細筆數 {report.total_rows_count():,}　｜　匯入時間 {dt.datetime.now():%Y-%m-%d %H:%M}</span></div></div>")
    kpis = []
    for t in report.tables:
        totals = [r for r in t.rows if r.kind == "total"]
        if totals:
            for j in t.numeric_columns():
                v = totals[-1].cells[j]
                if isinstance(v, float) and t.columns[j].kind == "number":
                    cls = " style='color:var(--red)'" if v < 0 else ""
                    kpis.append(f"<div class='kpi'><div class='v'{cls}>{html.escape(kpi_value(v))}</div><div class='n'>{html.escape(t.columns[j].name)}　{v:,.0f}</div></div>")
    if kpis:
        parts.append("<h2>重點摘要</h2><div class='kpis'>" + "".join(kpis[:6]) + "</div>")
    for t in report.tables:
        if t.rows:
            parts.append(f"<h2>{html.escape(t.name)}</h2>" + _table(t))
    if report.notes or report.warnings:
        parts.append("<details><summary>原始資料備註</summary><ul>")
        parts.append(f"<li>來源檔案：{html.escape(report.source_file)}</li>")
        parts.extend(f"<li>{html.escape(n)}</li>" for n in report.notes)
        parts.extend(f"<li class='warn'>⚠️ {html.escape(w)}</li>" for w in report.warnings)
        parts.append("</ul></details>")
    parts.append("</body></html>")
    return "".join(parts)


def _table(t: Table) -> str:
    out = ["<div class='wrap'><table><thead><tr>"]
    out += [f"<th>{html.escape(c.name)}</th>" for c in t.columns]
    out.append("</tr></thead><tbody>")
    for r in t.rows:
        out.append(f"<tr class='{r.kind}'>")
        for j, c in enumerate(t.columns):
            v = r.cells[j] if j < len(r.cells) else None
            cls = []
            if c.kind in ("number", "percent"):
                cls.append("num")
            if is_negative(v):
                cls.append("neg")
            out.append(f"<td class='{' '.join(cls)}'>{html.escape(fmt_cell(v, c))}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)
