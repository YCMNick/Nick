"""直接用 Notion 官方 API 寫入（不經 MCP 時使用）。需要環境變數 NOTION_TOKEN。

兩種模式：
  table    → 在父頁面下建子頁，內容為 callout + heading + table block（適合 ≤ 300 列、純閱讀）
  database → 在父頁面下建 database，每列一筆 page（適合要排序/篩選/大量資料）
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

from .format import fmt_cell, is_negative
from .model import Report, Table

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
CHUNK = 100          # Notion 一次 append 最多 100 個 block
CELL_LIMIT = 2000    # rich_text 單格上限


class NotionClient:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("NOTION_TOKEN")
        if not self.token:
            raise RuntimeError("缺少 NOTION_TOKEN（Notion → Settings → Connections → Develop or manage integrations）")
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        })

    def _req(self, method: str, path: str, **kw) -> dict[str, Any]:
        for attempt in range(5):
            r = self.s.request(method, f"{API}{path}", timeout=60, **kw)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", "1")) + 0.2)
                continue
            if r.status_code >= 500 and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            if not r.ok:
                raise RuntimeError(f"Notion API {r.status_code}: {r.text[:500]}")
            time.sleep(0.35)  # 官方上限約 3 req/s
            return r.json()
        raise RuntimeError("Notion API 連續重試失敗")

    # ---------- blocks ----------
    def create_page(self, parent_page_id: str, title: str, icon: str = "📊") -> str:
        body = {
            "parent": {"page_id": parent_page_id},
            "icon": {"type": "emoji", "emoji": icon},
            "properties": {"title": {"title": rt(title)}},
        }
        return self._req("POST", "/pages", json=body)["id"]

    def append(self, block_id: str, children: list[dict]) -> list[dict]:
        created: list[dict] = []
        for i in range(0, len(children), CHUNK):
            res = self._req("PATCH", f"/blocks/{block_id}/children", json={"children": children[i : i + CHUNK]})
            created.extend(res.get("results", []))
        return created

    # ---------- database ----------
    def create_database(self, parent_page_id: str, title: str, table: Table) -> str:
        props: dict[str, Any] = {}
        title_col = table.columns[0].name
        for c in table.columns:
            if c.name == title_col:
                props[c.name] = {"title": {}}
            elif c.kind in ("number", "percent"):
                props[c.name] = {"number": {"format": "percent" if c.kind == "percent" else "number_with_commas"}}
            elif c.kind == "date":
                props[c.name] = {"date": {}}
            else:
                props[c.name] = {"rich_text": {}}
        props["列別"] = {"select": {"options": [
            {"name": "明細", "color": "default"}, {"name": "小計", "color": "gray"},
            {"name": "合計", "color": "blue"}, {"name": "分組", "color": "purple"}]}}
        body = {"parent": {"type": "page_id", "page_id": parent_page_id},
                "title": rt(title), "properties": props, "is_inline": True}
        return self._req("POST", "/databases", json=body)["id"]

    def insert_rows(self, database_id: str, table: Table) -> int:
        kind_label = {"data": "明細", "subtotal": "小計", "total": "合計", "section": "分組"}
        n = 0
        for r in table.rows:
            props: dict[str, Any] = {"列別": {"select": {"name": kind_label[r.kind]}}}
            for j, c in enumerate(table.columns):
                v = r.cells[j] if j < len(r.cells) else None
                if j == 0:
                    props[c.name] = {"title": rt(str(v) if v is not None else "")}
                elif c.kind in ("number", "percent"):
                    if isinstance(v, float):
                        props[c.name] = {"number": v / 100 if c.kind == "percent" else v}
                elif c.kind == "date":
                    if v:
                        props[c.name] = {"date": {"start": str(v)}}
                else:
                    if v is not None:
                        props[c.name] = {"rich_text": rt(str(v))}
            self._req("POST", "/pages", json={"parent": {"database_id": database_id}, "properties": props})
            n += 1
        return n


# ---------- block builders ----------
def rt(text: str, bold: bool = False, color: str = "default") -> list[dict]:
    text = text[:CELL_LIMIT]
    return [{"type": "text", "text": {"content": text},
             "annotations": {"bold": bold, "color": color}}]


def report_blocks(report: Report) -> list[dict]:
    blocks: list[dict] = []
    lines = [f"{k}：{v}" for k, v in report.meta.items()]
    lines.append(f"明細筆數：{report.total_rows_count():,}")
    blocks.append({"object": "block", "type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "📊"}, "color": "blue_background",
        "rich_text": rt("\n".join([report.title] + lines))}})
    for t in report.tables:
        if not t.rows:
            continue
        blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": rt(t.name)}})
        blocks.append(table_block(t))
    if report.notes or report.warnings:
        children = [{"object": "block", "type": "bulleted_list_item",
                     "bulleted_list_item": {"rich_text": rt(n)}} for n in report.notes + [f"⚠️ {w}" for w in report.warnings]]
        blocks.append({"object": "block", "type": "toggle", "toggle": {
            "rich_text": rt("原始資料備註"), "children": children[:100]}})
    return blocks


def table_block(t: Table) -> dict:
    header = {"object": "block", "type": "table_row", "table_row": {
        "cells": [rt(c.name, bold=True) for c in t.columns]}}
    rows = [header]
    for r in t.rows:
        cells = []
        for j, c in enumerate(t.columns):
            v = r.cells[j] if j < len(r.cells) else None
            color = "red" if is_negative(v) else ("gray_background" if r.kind in ("total", "subtotal") else
                                                    "blue_background" if r.kind == "section" else "default")
            cells.append(rt(fmt_cell(v, c), bold=r.kind != "data", color=color))
        rows.append({"object": "block", "type": "table_row", "table_row": {"cells": cells}})
    return {"object": "block", "type": "table", "table": {
        "table_width": len(t.columns), "has_column_header": True, "has_row_header": True,
        "children": rows}}


def push_report(report: Report, parent_page_id: str, mode: str = "table", token: str | None = None) -> str:
    """回傳新頁面 URL。table block 若超過 100 列，會先建空 table 再分批 append rows。"""
    client = NotionClient(token)
    page_id = client.create_page(parent_page_id, report.title)
    if mode == "database":
        client.append(page_id, report_blocks_meta_only(report))
        for t in report.tables:
            if t.rows:
                db_id = client.create_database(page_id, t.name, t)
                client.insert_rows(db_id, t)
    else:
        blocks = report_blocks(report)
        for b in blocks:
            if b["type"] == "table" and len(b["table"]["children"]) > CHUNK:
                rows = b["table"]["children"]
                b["table"]["children"] = rows[:CHUNK]
                created = client.append(page_id, [b])
                tbl_id = next(x["id"] for x in created if x["type"] == "table")
                client.append(tbl_id, rows[CHUNK:])
            else:
                client.append(page_id, [b])
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def report_blocks_meta_only(report: Report) -> list[dict]:
    return [b for b in report_blocks(report) if b["type"] in ("callout", "toggle")]
