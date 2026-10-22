"""SEC EDGAR XBRL 基本面抓取（2026-10-22 新增，取代 s4／s7 的手填值）。

抓什麼、餵給誰：
  GOOGL／MSFT／AMZN／META 的資本支出（現金流量表購置不動產廠房設備）→ s4a capex 方向
  MSFT／GOOGL 的剩餘履約義務（RPO，雲端合約積壓）              → s4c backlog vs capex
  Micron 的營收／銷貨成本／存貨                                    → s6b 營收動能、s7 存貨天數
  AMZN 的 RPO 自 2020 年起不再用標準標籤揭露、META 沒有 RPO，所以 4c 只有兩家，這是資料的邊界不是漏抓。
  NVDA 的「供應與產能承諾」（$279B 那個數字）沒有對應的標準 XBRL 標籤（PurchaseObligation 停在
  2025-07），程式抓不到 → 4f 移除，不做假自動化。

失敗處理（★這支掛在 calc_score 前面，Run-Step 任一指令 exit≠0 會擋掉後面的 calc_score 與 git push）：
  一律 exit 0。單一公司抓失敗 → 保留上一份該公司的結果、標 stale_cache 與上次成功日，不填中性值。
  calc_score 讀 fetch.failed 出告警，並在明細寫出「資料日期／沿用哪天的結果」。

跑法：venv\\Scripts\\python.exe scripts\\fetch_sec_fundamentals.py
"""

import json
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

if __name__ != "__main__":
    raise ImportError(
        "fetch_sec_fundamentals.py 是排程入口腳本，不可 import；共用函式在 sec_xbrl.py。"
    )

sys.path.insert(0, str(Path(__file__).parent))
from sec_xbrl import instants, next_filing_due, pick_concept, quarterly  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_FILE = DATA_DIR / "sec_fundamentals.json"
URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
# SEC 要求 User-Agent 帶聯絡方式；用通用字串，不外送使用者信箱
HEADERS = {"User-Agent": "memory-dashboard research contact@example.com"}
KEEP_QUARTERS = 12

COMPANIES = {
    "GOOGL": {
        "cik": 1652044,
        "calendar_quarters": True,
        "fy_end_months": (12,),
        "duration": {"capex": ["PaymentsToAcquirePropertyPlantAndEquipment"]},
        "instant": {"rpo": ["RevenueRemainingPerformanceObligation"]},
    },
    "MSFT": {
        "cik": 789019,
        "calendar_quarters": True,
        "fy_end_months": (6,),
        "duration": {"capex": ["PaymentsToAcquirePropertyPlantAndEquipment"]},
        "instant": {"rpo": ["RevenueRemainingPerformanceObligation"]},
    },
    "AMZN": {
        "cik": 1018724,
        "calendar_quarters": True,
        "fy_end_months": (12,),
        # AMZN 2017 起把「Purchases of property and equipment」標成 ProductiveAssets
        "duration": {
            "capex": [
                "PaymentsToAcquireProductiveAssets",
                "PaymentsToAcquirePropertyPlantAndEquipment",
            ]
        },
        "instant": {},
    },
    "META": {
        "cik": 1326801,
        "calendar_quarters": True,
        "fy_end_months": (12,),
        "duration": {"capex": ["PaymentsToAcquirePropertyPlantAndEquipment"]},
        "instant": {},
    },
    "MU": {
        "cik": 723125,
        "calendar_quarters": False,  # 52/53 週年，期末日不在月底
        "fy_end_months": (8, 9),
        "duration": {
            "revenue": [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
            ],
            "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue"],
        },
        "instant": {"inventory": ["InventoryNet"]},
    },
}


