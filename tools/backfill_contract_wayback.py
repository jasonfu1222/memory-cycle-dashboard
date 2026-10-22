r"""從 Internet Archive（Wayback Machine）回補 DRAM 合約價期別（2026-10-22）。

為什麼要回補：s1b/s3 的門檻要用「期別對齊比值」校準，而樣本單位是「期別」不是「天」。
本機真合約價只從 2026-08-10 開始累積（3 期），不夠定門檻。Wayback 存有 TrendForce 合約頁
與 DRAMeXchange 首頁 JSON（/Home/HomePrice?Source=NationalDramContract）的公開快照，
內容就是當時免費公開的數字，不涉及登入或付費牆。

做什麼：
  ① 列出兩個來源的所有快照 → 逐一抓原始內容（id_ 模式，不含 Wayback 外框）
  ② 解析出期別與 7 個品項的 Session Average
  ③ 寫進 contract_real_history.json 的 periods，標 source=wayback；
     ★本機已親眼看到的期別一律不覆蓋，只在數字不同時記 wayback_mismatch 供稽核
  ④ 同時印出「快照日 − 期別結束日」，那就是免費層的公開延遲（實測證據）

跑法：venv\Scripts\python.exe tools\backfill_contract_wayback.py [--dry-run]
"""

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

if __name__ != "__main__":
    raise ImportError("backfill_contract_wayback.py 是工具入口腳本，不可 import。")

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from contract_period import parse_period  # noqa: E402

CONTRACT_REAL_FILE = ROOT / "data" / "contract_real_history.json"
UA = {"User-Agent": "Mozilla/5.0 (memory-cycle-dashboard research backfill)"}
CDX = "https://web.archive.org/cdx/search/cdx"
SOURCES = [
    ("www.trendforce.com/price/dram/dram_contract", "html"),
    ("www.dramexchange.com/Home/HomePrice*", "json"),
    ("dramexchange.com/Home/HomePrice*", "json"),
]
MON = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def cdx_list(url):
    r = requests.get(
        CDX,
        params={
            "url": url,
            "from": "2024",
            "output": "json",
            "filter": "statuscode:200",
            "fl": "timestamp,original,digest",
            "collapse": "digest",
        },
        headers=UA,
        timeout=90,
    )
    r.raise_for_status()
    rows = r.json()[1:]
    # HomePrice 端點的 Source 參數決定是哪張表；萬用字元查詢會帶回 eMMC/PCC/Flash，只留 DRAM 合約
    return [
        (t, o)
        for t, o, _ in rows
        if "HomePrice" not in o or "Source=NationalDramContract" in o
    ]


def fetch_snapshot(ts, original):
    for attempt in range(3):
        try:
            r = requests.get(
                f"https://web.archive.org/web/{ts}id_/{original}",
                headers=UA,
                timeout=60,
            )
            if r.ok:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(3 * (attempt + 1))
    return None


def parse_json(text):
    """HomePrice JSON → (期別標籤, 定價日, {item: {avg, high, low, change_pct}})。"""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, list) or not data:
        return None
    day = str(data[0].get("show_day", ""))[:10]
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    label = f"{'1H' if d.day <= 15 else '2H'} {MON[d.month - 1]}"
    items = {
        it["show_name"].strip(): {
            "avg": it.get("show_avg"),
            "high": it.get("show_hi"),
            "low": it.get("show_lo"),
            "change_pct": it.get("show_avg_change"),
        }
        for it in data
        if it.get("show_name") and it.get("show_avg")
    }
    return label, day, items


def parse_html(text):
    soup = BeautifulSoup(text, "lxml")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        hdr = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
        if "Session Average" not in hdr or "Low Change" not in hdr:
            continue
        heading = table.find_previous(string=re.compile(r"Contract Price \("))
        m = re.search(r"\(((?:1H|2H) \w{3})\)", heading or "")
        if not m:
            continue
        lu = table.find_previous(string=re.compile(r"Last Update"))
        mm = re.search(r"(\d{4}-\d{2}-\d{2})", lu.parent.get_text(" ") if lu else "")
        ia, ih, il = (
            hdr.index(c) for c in ("Session Average", "Session High", "Session Low")
        )
        items = {}
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) <= ia:
                continue

            def num(i):
                n = re.search(r"([\d,]+\.?\d*)", cells[i]) if len(cells) > i else None
                return float(n.group(1).replace(",", "")) if n else None

            if cells[0] and num(ia) is not None:
                items[cells[0]] = {
                    "avg": num(ia),
                    "high": num(ih),
                    "low": num(il),
                    "change_pct": None,
                }
        if items:
            return m.group(1), (mm.group(1) if mm else None), items
    return None


def main():
    dry = "--dry-run" in sys.argv
    # --only html｜json：JSON 端點快照數百個、archive.org 又限速，全跑要一小時以上
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    found = {}
    for url, kind in SOURCES:
        if only and kind != only:
            continue
        try:
            snaps = cdx_list(url)
        except Exception as e:
            print(f"[CDX 失敗] {url}: {e}")
            continue
        print(f"== {url}：{len(snaps)} 個不重複快照")
        for ts, original in snaps:
            text = fetch_snapshot(ts, original)
            if not text:
                print(f"   {ts} 抓不到")
                continue
            parsed = parse_json(text) if kind == "json" else parse_html(text)
            if not parsed:
                continue
            label, priced, items = parsed
            snap_day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
            p = parse_period(label, priced or snap_day)
            if not p:
                continue
            lag = (date.fromisoformat(snap_day) - date.fromisoformat(p["end"])).days
            print(
                f"   快照 {snap_day}｜{label}（{p['key']}）｜定價日 {priced}｜快照−期末 {lag} 天"
            )
            cur = found.get(p["key"])
            if cur is None or snap_day < cur["first_snapshot"]:
                found[p["key"]] = {
                    **p,
                    "first_snapshot": snap_day,
                    "source_updated": priced,
                    "items": items,
                    "snapshot_url": f"https://web.archive.org/web/{ts}/{original}",
                }
            time.sleep(
                4.0
            )  # archive.org 連續請求太密會直接拒絕連線（實測 1 秒間隔被封）

    hist = json.loads(CONTRACT_REAL_FILE.read_text(encoding="utf-8-sig"))
    periods = hist.setdefault("periods", {})
    added, mismatched = [], []
    for key, rec in sorted(found.items()):
        if key in periods and periods[key].get("source") != "wayback":
            own = periods[key]["items"]
            diff = {
                k: {"local": own[k]["avg"], "wayback": v["avg"]}
                for k, v in rec["items"].items()
                if k in own and own[k]["avg"] != v["avg"]
            }
            if diff:
                periods[key]["wayback_mismatch"] = diff
                mismatched.append(key)
            continue
        periods[key] = {
            "key": key,
            "label": rec["label"],
            "year": rec["year"],
            "month": rec["month"],
            "half": rec["half"],
            "start": rec["start"],
            "end": rec["end"],
            "first_seen": rec["first_snapshot"],
            "last_seen": rec["first_snapshot"],
            "source_updated": rec["source_updated"],
            "source": "wayback",
            "snapshot_url": rec["snapshot_url"],
            "items": rec["items"],
        }
        added.append(key)
    hist["periods"] = dict(sorted(periods.items()))
    print(f"\n新增 {len(added)} 期：{', '.join(added) or '—'}")
    print(f"與本機不一致：{', '.join(mismatched) or '無'}")
    if dry:
        print("（--dry-run：未寫檔）")
        return
    CONTRACT_REAL_FILE.write_text(
        json.dumps(hist, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"→ {CONTRACT_REAL_FILE}")


main()
