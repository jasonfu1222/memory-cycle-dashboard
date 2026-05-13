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
        await page.goto(
            "https://www.trendforce.com/price/dram/dram_spot",
            wait_until="networkidle",
            timeout=30000,
        )
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
                m = re.search(r'\$?([\d]+\.[\d]+)', cell.get_text(strip=True))
                if m and any(kw in label for kw in ["DDR", "LPDDR", "GDDR"]):
                    results[label] = float(m.group(1))
                    break
    return results

def load_history():
    if SPOT_FILE.exists():
        return json.loads(SPOT_FILE.read_text(encoding="utf-8"))
    return {"updated": "", "series": {}}

def save_history(history):
    SPOT_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8"
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
        if key not in history["series"]:
            history["series"][key] = []
        entries = history["series"][key]
        if entries and entries[-1]["date"] == today:
            entries[-1]["price"] = all_prices[key]
        else:
            entries.append({"date": today, "price": all_prices[key]})
        # Keep last 365 days
        history["series"][key] = entries[-365:]
        print(f"  {key}: ${all_prices[key]}")

    save_history(history)
    print(f"Saved to {SPOT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
