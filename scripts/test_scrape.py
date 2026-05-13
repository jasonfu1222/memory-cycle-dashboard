import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json, re

async def fetch_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.trendforce.com/price/dram/dram_spot", wait_until="networkidle", timeout=30000)
        content = await page.content()
        await browser.close()
        return content

def parse_spot_prices(html):
    soup = BeautifulSoup(html, "lxml")
    results = {}

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True)
                # Look for price patterns like $1.23 or 1.23
                for cell in cells[1:]:
                    text = cell.get_text(strip=True)
                    price_match = re.search(r'\$?([\d]+\.[\d]+)', text)
                    if price_match and any(kw in label for kw in ["DDR", "LPDDR", "GDDR"]):
                        results[label] = float(price_match.group(1))
                        break

    return results

async def main():
    print("Fetching TrendForce DRAM Spot Price...")
    html = await fetch_page()
    prices = parse_spot_prices(html)

    if prices:
        print(f"\nFound {len(prices)} prices:")
        for k, v in prices.items():
            print(f"  {k}: ${v}")
    else:
        print("\nNo prices found in tables, dumping raw table content...")
        soup = BeautifulSoup(html, "lxml")
        for i, table in enumerate(soup.find_all("table")):
            print(f"\n--- Table {i+1} ---")
            print(table.get_text(separator=" | ", strip=True)[:500])

if __name__ == "__main__":
    asyncio.run(main())