def fetch_company(ticker, cfg, requests):
    r = requests.get(URL.format(cik=cfg["cik"]), headers=HEADERS, timeout=60)
    r.raise_for_status()
    gaap = r.json().get("facts", {}).get("us-gaap", {})
    out = {"cik": cfg["cik"], "concepts": {}, "quarterly": {}, "instant": {}}
    latest = None
    for name, cands in cfg["duration"].items():
        c = pick_concept(gaap, cands, "duration")
        if not c:
            raise ValueError(f"{name}: 找不到標籤 {cands}")
        q, mismatch = quarterly(gaap[c]["units"]["USD"])
        rows = [q[k] for k in sorted(q)][-KEEP_QUARTERS:]
        if not rows:
            raise ValueError(f"{name}: {c} 拆不出任何單季")
        out["concepts"][name] = c
        out["quarterly"][name] = rows
        if mismatch:
            out.setdefault("mismatch", {})[name] = mismatch[-4:]
        if latest is None or rows[-1]["end"] > latest["end"]:
            latest = rows[-1]
    for name, cands in cfg["instant"].items():
        c = pick_concept(gaap, cands, "instant")
        if not c:
            raise ValueError(f"{name}: 找不到標籤 {cands}")
        inst = instants(gaap[c]["units"]["USD"])
        out["concepts"][name] = c
        out["instant"][name] = [inst[k] for k in sorted(inst)][-KEEP_QUARTERS - 1 :]
    out["latest_period_end"] = latest["end"]
    out["latest_available"] = max(
        r["available"] for rows in out["quarterly"].values() for r in rows[-1:]
    )
    out.update(
        next_filing_due(
            latest["end"],
            cfg["fy_end_months"],
            cfg["calendar_quarters"],
            latest.get("fq"),
        )
    )
    return out


def main():
    import requests

    today = date.today().isoformat()
    prev = (
        json.loads(OUT_FILE.read_text(encoding="utf-8-sig"))
        if OUT_FILE.exists()
        else {}
    )
    companies = dict(prev.get("companies") or {})
    ok, failed = [], {}
    for ticker, cfg in COMPANIES.items():
        try:
            rec = fetch_company(ticker, cfg, requests)
            rec.update(fetched_at=today, stale_cache=False)
            companies[ticker] = rec
            ok.append(ticker)
            print(
                f"  {ticker}: 最新期末 {rec['latest_period_end']}（{rec['latest_available']} 申報）"
                f"｜下一份 {rec['next_form']} 法定期限 {rec['due']}"
            )
        except Exception as e:  # noqa: BLE001 — 單一公司失敗不得拖垮其他公司與後續評分
            failed[ticker] = f"{type(e).__name__}: {e}"[:300]
            old = companies.get(ticker)
            if old:
                old["stale_cache"] = True
                old["last_error"] = failed[ticker]
                print(
                    f"  [!! {ticker}] 抓取失敗，沿用 {old.get('fetched_at')} 的結果"
                    f"（資料期末 {old.get('latest_period_end')}）：{failed[ticker]}",
                    file=sys.stderr,
                )
            else:
                companies[ticker] = {"stale_cache": True, "last_error": failed[ticker]}
                print(
                    f"  [!! {ticker}] 抓取失敗且無上一份：{failed[ticker]}",
                    file=sys.stderr,
                )
        time.sleep(0.25)  # SEC 限 10 次/秒

    payload = {
        "updated": datetime.now().isoformat(),
        "source": "SEC EDGAR XBRL companyfacts（https://data.sec.gov/api/xbrl/companyfacts/）",
        "fetch": {"date": today, "ok": ok, "failed": failed},
        "note": (
            "單季值由同一起始日的累計值相減而來（10-Q 現金流量表只給年初至今、10-K 只給全年）；"
            "available＝該數字第一次出現的申報日。due＝下一份申報的法定期限（10-Q 40 天／10-K 60 天）。"
        ),
        "companies": companies,
    }
    OUT_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"→ {OUT_FILE}（成功 {len(ok)}／失敗 {len(failed)}）")


try:
    main()
except Exception:  # noqa: BLE001
    # 程式本身壞掉也不擋後面的 calc_score：上一份檔案原封不動，calc_score 會因 fetch.date 不是今天而告警
    print(
        "[!! fetch_sec_fundamentals] 未預期錯誤，保留上一份 sec_fundamentals.json：",
        file=sys.stderr,
    )
    traceback.print_exc()
sys.exit(0)
