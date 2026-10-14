"""報表 profile：針對特定鼎新報表覆寫辨識規則（YAML 或 JSON）。自動辨識失準時才需要。

可用欄位（皆選填）：
  header_row: 7            # 表頭在第幾列（1-based）；不填則自動偵測
  header_span: 2           # 表頭佔幾列
  table_name: 應收帳款帳齡表
  source_label: 鼎新 Workflow ERP
  only_sheets: [Sheet1]    # 只處理這些工作表
  drop_columns: [備註]
  rename: {客戶代號: 客戶編號}
  kinds: {帳款金額: number, 逾期天數: number, 占比: percent}
  decimals: 0
  sheets:                  # 針對個別工作表再覆寫
    Sheet2: {header_row: 5}
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"


def load_profile(name_or_path: str | None) -> dict:
    if not name_or_path:
        return {}
    p = Path(name_or_path)
    if not p.exists():
        for ext in (".yaml", ".yml", ".json"):
            cand = PROFILE_DIR / f"{name_or_path}{ext}"
            if cand.exists():
                p = cand
                break
    if not p.exists():
        raise FileNotFoundError(f"找不到 profile：{name_or_path}（可放在 {PROFILE_DIR}）")
    text = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        import yaml  # pip install pyyaml
        return yaml.safe_load(text) or {}
    return json.loads(text)


def list_profiles() -> list[str]:
    if not PROFILE_DIR.exists():
        return []
    return sorted(p.stem for p in PROFILE_DIR.iterdir() if p.suffix in (".yaml", ".yml", ".json"))
