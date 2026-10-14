"""產生一份模擬鼎新 ERP 匯出的「應收帳款帳齡分析表」xlsx，供測試與示範（數字皆為虛構）。"""
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font


def make(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "應收帳齡"
    ws.append(["亞洲永昌股份有限公司"])
    ws.merge_cells("A1:I1")
    ws.append(["應收帳款帳齡分析表"])
    ws.merge_cells("A2:I2")
    ws.append(["期間：2026/09/01~2026/09/30", None, None, None, None, None, "幣別：NTD", None, "列印日期：115/10/01"])
    ws.append([])
    # 兩列表頭：第 2 列是帳齡區間，第 1 列「帳齡」橫跨
    ws.append(["客戶代號", "客戶簡稱", "發票日期", "應收金額", "已收金額", "帳齡", None, None, "備註"])
    ws.append([None, None, None, None, None, "0-30天", "31-60天", "61天以上", None])
    ws.merge_cells("F5:H5")
    for c in "ABCDE":
        ws.merge_cells(f"{c}5:{c}6")
    ws["A5"].font = Font(bold=True)
    rows = [
        ("C001", "大華貿易", "1150903", "1,250,000", "1,000,000", "250,000", "0", "0", ""),
        ("C001", "大華貿易", "1150918", "860,500.00", "0", "860,500", "0", "0", ""),
        ("小計", None, None, "2,110,500", "1,000,000", "1,110,500", "0", "0", None),
        ("C002", "鴻光製鞋", "1150712", "430,000", "380,000", "0", "0", "50,000", "逾期催收中"),
        ("C002", "鴻光製鞋", "1150825", "(12,300)", "0", "0", "(12,300)", "0", "折讓"),
        ("小計", None, None, "417,700", "380,000", "0", "-12,300", "50,000", None),
        ("C003", "GreenX USA Inc.", "2026/09/28", "95,000", "0", "95,000", "0", "0", "美國子公司"),
        ("小計", None, None, "95,000", "0", "95,000", "0", "0", None),
        ("合計", None, None, "2,623,200", "1,380,000", "1,205,500", "-12,300", "50,000", None),
    ]
    for r in rows:
        ws.append(list(r))
    ws.append([])
    ws.append(["製表：財務部", None, None, None, "審核：", None, None, None, "第 1 頁 / 共 1 頁"])
    for col in "DEFGH":
        for cell in ws[col]:
            cell.alignment = Alignment(horizontal="right")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("sample_ar_aging.xlsx")
    print(make(out))
