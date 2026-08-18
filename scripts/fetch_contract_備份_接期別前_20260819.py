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


# ── 2026-08-10 新增：真・合約價擷取 ───────────────────────────────
# 背景訂正：8/05 記錄的結論是「dram_contract 與 dram_spot 回傳同一頁面 →
# 合約價來源失效」。實測推翻：同一頁面上其實有 6 張表，其中 table[1] 標題為
# "DRAM Contract Price (2H Jun)"，欄位 Session High/Low/Average + Average Change/Low Change，
# 是貨真價實的合約價。上面 parse_prices() 不分表地掃全頁，抓到的是
# "Module Spot Price" 與 "GDDR Spot Price" 兩張現貨表（DDR5 UDIMM 16GB / RDIMM 32GB /
# GDDR5 8Gb 等 label 全來自那裡）——所以它跟現貨檔一模一樣是必然的，不是來源合併。
#
# 本段只做一件事：把真合約表存進「獨立檔」開始累積歷史。
# 刻意不接回 contract_history.json，也不動 s1b/s3/位元代理的停用狀態，理由：
#   ① 舊檔 56 天的「合約價」其實是現貨模組價，混進去會製造假歷史
#   ② 現貨表是顆粒（DDR5 16Gb，單位 Gb），合約表是模組（DDR5 8GB SO-DIMM，單位 GB），
#      spot÷contract 直接相除沒有意義——配對關係要重新定義，那是設計裁決不是抓取問題
#   ③ 解除 data_integrity 旗標會讓 s3 悄悄退回「手填 5.0」，正是 8/05 修掉的那個病
CONTRACT_REAL_FILE = DATA_DIR / "contract_real_history.json"
PRICE_COL = "Session Average"  # 對齊 8/05 的均價口徑，不用 High


def parse_contract_table(html):
    """定位標題含 'Contract Price' 的表（排除 Mobile DRAM，產品線不同），
    回傳 (heading, {item: price})。找不到回 (None, {})——大聲失敗，不猜。"""
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        heading = None
        for prev in table.find_all_previous(
            ["h1", "h2", "h3", "h4", "h5", "div", "span"], limit=40
        ):
            txt = prev.get_text(" ", strip=True)
            if txt and len(txt) < 80 and "Price" in txt:
                heading = txt
                break
        if not heading or "Contract Price" not in heading or "Mobile" in heading:
            continue

        rows = table.find_all("tr")
        if not rows:
            continue
        hdr = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
        if PRICE_COL not in hdr:
            continue
        # 結構護欄：現貨表才有 Daily/Weekly High，合約表沒有。誤抓到現貨表就放棄。
        if any(h.startswith(("Daily", "Weekly")) for h in hdr):
            continue
        idx = hdr.index(PRICE_COL)

        out = {}
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) <= idx:
                continue
            item = cells[0]
            m = re.search(r"([\d,]+\.?\d*)", cells[idx])
            if item and m:
                out[item] = float(m.group(1).replace(",", ""))
        if out:
            return heading, out
    return None, {}


def save_contract_real(heading, prices, today):
    hist = (
        json.loads(CONTRACT_REAL_FILE.read_text(encoding="utf-8-sig"))
        if CONTRACT_REAL_FILE.exists()
        else {"series": {}}
    )
    hist["updated"] = datetime.now().isoformat()
    hist["source_heading"] = heading  # 存來源表名，日後可稽核抓對沒
    hist["price_column"] = PRICE_COL
    hist["note"] = (
        "真・DRAM 合約價（TrendForce 頁內獨立表）。單位為模組 GB，"
        "與現貨顆粒 Gb 不同口徑，未接入 s1b/s3/位元代理，待配對關係裁決。"
    )
    for key, price in prices.items():
        entries = hist["series"].setdefault(key, [])
        if entries and entries[-1]["date"] == today:
            entries[-1]["price"] = price
        else:
            entries.append({"date": today, "price": price})
        hist["series"][key] = entries[-365:]
    CONTRACT_REAL_FILE.write_text(
        json.dumps(hist, indent=2, ensure_ascii=False), encoding="utf-8"
    )


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

    # 真・合約價（獨立檔累積，不接評分）。失敗不得影響上面既有流程 → 不改 exit code。
    try:
        heading, c_prices = parse_contract_table(html)
        if c_prices:
            save_contract_real(heading, c_prices, today)
            print(
                f"\n  [真合約價] 來源表「{heading}」｜{PRICE_COL}｜{len(c_prices)} 項"
            )
            for k, v in list(c_prices.items())[:6]:
                print(f"    {k}: ${v}")
            print(f"  → {CONTRACT_REAL_FILE}（尚未接入 s1b/s3/位元代理，待配對裁決）")
        else:
            print(
                "\n  [真合約價][警告] 頁面上找不到 Contract Price 表——版面可能已改，"
                "請重跑診斷確認表格結構",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"\n  [真合約價][警告] 擷取失敗（不影響既有流程）: {e}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
