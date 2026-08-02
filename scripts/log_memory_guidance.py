"""記憶體三雄 位元出貨量／ASP 指引記錄簿

為什麼要這個：位元出貨量(bit shipment)是判斷「需求是真的、還是純漲價」的唯一直接證據，
但它只出現在法說會，沒有 API。而 SK hynix / 三星的財報比 MU 早約兩個月——
先記下他們的下季指引，等於提前兩個月知道 MU 會說什麼。

用法：
    python scripts/log_memory_guidance.py --show          # 看對照表（預設）
    python scripts/log_memory_guidance.py --interactive   # 互動新增一筆
資料檔 data/memory_guidance.json 是純 JSON，也可以直接手動編輯。

★口徑雷：三家的財季錯開（MU 財年 8 月底結束，比 hynix/三星的日曆季早一個月），
  跨公司比 QoQ 時要對齊「期間」而不是「季度標籤」。period_end 欄位就是為此存在。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data" / "memory_guidance.json"

SEED = [
    {
        "company": "SK hynix",
        "quarter": "2026Q2",
        "period_end": "2026-06-30",
        "reported_on": "2026-07-28",
        "dram_bit_qoq_actual": "高個位數 %",
        "dram_asp_qoq_actual": "約 +30%",
        "dram_bit_qoq_guide_next": "約 +10%（加速）",
        "nand_bit_qoq_actual": "中十幾 %",
        "nand_asp_qoq_actual": "中 50 幾 %",
        "nand_bit_qoq_guide_next": "低個位數 %（急鈍化）",
        "note": "營收 79.32 兆韓元(QoQ +51%/YoY +257%)、營益率 76%；HBM4 Q2 進入量產出貨；"
        "與約 10 家客戶簽多年期 LTA。Q3 明講積極回應伺服器需求。",
        "source": "SK hynix Q2 2026 法說",
    },
    {
        "company": "Micron",
        "quarter": "FY26Q3",
        "period_end": "2026-05-28",
        "reported_on": "2026-06-下旬",
        "dram_bit_qoq_actual": "低個位數 %",
        "dram_asp_qoq_actual": "+60 幾 %（low-60s）",
        "dram_bit_qoq_guide_next": "（未記錄）",
        "nand_bit_qoq_actual": "中個位數 %",
        "nand_asp_qoq_actual": "+80 幾 %（mid-80s）",
        "nand_bit_qoq_guide_next": "（未記錄）",
        "note": "DRAM 營收 $31.3B＝總營收 76%，QoQ +67%(=1.03×1.62 量價相乘吻合)；"
        "單季毛利率 84.6%；FY26 capex 上調至約 $27B。",
        "source": "MU FQ3-2026 法說＋SEC XBRL",
    },
]

FIELDS = [
    ("company", "公司（SK hynix / Samsung / Micron）"),
    ("quarter", "季度標籤（如 2026Q3 / FY26Q4）"),
    ("period_end", "期間結束日 YYYY-MM-DD（跨公司比較用這個對齊）"),
    ("reported_on", "公布日 YYYY-MM-DD"),
    ("dram_bit_qoq_actual", "DRAM 位元出貨量 QoQ 實績"),
    ("dram_asp_qoq_actual", "DRAM ASP QoQ 實績"),
    ("dram_bit_qoq_guide_next", "DRAM 位元出貨量 下季指引"),
    ("nand_bit_qoq_actual", "NAND 位元出貨量 QoQ 實績"),
    ("nand_asp_qoq_actual", "NAND ASP QoQ 實績"),
    ("nand_bit_qoq_guide_next", "NAND 位元出貨量 下季指引"),
    ("note", "備註（營收/毛利率/長約/HBM 進度等）"),
    ("source", "來源"),
]


def load():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"updated": "", "entries": list(SEED)}


def save(d):
    d["updated"] = datetime.now().isoformat()
    d["entries"].sort(key=lambda e: (e.get("period_end") or "", e.get("company") or ""))
    DATA_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def show(d):
    entries = d["entries"]
    if not entries:
        print("（尚無資料）")
        return
    print(f"\n{'=' * 96}")
    print("記憶體三雄 位元出貨量／ASP 對照（按期間結束日排序）")
    print(f"{'=' * 96}")
    for e in entries:
        print(
            f"\n■ {e['company']}  {e['quarter']}   期間結束 {e['period_end']}   公布 {e['reported_on']}"
        )
        print(
            f"   DRAM  量 QoQ 實績 {e['dram_bit_qoq_actual']:<16s} ASP {e['dram_asp_qoq_actual']:<16s}"
            f" → 下季量指引 {e['dram_bit_qoq_guide_next']}"
        )
        print(
            f"   NAND  量 QoQ 實績 {e['nand_bit_qoq_actual']:<16s} ASP {e['nand_asp_qoq_actual']:<16s}"
            f" → 下季量指引 {e['nand_bit_qoq_guide_next']}"
        )
        if e.get("note"):
            print(f"   註：{e['note']}")
        print(f"   來源：{e.get('source', '')}")

    print(f"\n{'-' * 96}")
    print(
        "判讀提示：DRAM 量加速＋NAND 量鈍化＝AI 端獨撐、消費端未回溫（利 MU、不利純 NAND 的 SNDK）；"
    )
    print(
        "          量價同時收斂＝週期反轉確認；量起來但 ASP 收斂＝健康的擴張，非泡沫。"
    )
    print(f"{'-' * 96}\n")


def interactive(d):
    print("新增一筆（直接 Enter 可跳過該欄）")
    rec = {}
    for key, prompt in FIELDS:
        rec[key] = input(f"  {prompt}: ").strip() or "（未記錄）"
    d["entries"].append(rec)
    save(d)
    print(f"\n已寫入 {DATA_FILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="顯示對照表（預設）")
    ap.add_argument("--interactive", action="store_true", help="互動新增一筆")
    args = ap.parse_args()

    d = load()
    if not DATA_FILE.exists():
        save(d)
        print(f"已建立 {DATA_FILE}（含 SK hynix 2026Q2 與 MU FY26Q3 種子資料）")

    if args.interactive:
        interactive(d)
    else:
        show(d)


if __name__ == "__main__":
    main()
