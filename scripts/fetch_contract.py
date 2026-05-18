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
        await page.goto(URL, wait_until="networkidle", timeout=30000)
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
                m = re.search(r"\$?([\d]+\.[\d]+)", cell.get_text(strip=True))
                if m and any(kw in label for kw in ["DDR5", "DDR4", "LPDDR", "GDDR"]):
                    results[label] = float(m.group(1))
                    break
    return results


def load_history():
    if CONTRACT_FILE.exists():
        return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
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
