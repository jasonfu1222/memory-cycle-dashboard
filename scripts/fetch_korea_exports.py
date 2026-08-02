"""韓國海關旬報：半導體出口金額（10日單位暫定值）

為什麼要這個：韓國佔全球 DRAM 約七成，這是頻率最高的記憶體需求總量代理。
公布節奏＝每月 11 日出 1~10 日、21 日出 1~20 日、次月 1 日出全月，
比 MU 財報（季度）早得多，比台系月營收（每月 10 日）也早。

資料源：관세청 수출입무역통계（tradedata.go.kr）內部 JSON 端點，免金鑰。
        端點與欄位對照由 /cts/js/ets/hmpg/trade/ETS0100173Q.js 逆向取得（2026-08-01）。
        單位＝千美元。itemUsdAmt01 在「出口×品項別」口徑下固定為半導體。

★限制：韓國半導體出口含記憶體＋系統半導體＋代工，非純記憶體。
        用途是看總量方向與 YoY 轉折，不能當 bit shipment 的精確替代。
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_FILE = DATA_DIR / "korea_exports.json"

HOME = "https://tradedata.go.kr/cts/index.do"
API = "https://tradedata.go.kr/cts/hmpg/retrieveTentativeValues.do"

START_YM = "202401"  # 抓兩年以上，YoY 才算得出來

# 出口×品項別 口徑的欄位對照（來源：ETS0100173Q.js f_tableDownData）
FIELDS = {
    "total": "itemUsdAmt00",
    "semiconductor": "itemUsdAmt01",
    "steel": "itemUsdAmt02",
    "auto": "itemUsdAmt03",
    "wireless": "itemUsdAmt05",
    "computer_peripheral": "itemUsdAmt08",
}


def to_num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace(" ", "").strip()
    if not s or s == "-":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def seg_of(priod_dt):
    """'01~10'→D10, '01~20'→D20, '01~31'/'01~28'…→FULL"""
    if not priod_dt:
        return None
    tail = priod_dt.split("~")[-1].strip()
    return {"10": "D10", "20": "D20"}.get(tail, "FULL")


def fetch(start_ym, end_ym):
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": HOME,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
    )
    s.get(HOME, timeout=30)  # 取 JSESSIONID
    payload = {
        "statsKind": "ETS_MNK_1050000A",  # 품목별
        "imexTpcd": "E",  # 수출
        "priodKind": "MON",
        "priodFr": start_ym,
        "priodTo": end_ym,
        "priodDate": "",  # 三段全取
        "selectPaging": "1",
        "showPagingLine": "500",
        "sortColumn": "",
        "sortOrder": "",
    }
    r = s.post(API, data=payload, timeout=60)
    r.raise_for_status()
    return r.json().get("items", [])


def main():
    today = date.today()
    end_ym = today.strftime("%Y%m")
    print(f"Fetching Korea customs exports {START_YM} ~ {end_ym} ...")

    items = fetch(START_YM, end_ym)
    if not items:
        print("ERROR: no items returned", file=sys.stderr)
        sys.exit(1)

    rows = []
    for it in items:
        ym = it.get("priodMon")
        seg = seg_of(it.get("priodDt"))
        if not ym or not seg:
            continue
        rec = {"ym": ym, "seg": seg, "range": it.get("priodDt", "").strip()}
        for name, tag in FIELDS.items():
            rec[name] = to_num(it.get(tag))
        rows.append(rec)

    rows.sort(key=lambda r: (r["ym"], {"D10": 0, "D20": 1, "FULL": 2}[r["seg"]]))

    # YoY：同月同段對比去年
    index = {(r["ym"], r["seg"]): r for r in rows}
    for r in rows:
        ly = f"{int(r['ym'][:4]) - 1}{r['ym'][4:]}"
        prev = index.get((ly, r["seg"]))
        for name in ("total", "semiconductor"):
            cur, old = r.get(name), (prev or {}).get(name)
            r[f"{name}_yoy"] = round((cur / old - 1) * 100, 1) if cur and old else None
        if r.get("total"):
            r["semi_share"] = (
                round(r["semiconductor"] / r["total"] * 100, 1)
                if r.get("semiconductor")
                else None
            )

    out = {
        "updated": datetime.now().isoformat(),
        "unit": "千美元 (thousand USD)",
        "source": "관세청 수출입무역통계 retrieveTentativeValues.do (品項別×出口)",
        "note": "半導體含記憶體＋系統半導體＋代工，非純記憶體；用於看總量方向與 YoY 轉折",
        "rows": rows,
    }
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    latest = [r for r in rows if r["semiconductor"]][-6:]
    print(f"  共 {len(rows)} 筆 → {OUT_FILE}")
    print("  最近六期（半導體出口，百萬美元）：")
    for r in latest:
        yoy = (
            f"{r['semiconductor_yoy']:+.1f}%"
            if r.get("semiconductor_yoy") is not None
            else "n/a"
        )
        share = f"{r['semi_share']:.1f}%" if r.get("semi_share") is not None else "n/a"
        print(
            f"    {r['ym']} {r['seg']:4s} ({r['range']:>6s})  "
            f"{r['semiconductor']/1000:>10,.0f}  YoY {yoy:>8s}  佔總出口 {share}"
        )


if __name__ == "__main__":
    main()
