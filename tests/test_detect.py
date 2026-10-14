import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "samples"))

from erp2notion.detect import build_report, classify_row, parse_date, parse_number  # noqa: E402
from erp2notion.reader import read_workbook  # noqa: E402
from erp2notion.render_notion import render_report  # noqa: E402
from erp2notion.render_html import render_html  # noqa: E402
from make_sample import make  # noqa: E402


def test_parse_number():
    assert parse_number("1,234.50") == 1234.5
    assert parse_number("(1,234)") == -1234
    assert parse_number("1,234-") == -1234
    assert parse_number("-12") == -12
    assert parse_number("12.5%") == 12.5
    assert parse_number("客戶") is None
    assert parse_number("C001") is None
    assert parse_number(True) is None


def test_parse_date_roc_and_iso():
    assert parse_date("1150930") == dt.date(2026, 9, 30)
    assert parse_date("115/09/30") == dt.date(2026, 9, 30)
    assert parse_date("2026/9/30") == dt.date(2026, 9, 30)
    assert parse_date("20260930") == dt.date(2026, 9, 30)
    assert parse_date("abc") is None


def test_classify_row():
    assert classify_row(["合計", None, "1,000"]) == "total"
    assert classify_row(["小計", None, "1,000"]) == "subtotal"
    assert classify_row(["大華貿易", None, None]) == "section"
    assert classify_row(["製表：財務部", None, "第 1 頁"]) == "footer"
    assert classify_row(["C001", "大華", "1,000"]) == "data"


def test_sample_end_to_end(tmp_path):
    path = make(tmp_path / "s.xlsx")
    report = build_report(read_workbook(path), path.name)
    t = report.tables[0]
    names = [c.name for c in t.columns]
    assert names[:5] == ["客戶代號", "客戶簡稱", "發票日期", "應收金額", "已收金額"]
    assert "帳齡 0-30天" in names and "帳齡 61天以上" in names
    assert report.meta["期間"] == "2026/09/01~2026/09/30"
    assert report.meta["幣別"] == "NTD"
    assert "應收帳款帳齡分析表" in report.title
    kinds = [r.kind for r in t.rows]
    assert kinds.count("data") == 5 and kinds.count("subtotal") == 3 and kinds.count("total") == 1
    # 欄位型別
    kind_of = {c.name: c.kind for c in t.columns}
    assert kind_of["應收金額"] == "number" and kind_of["發票日期"] == "date" and kind_of["客戶代號"] == "code"
    # 負數與民國日期
    row2 = t.rows[4]
    assert row2.cells[3] == -12300.0 and row2.cells[2] == "2026-08-25"
    # 合計檢核：明細加總 = 合計 → 不應有差異提醒
    assert not any("合計列" in w for w in report.warnings), report.warnings
    # 頁尾不進資料
    assert not any("製表" in str(r.cells) for r in t.rows)
    assert any("製表" in n for n in report.notes)

    md = render_report(report)
    assert '<table fit-page-width="true" header-row="true"' in md
    assert '<span color="red">' in md          # 負數紅字
    assert '<tr color="gray_bg">' in md         # 合計列
    assert "重點摘要" in md and "<columns>" in md
    assert "1,250,000" in md and "\\$" not in md
    html = render_html(report)
    assert "<table>" in html and "應收帳款帳齡分析表" in html


def test_total_mismatch_warning(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["測試報表"]); ws.append(["科目", "金額"])
    ws.append(["A", 100]); ws.append(["B", 200]); ws.append(["合計", 999])
    p = tmp_path / "m.xlsx"; wb.save(p)
    report = build_report(read_workbook(p), p.name)
    assert any("合計列" in w and "差" in w for w in report.warnings)


def test_large_table_chunks(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["客戶", "金額"])
    for i in range(250):
        ws.append([f"C{i:03d}", i * 10])
    ws.append(["合計", sum(i * 10 for i in range(250))])
    p = tmp_path / "big.xlsx"; wb.save(p)
    report = build_report(read_workbook(p), p.name)
    md = render_report(report, max_rows=100)
    assert md.count('{toggle="true"}') == 3
    assert "### 合計" in md
