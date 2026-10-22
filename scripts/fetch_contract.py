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
    本檔抓到的其實是現貨表。不靜默接受：比對現貨檔，重疊鍵全同就記旗標。
    ★2026-10-22：只回傳旗標、不再自己印。要不要大聲取決於下游還有沒有人吃這份檔——
      s1b/s3/位元代理已改讀 contract_real_history，喊不喊由 main() 依真合約價狀態決定。"""
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
#
# ★2026-10-22 更新：s1b/s3/位元代理改讀本段產出的 periods（期別價），
#   contract_history.json 已無下游評分使用者，只為相容保留。理由與期別規則見 contract_period.py。
sys.path.insert(0, str(Path(__file__).parent))
from contract_period import (  # noqa: E402
    DATA_AGE_WARN_DAYS,
    VINTAGE_STALE_DAYS,
    data_age_days,
    freshness_status,
    parse_period,
)

CONTRACT_REAL_FILE = DATA_DIR / "contract_real_history.json"
PRICE_COL = "Session Average"  # 對齊 8/05 的均價口徑，不用 High
CHANGE_COL = "Average Change"  # 官方自報的「期別對期別」變動，不是我們自算
# 免費層實際是「每月月底換一次、放的是上個月 2H」，不是半月更新（2026-10-22 實測）。
# 期別 45 天沒換＝漏掉一次月底更新又過半個月。門檻統一放在 contract_period.py。


def _pct(text):
    """'▲2.68 %' → +2.68；'▼1.5 %' → -1.5；'—0.00 %' → 0.0；讀不出來回 None。
    ▲▼ 是唯一的正負來源（數字本身不帶符號），漏判方向會讓漲價被記成跌價。"""
    if not text:
        return None
    m = re.search(r"([\d,]+\.?\d*)\s*%", text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    if "▼" in text or "▽" in text:
        return -val
    if "▲" in text or "△" in text:
        return val
    return 0.0 if val == 0 else None  # 有數字卻沒方向符號→不猜，回 None


def parse_contract_table(html):
    """定位標題含 'Contract Price' 的表（排除 Mobile DRAM，產品線不同），
    回傳 (heading, {item: {price, high, low, change_pct}}, source_updated)。
    找不到回 (None, {}, None)——大聲失敗，不猜。
    source_updated＝表頭「Last Update」時間：它是 TrendForce 自己標的這期定價日，
    與「我們哪天第一次看到」是兩件事（實測差約 30 天），兩個都要留。"""
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
        idx_chg = hdr.index(CHANGE_COL) if CHANGE_COL in hdr else None
        idx_hi = hdr.index("Session High") if "Session High" in hdr else None
        idx_lo = hdr.index("Session Low") if "Session Low" in hdr else None

        def _num(cells, i):
            if i is None or len(cells) <= i:
                return None
            m = re.search(r"([\d,]+\.?\d*)", cells[i])
            return float(m.group(1).replace(",", "")) if m else None

        out = {}
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) <= idx:
                continue
            item = cells[0]
            price = _num(cells, idx)
            if item and price is not None:
                out[item] = {
                    "price": price,
                    "high": _num(cells, idx_hi),
                    "low": _num(cells, idx_lo),
                    "change_pct": (
                        _pct(cells[idx_chg])
                        if idx_chg is not None and len(cells) > idx_chg
                        else None
                    ),
                }
        if out:
            updated = None
            lu = table.find_previous(string=re.compile(r"Last Update"))
            if lu:
                m = re.search(
                    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
                    lu.parent.get_text(" ", strip=True),
                )
                updated = m.group(1) if m else None
            return heading, out, updated
    return None, {}, None


def parse_vintage(heading):
    """'DRAM Contract Price (2H Jun)' → '2H Jun'。括號抓不到就回 None，不編。"""
    if not heading:
        return None
    m = re.search(r"\(([^)]+)\)", heading)
    return m.group(1).strip() if m else None


def track_vintage(hist, vintage, today):
    """記錄期別何時第一次／最後一次出現，回傳（停滯天數, 是否停滯）。
    只有這份紀錄能回答「合約價到底多久沒動了」——價格本身是平的，看不出來。"""
    log = hist.setdefault("vintage_log", [])
    if not vintage:
        return None, False
    if log and log[-1]["period"] == vintage:
        log[-1]["last_seen"] = today
    else:
        log.append({"period": vintage, "first_seen": today, "last_seen": today})
    cur = log[-1]
    try:
        span = (
            date.fromisoformat(cur["last_seen"]) - date.fromisoformat(cur["first_seen"])
        ).days
    except ValueError:
        return None, False
    return span, span >= VINTAGE_STALE_DAYS


def _first_seen_of(hist, label):
    for rec in reversed(hist.get("vintage_log", [])):
        if rec["period"] == label:
            return rec["first_seen"]
    return None


def backfill_periods(hist):
    """一次性：把 2026-10-22 以前只存在 series 裡的期別價整理成 periods。
    只收帶 vintage 標籤的列；8/10~8/18 那段沒有標籤，價格與 2H Jun 相同，已由 2H Jun 涵蓋。"""
    periods = hist.setdefault("periods", {})
    for item, entries in hist.get("series", {}).items():
        for e in entries:
            label = e.get("vintage")
            seen = _first_seen_of(hist, label) if label else None
            p = parse_period(label, seen) if seen else None
            if not p:
                continue
            rec = periods.setdefault(
                p["key"],
                {
                    **p,
                    "first_seen": seen,
                    "last_seen": e["date"],
                    "source_updated": None,
                    "backfilled": True,
                    "items": {},
                },
            )
            rec["last_seen"] = max(rec["last_seen"], e["date"])
            rec["items"].setdefault(
                item,
                {
                    "avg": e["price"],
                    "high": None,
                    "low": None,
                    "change_pct": e.get("change_pct"),
                },
            )
    return periods


def update_period(hist, vintage, rows, source_updated, today):
    """把今天看到的這期寫進 periods。同一期別數字被改過就留修訂紀錄，不默默覆蓋。"""
    seen = _first_seen_of(hist, vintage) or today
    p = parse_period(vintage, seen)
    if not p:
        return None
    periods = hist.setdefault("periods", {})
    items = {
        k: {
            "avg": v["price"],
            "high": v.get("high"),
            "low": v.get("low"),
            "change_pct": v.get("change_pct"),
        }
        for k, v in rows.items()
    }
    rec = periods.get(p["key"])
    if rec is None:
        rec = periods[p["key"]] = {
            **p,
            "first_seen": seen,
            "last_seen": today,
            "source_updated": source_updated,
            "source": "live",
            "items": items,
        }
    else:
        changed = {
            k: {"old": rec["items"].get(k, {}).get("avg"), "new": v["avg"]}
            for k, v in items.items()
            if rec["items"].get(k, {}).get("avg") not in (None, v["avg"])
        }
        if changed:
            rec.setdefault("revisions", []).append({"date": today, "changed": changed})
        rec["items"] = items
        rec["last_seen"] = today
        rec["source"] = "live"
        if source_updated:
            rec["source_updated"] = source_updated
            rec.pop("backfilled", None)
    return rec


def save_contract_real(heading, rows, today, source_updated=None):
    """rows = {item: {price, high, low, change_pct}}。
    回傳 (vintage, 期別已持續天數, 是否停滯, 期別紀錄, 資料年齡天數, 新鮮度)。"""
    hist = (
        json.loads(CONTRACT_REAL_FILE.read_text(encoding="utf-8-sig"))
        if CONTRACT_REAL_FILE.exists()
        else {"series": {}}
    )
    vintage = parse_vintage(heading)
    span, stalled = track_vintage(hist, vintage, today)
    if "periods" not in hist:
        backfill_periods(hist)
    period = (
        update_period(hist, vintage, rows, source_updated, today) if vintage else None
    )
    age = data_age_days(period, today) if period else None
    status = freshness_status(age)

    hist["updated"] = datetime.now().isoformat()
    hist["source_heading"] = heading  # 存來源表名，日後可稽核抓對沒
    hist["source_updated"] = source_updated
    hist["price_column"] = PRICE_COL
    hist["vintage"] = vintage
    hist["vintage_span_days"] = span
    hist["latest_period"] = period["key"] if period else None
    hist["data_age_days"] = age
    hist["freshness"] = status
    hist["note"] = (
        "真・DRAM 合約價（TrendForce 頁內獨立表）。★免費層每月月底換一次期別、放的是上個月 2H，"
        "所以資料年齡（今天−期別結束日）正常就在 30~61 天；超過 "
        f"{DATA_AGE_WARN_DAYS} 天＝該來的月底更新沒來。"
        "★這是「期別價」不是日價：periods 一期一筆，series 是逐日快照（同期別內必然相同）。"
        "顆粒項（DDR4 16Gb 2Gx8 等）與現貨同口徑可比；"
        "模組項（DDR5 8GB SO-DIMM 等）含 PCB/SPD 非純顆粒，不可與顆粒現貨相除。"
        "s1b/s3 比值與位元代理自 2026-10-22 起讀 periods，規則見 scripts/contract_period.py。"
    )
    for key, row in rows.items():
        price = row["price"] if isinstance(row, dict) else row
        change = row.get("change_pct") if isinstance(row, dict) else None
        entries = hist["series"].setdefault(key, [])
        rec = {"date": today, "price": price, "change_pct": change, "vintage": vintage}
        if entries and entries[-1]["date"] == today:
            entries[-1] = rec
        else:
            entries.append(rec)
        hist["series"][key] = entries[-365:]
    CONTRACT_REAL_FILE.write_text(
        json.dumps(hist, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return vintage, span, stalled, period, age, status


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

    # 真・合約價（s1b/s3/位元代理的分母）。失敗不得影響上面既有流程 → 不改 exit code，
    # 但一定要讓下面的完整性告警知道「真合約價這條也斷了」。
    real_status = "unavailable"
    try:
        heading, c_prices, src_updated = parse_contract_table(html)
        if c_prices:
            vintage, span, stalled, period, age, real_status = save_contract_real(
                heading, c_prices, today, src_updated
            )
            print(
                f"\n  [真合約價] 來源表「{heading}」｜{PRICE_COL}｜{len(c_prices)} 項"
                f"｜期別 {vintage}"
                + (f"（{period['start']}~{period['end']}）" if period else "")
                + f"｜來源定價日 {src_updated or 'n/a'}"
                + f"｜本站已顯示 {span} 天｜距期末 {age} 天｜{real_status}"
            )
            for k, v in list(c_prices.items())[:7]:
                chg = v.get("change_pct")
                chg_s = f"  期變動 {chg:+.2f}%" if chg is not None else "  期變動 n/a"
                print(f"    {k}: ${v['price']}{chg_s}")
            print(f"  → {CONTRACT_REAL_FILE}（periods＝s1b/s3/位元代理的分母）")
            if stalled or real_status in ("stale", "expired"):
                print(
                    f"\n  [!! 合約價過期] 期別「{vintage}」本站已顯示 {span} 天、距期末 {age} 天"
                    f"（門檻：顯示 {VINTAGE_STALE_DAYS} 天／距期末 {DATA_AGE_WARN_DAYS} 天）。\n"
                    "      免費層正常是每月月底換期，這次沒換＝來源停更或頁面改版。\n"
                    "      影響：s1b/s3 比值改標過期（expired 時直接不算），位元代理缺當月分母。",
                    file=sys.stderr,
                )
        else:
            print(
                "\n  [!! 真合約價] 頁面上找不到 Contract Price 表——版面可能已改，"
                "請重跑診斷確認表格結構",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"\n  [!! 真合約價] 擷取失敗（不影響既有流程）: {e}", file=sys.stderr)

    # 完整性檢查保留：contract_history.json 仍是現貨表（parse_prices 掃全頁的老問題）。
    # 下游已改讀真合約價，所以真合約價健康時只記一行；真合約價也壞了才大聲喊，
    # 因為那代表這個儀表板此刻沒有任何一份可信的合約價。
    if integrity:
        if real_status == "current":
            print(
                "\n  [資料完整性·已隔離] contract_history.json 仍為現貨表"
                f"（{integrity['overlap_keys']} 個重疊項目同值），已無評分讀取它；"
                "s1b/s3/位元代理改用 contract_real_history.json 的期別價。"
            )
        else:
            print(
                "\n  [!! 資料完整性] contract_history.json 為現貨表（非合約價），"
                f"而真合約價狀態＝{real_status}。\n"
                "      此刻儀表板沒有任何可信的合約價：s1b/s3 比值與位元代理分母都不可用。\n",
                file=sys.stderr,
            )


if __name__ == "__main__":
    asyncio.run(main())
