# -*- coding: utf-8 -*-
"""只讀探針：分別抓 TrendForce spot / contract 兩頁，比對解析結果。不寫任何專案檔案。"""

import asyncio, re, sys
from playwright.async_api import async_playwright

URLS = {
    "spot": "https://www.trendforce.com/price/dram/dram_spot",
    "contract": "https://www.trendforce.com/price/dram/dram_contract",
}


async def grab(url):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        pg = await b.new_page()
        await pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_selector("table", state="attached", timeout=30000)
        html = await pg.content()
        title = await pg.title()
        final = pg.url
        await b.close()
    return title, final, html


def parse_rows(html):
    """粗解析：抓 <tr> 裡的文字，取 (品名, 第一個看起來像價格的數字)。"""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        ]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            name = cells[0]
            price = None
            for c in cells[1:]:
                m = re.search(r"\d+\.?\d*", c.replace(",", ""))
                if m:
                    price = m.group()
                    break
            if price and len(name) > 3:
                out.append((name[:46], price))
    return out


async def main():
    results = {}
    for tag, url in URLS.items():
        try:
            title, final, html = await grab(url)
            rows = parse_rows(html)
            results[tag] = rows
            print(f"\n===== {tag} =====")
            print(f"  requested : {url}")
            print(f"  final url : {final}")
            print(f"  title     : {title}")
            print(f"  rows      : {len(rows)}")
            for n, v in rows[:12]:
                print(f"     {n:<46} {v}")
        except Exception as e:
            print(f"[{tag}] FAILED: {e}")
            results[tag] = []

    a, b = results.get("spot", []), results.get("contract", [])
    if a and b:
        da, db = dict(a), dict(b)
        shared = set(da) & set(db)
        same = [k for k in shared if da[k] == db[k]]
        print(f"\n===== 比對 =====")
        print(
            f"  spot 品項 {len(da)} / contract 品項 {len(db)} / 共同品項 {len(shared)}"
        )
        print(f"  共同品項中價格相同: {len(same)} / {len(shared)}")
        print(f"  兩頁 rows 完全相同: {a == b}")


asyncio.run(main())
