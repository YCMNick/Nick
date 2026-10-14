"""erp2notion — 鼎新 ERP Excel 匯出檔 → Notion 主管檢視表格。

流程：reader(讀檔) → detect(辨識標題/表頭/合計) → model(結構化) → render(Notion Markdown / HTML / JSON) → push(Notion API)
"""
__version__ = "0.1.0"
