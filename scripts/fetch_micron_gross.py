import json, sys
import requests
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
MICRON_FILE = DATA_DIR / "micron_gross.json"

EDGAR_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000723125.json"
HEADERS = {"User-Agent": "memory-cycle-dashboard bot@memory-cycle.netlify.app"}


def fetch_facts():
    r = requests.get(EDGAR_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def extract_quarterly(facts, concept):
    """Return {end_date: value} keeping only ~3-month periods (quarterly, not YTD)."""
    try:
        entries = facts[concept]["units"]["USD"]
    except KeyError:
        return {}

    by_date = {}
    for e in entries:
        if e.get("form") not in ("10-Q", "10-K"):
            continue
        start, end = e.get("start"), e.get("end")
        if not start or not end:
            continue
        try:
            days = (
                datetime.strptime(end, "%Y-%m-%d")
                - datetime.strptime(start, "%Y-%m-%d")
            ).days
        except ValueError:
            continue
        if not 65 <= days <= 100:
            continue
        if end not in by_date or e["filed"] > by_date[end]["filed"]:
            by_date[end] = e

    # 連 filed 一起回傳：季末日不等於資訊到手日（FY26Q3 季末 5/28、公告 6/24 差 27 天），
    # 新鮮度要用「什麼時候能知道」而不是「涵蓋到哪天」，否則剛開牌的財報也會被判過期。
    return {k: {"val": v["val"], "filed": v.get("filed")} for k, v in by_date.items()}


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
    main()
