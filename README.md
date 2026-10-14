# erp2notion — 鼎新 ERP Excel → Notion 主管檢視表格

把鼎新 ERP（Workflow / TIPTOP / 智慧 ERP）匯出的財務 Excel，自動整理成主管、老闆可直接在 Notion 閱讀的頁面。

## 結論：怎麼用

**日常流程（Nick → Claude）**
1. 把鼎新匯出的 `.xlsx / .xls / .csv` 丟給 Claude
2. Claude 跑 `inspect` 確認表頭、合計列、欄位型別；有疑慮會先列「⚠️ 提醒」
3. Claude 產出 HTML 預覽給 Nick 看一眼
4. Nick 確認後，Claude 用 Notion MCP 把 Markdown 寫到指定頁面

**自己跑**
```bash
pip install -r requirements.txt
python -m erp2notion inspect 報表.xlsx                       # 看辨識結果
python -m erp2notion render  報表.xlsx -f html -o out.html   # HTML 預覽
python -m erp2notion render  報表.xlsx -f md   -o out.md     # Notion Markdown（貼給 Notion MCP）
export NOTION_TOKEN=secret_xxx
python -m erp2notion push    報表.xlsx --parent <父頁面ID> --mode table      # 直接寫入 Notion
python -m erp2notion push    報表.xlsx --parent <父頁面ID> --mode database   # 大量資料改用 database
```

## Notion 頁面長相（主管視角）

| 區塊 | 內容 |
|---|---|
| 📊 Callout | 報表名稱、資料來源、公司、期間、幣別、列印日期、明細筆數、匯入時間 |
| 重點摘要 | 合計列的數值欄做成 KPI（萬 / 億縮寫 + 完整數字），負數紅字 |
| 表格 | 表頭列 + 第一欄凍結；千分位；小計／合計灰底粗體；分組列藍底；負數紅字 |
| 原始資料備註（收合） | 鼎新匯出的標題列、頁尾（製表／審核／頁次）、辨識提醒 |

超過 100 列會自動分段放進可收合的「第 1–100 筆」標題，合計列獨立放最後。

## 自動處理的鼎新匯出特徵

- 前幾列的公司名／報表名／期間／幣別／列印日期 → 抓進 meta，不進表格
- 1～3 列的多層表頭（含合併儲存格）→ 合併成「帳齡 0-30天」這類欄名
- 文字型數字 `1,234.00`、`(1,234)`、`1,234-`、`12.5%` → 數值
- 民國日期 `1150930`、`115/09/30` → `2026-09-30`
- 小計／合計／總計列、分組列、頁尾列自動辨識
- **合計檢核**：合計列與明細加總不符會出提醒（主管看的數字不能錯）
- 全空欄自動刪除；`.csv` 自動偵測 Big5 / UTF-8

## 自動辨識不準時：profile

在 `profiles/` 放 YAML，用 `--profile 名稱` 指定：

```yaml
header_row: 7            # 表頭在第 7 列
header_span: 2           # 表頭佔 2 列
table_name: 應收帳款帳齡分析表
drop_columns: [備註]
rename: {客戶代號: 客戶編號}
kinds: {逾期天數: number, 占比: percent}
only_sheets: [Sheet1]
sheets:
  Sheet2: {header_row: 5}
```

## 專案結構

```
erp2notion/
  reader.py         讀 xlsx / xls / csv，合併儲存格補值
  detect.py         辨識標題列、表頭、合計列、欄位型別、合計檢核
  model.py          Report / Table / Column / Row
  format.py         千分位、負數、KPI 縮寫、Notion 跳脫
  render_notion.py  → Notion-flavored Markdown（給 Notion MCP）
  render_html.py    → HTML 預覽
  notion_api.py     → 直接呼叫 Notion API（table / database 兩種模式）
  profiles.py       讀 profiles/*.yaml
  cli.py            inspect / render / push
profiles/           報表 profile
samples/            make_sample.py 產生模擬鼎新匯出檔（虛構數據）
tests/              pytest
```

## 限制與注意

- 鼎新匯出若是「列印版」Excel（每頁重複表頭），每頁表頭會被當資料列；請改用「資料匯出」或用 profile 處理
- Notion 表格不支援合併儲存格，多層表頭會攤平成單列
- 財務數字屬內部資料：Notion 目標頁面請設定好權限，`push` 模式的 `NOTION_TOKEN` 不要進 git
