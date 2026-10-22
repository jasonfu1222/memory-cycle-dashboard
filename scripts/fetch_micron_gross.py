import json, sys
import requests
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sec_xbrl import quarterly  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
MICRON_FILE = DATA_DIR / "micron_gross.json"

EDGAR_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000723125.json"
HEADERS = {"User-Agent": "memory-cycle-dashboard bot@memory-cycle.netlify.app"}


def fetch_facts():
    r = requests.get(EDGAR_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def extract_quarterly(facts, concept):
    """Return {end_date: {val, filed}}，單季值。

    ★2026-10-22 改走 sec_xbrl.quarterly：舊寫法只收 65~100 天的期間，10-K 只給全年，
      所以每年 8 月底那季（FQ4）永遠抓不到——10/01 s6a 就停在 FQ3 84.6%，實際 FQ4 86.8%。
      現在用「全年 − 前三季累計」補出第四季。
    ★filed 改為「這個數字第一次被申報的日子」：舊寫法取最後一次申報（下一年 10-Q 的比較欄），
      2024-02 那季被標成 2025-03 申報，舊季度看起來像新資料。
    """
    try:
        entries = facts[concept]["units"]["USD"]
    except KeyError:
        return {}
    q, _mismatch = quarterly(entries)
    # 連 filed 一起回傳：季末日不等於資訊到手日（FY26Q3 季末 5/28、公告 6/24 差 27 天），
    # 新鮮度要用「什麼時候能知道」而不是「涵蓋到哪天」，否則剛開牌的財報也會被判過期。
    return {k: {"val": v["val"], "filed": v["available"]} for k, v in q.items()}


def main():
    print("Fetching Micron gross margin from SEC EDGAR...")
    data = fetch_facts()
    facts = data.get("facts", {}).get("us-gaap", {})

    gross_profit = extract_quarterly(facts, "GrossProfit")

    revenue = {}
    for concept in [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ]:
        revenue = extract_quarterly(facts, concept)
        if revenue:
            break

    if not gross_profit or not revenue:
        print("ERROR: Could not extract GrossProfit or Revenue", file=sys.stderr)
        sys.exit(1)

    margins = []
    for end_date in sorted(set(gross_profit) & set(revenue)):
        rev = revenue[end_date]["val"]
        gp = gross_profit[end_date]["val"]
        if rev > 0:
            margin = round(gp / rev * 100, 1)
            margins.append(
                {
                    "date": end_date,
                    "filed": gross_profit[end_date]["filed"]
                    or revenue[end_date]["filed"],
                    "gross_profit": gp,
                    "revenue": rev,
                    "margin_pct": margin,
                }
            )

    margins = margins[-8:]
    result = {"updated": datetime.now().isoformat(), "entries": margins}
    MICRON_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if margins:
        latest = margins[-1]
        print(
            f"  Latest: {latest['date']} GM={latest['margin_pct']}%"
            f"（公告日 {latest['filed']}）"
        )
    print(f"Saved {len(margins)} quarters to {MICRON_FILE}")


if __name__ == "__main__":
    # 2026-10-22：SEC 暫時連不上不准擋掉整條儀表板更新。保留上一份 micron_gross.json，
    # 新鮮度守門以資料本身的 filed 日判斷，舊資料會自己變黃／紅，不會被當成新的。
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(
            f"WARN: Micron 毛利率抓取失敗，沿用上一份（{MICRON_FILE.name}）：{e}",
            file=sys.stderr,
        )
        sys.exit(0)
