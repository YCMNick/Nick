"""指令列介面。

  python -m erp2notion inspect  報表.xlsx                 # 看辨識結果（表頭、欄位型別、合計列、提醒）
  python -m erp2notion render   報表.xlsx -f md  -o out.md   # 產 Notion Markdown（給 Notion MCP 貼）
  python -m erp2notion render   報表.xlsx -f html -o out.html # 產 HTML 預覽
  python -m erp2notion render   報表.xlsx -f json -o out.json # 結構化 JSON
  python -m erp2notion push     報表.xlsx --parent <page_id> [--mode table|database]  # 直接寫進 Notion（需 NOTION_TOKEN）
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .detect import build_report
from .profiles import list_profiles, load_profile
from .reader import read_workbook


def load(path: str, profile: str | None, title: str | None):
    sheets = read_workbook(path)
    if not sheets:
        sys.exit(f"檔案沒有可讀的工作表：{path}")
    return build_report(sheets, Path(path).name, load_profile(profile), title)


def cmd_inspect(a):
    r = load(a.file, a.profile, a.title)
    print(f"標題　　：{r.title}")
    for k, v in r.meta.items():
        print(f"{k}：{v}")
    for t in r.tables:
        kinds = {"data": 0, "subtotal": 0, "total": 0, "section": 0}
        for row in t.rows:
            kinds[row.kind] += 1
        print(f"\n[工作表 {t.sheet}] 表名：{t.name}　明細 {kinds['data']} 列、小計 {kinds['subtotal']}、合計 {kinds['total']}、分組 {kinds['section']}")
        for c in t.columns:
            extra = f"（小數 {c.decimals}）" if c.kind in ("number", "percent") and c.decimals else ""
            print(f"  - {c.name:<20} {c.kind}{extra}")
        for row in t.rows[:3]:
            print("  例：", row.cells)
    if r.notes:
        print("\n原始標題/頁尾：")
        for n in r.notes:
            print("  ·", n)
    if r.warnings:
        print("\n⚠️ 提醒：")
        for w in r.warnings:
            print("  ·", w)


def cmd_render(a):
    r = load(a.file, a.profile, a.title)
    if a.format == "md":
        from .render_notion import render_report
        out = render_report(r, max_rows=a.max_rows)
    elif a.format == "html":
        from .render_html import render_html
        out = render_html(r)
    else:
        out = json.dumps(dataclasses.asdict(r), ensure_ascii=False, indent=2, default=str)
    if a.output:
        Path(a.output).write_text(out, encoding="utf-8")
        print(f"已輸出 {a.output}（{len(out):,} 字元）", file=sys.stderr)
    else:
        print(out)
    if r.warnings:
        print("\n⚠️ 提醒：", file=sys.stderr)
        for w in r.warnings:
            print("  ·", w, file=sys.stderr)


def cmd_push(a):
    from .notion_api import push_report
    r = load(a.file, a.profile, a.title)
    url = push_report(r, a.parent, mode=a.mode)
    print(url)


def main(argv=None):
    p = argparse.ArgumentParser(prog="erp2notion", description="鼎新 ERP Excel → Notion 主管檢視表格")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("file")
        sp.add_argument("--profile", "-p", help=f"報表 profile（現有：{', '.join(list_profiles()) or '無'}）")
        sp.add_argument("--title", "-t", help="覆寫 Notion 頁面標題")

    s = sub.add_parser("inspect", help="顯示辨識結果"); common(s); s.set_defaults(fn=cmd_inspect)
    s = sub.add_parser("render", help="輸出 md/html/json"); common(s)
    s.add_argument("--format", "-f", choices=["md", "html", "json"], default="md")
    s.add_argument("--output", "-o")
    s.add_argument("--max-rows", type=int, default=100, help="單一 Notion 表格最多列數，超過分段")
    s.set_defaults(fn=cmd_render)
    s = sub.add_parser("push", help="直接寫入 Notion（NOTION_TOKEN）"); common(s)
    s.add_argument("--parent", required=True, help="父頁面 ID")
    s.add_argument("--mode", choices=["table", "database"], default="table")
    s.set_defaults(fn=cmd_push)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
