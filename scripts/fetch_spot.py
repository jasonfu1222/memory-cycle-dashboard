import asyncio, json, re, sys
from datetime import date, datetime
from pathlib import Path
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data"
SPOT_FILE = DATA_DIR / "spot_history.json"

TARGET_KEYS = [
    "DDR5 16Gb (2Gx8) 4800/5600",
    "DDR4 16Gb (2Gx8) 3200",
    "DDR4 8Gb (1Gx8) 3200",
    "GDDR6  8Gb",
]


async def fetch_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # 表格為伺服器端渲染；networkidle 會被廣告/追蹤請求卡到逾時，等 table 即可
        await page.goto(
            "https://www.trendforce.com/price/dram/dram_spot",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_selector("table", state="attached", timeout=30000)
        content = await page.content()
        await browser.close()
    return content


def _num(text):
    # 千分位逗號必須納入，否則 "1,750.00" 會被讀成 750.00
    m = re.search(r"\$?(-?[\d,]+\.?[\d]*)", text)
    return float(m.group(1).replace(",", "")) if m else None


def _column_index(headers, *musts, exclude=()):
    for i, h in enumerate(headers):
        low = h.lower()
        if all(w in low for w in musts) and not any(x in low for x in exclude):
            return i
    return None


def parse_prices(html):
    """回傳 {品項: {"high":…, "avg":…, "change_pct":…}}。

    TrendForce 每列同時給 High / Low / Session Average / Change。舊版只取第一個
    數字＝High 欄，而 High 與 Average 差距極大（DDR4 16Gb 高 111 vs 均 85.95），
    故一併取均價與漲跌幅，讓下游能選用代表性數值。
    """
    soup = BeautifulSoup(html, "lxml")
    results = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
        i_high = _column_index(headers, "high", exclude=("change",))
        i_avg = _column_index(headers, "average", exclude=("change",))
        i_chg = _column_index(headers, "change")
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            if not any(kw in label for kw in ["DDR", "LPDDR", "GDDR"]):
                continue
            texts = [c.get_text(strip=True) for c in cells]

            def pick(idx):
                return (
                    _num(texts[idx]) if idx is not None and idx < len(texts) else None
                )

            high = pick(i_high)
            if high is None:  # 無表頭時退回舊行為：取第一個數字
                high = next(
                    (v for v in (_num(t) for t in texts[1:]) if v is not None), None
                )
            if high is None:
                continue
            results[label] = {
                "high": high,
                "avg": pick(i_avg),
                "change_pct": pick(i_chg),
            }
    return results


def load_history():
    if SPOT_FILE.exists():
        return json.loads(SPOT_FILE.read_text(encoding="utf-8-sig"))
    return {"updated": "", "series": {}}


def save_history(history):
    SPOT_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def main():
    today = date.today().isoformat()
    print(f"Fetching spot prices for {today}...")

    html = await fetch_page()
    all_prices = parse_prices(html)

    if not all_prices:
        print("ERROR: No prices found", file=sys.stderr)
        sys.exit(1)

    history = load_history()
    history["updated"] = datetime.now().isoformat()

    for key in TARGET_KEYS:
        if key not in all_prices:
            continue
        row = all_prices[key]
        # price 沿用 High 欄不改，避免既有 5MA/20MA 序列出現斷階；
        # avg/change_pct 為 2026-08-04 新增的平行欄位，供日後決定是否改用均價。
        point = {"date": today, "price": row["high"]}
        if row["avg"] is not None:
            point["price_avg"] = row["avg"]
        if row["change_pct"] is not None:
            point["change_pct"] = row["change_pct"]

        entries = history["series"].setdefault(key, [])
        if entries and entries[-1]["date"] == today:
            entries[-1].update(point)
        else:
            entries.append(point)
        # Keep last 365 days
        history["series"][key] = entries[-365:]
        avg_txt = f"｜均價 ${row['avg']}" if row["avg"] is not None else ""
        print(f"  {key}: ${row['high']}{avg_txt}")

    save_history(history)
    print(f"Saved to {SPOT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
