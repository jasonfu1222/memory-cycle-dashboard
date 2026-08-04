import asyncio, json, re, sys
from datetime import date, datetime
from pathlib import Path
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data"
CONTRACT_FILE = DATA_DIR / "contract_history.json"
URL = "https://www.trendforce.com/price/dram/dram_contract"


async def fetch_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # 表格為伺服器端渲染；networkidle 會被廣告/追蹤請求卡到逾時，等 table 即可
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_selector("table", state="attached", timeout=30000)
        content = await page.content()
        await browser.close()
    return content


def parse_prices(html):
    soup = BeautifulSoup(html, "lxml")
    results = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            for cell in cells[1:]:
                # 千分位逗號必須納入，否則 "1,750.00" 會被讀成 750.00
                m = re.search(r"\$?([\d,]+\.[\d]+)", cell.get_text(strip=True))
                if m and any(kw in label for kw in ["DDR5", "DDR4", "LPDDR", "GDDR"]):
                    results[label] = float(m.group(1).replace(",", ""))
                    break
    return results


def check_source_integrity(prices):
    """TrendForce 的 dram_spot 與 dram_contract 兩個 URL 目前回傳同一份頁面，
    本檔抓到的其實是現貨表。不靜默接受：比對現貨檔，重疊鍵全同就大聲示警。"""
    spot_file = DATA_DIR / "spot_history.json"
    if not spot_file.exists():
        return None
    spot = json.loads(spot_file.read_text(encoding="utf-8-sig")).get("series", {})
    overlap = [k for k in prices if k in spot and spot[k]]
    if not overlap:
        return None

    # 必須比同一個口徑：現貨檔自 2026-08-05 起 price＝Session Average，
    # 而本檔解析出來的是 High 欄，要拿 price_high 對照才有意義。
    # 拿均價對 High 會永遠不相等，同源偵測就會靜默失效。
    def spot_high(key):
        last = spot[key][-1]
        return last.get("price_high", last.get("price"))

    same = [k for k in overlap if spot_high(k) == prices[k]]
    if len(same) < len(overlap):
        return None
    print(
        "\n  [!! 資料完整性] 合約頁抓到的數值與現貨頁完全相同"
        f"（{len(same)}/{len(overlap)} 個重疊項目）。\n"
        "      dram_contract 與 dram_spot 現為同一份 DRAM Price Trends 頁面，\n"
        "      本檔記錄的並非合約價。受影響：s1b 與 s3 的 spot/contract 比值恆為 1.00、\n"
        "      calc_bit_proxy 的價格分母。待決定替代來源前不要據此解讀比值。\n",
        file=sys.stderr,
    )
    return {
        "duplicate_of_spot": True,
        "overlap_keys": len(overlap),
        "checked_at": datetime.now().isoformat(),
        "note": "dram_contract URL 與 dram_spot 回傳同一頁；本檔實為現貨表，非合約價",
    }


def load_history():
    if CONTRACT_FILE.exists():
        return json.loads(CONTRACT_FILE.read_text(encoding="utf-8-sig"))
    return {"updated": "", "series": {}}


def save_history(history):
    CONTRACT_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def main():
    today = date.today().isoformat()
    print(f"Fetching contract prices for {today}...")

    html = await fetch_page()
    prices = parse_prices(html)

    if not prices:
        print("ERROR: No contract prices found", file=sys.stderr)
        sys.exit(1)

    history = load_history()
    history["updated"] = datetime.now().isoformat()

    integrity = check_source_integrity(prices)
    if integrity:
        history["data_integrity"] = integrity
    else:
        history.pop("data_integrity", None)

    for key, price in prices.items():
        if key not in history["series"]:
            history["series"][key] = []
        entries = history["series"][key]
        if entries and entries[-1]["date"] == today:
            entries[-1]["price"] = price
        else:
            entries.append({"date": today, "price": price})
        history["series"][key] = entries[-365:]
        print(f"  {key}: ${price}")

    save_history(history)
    print(f"Saved to {CONTRACT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
