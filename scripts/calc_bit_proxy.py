r"""位元出貨量代理：台系記憶體廠月營收 ÷ 合約價 ÷ 匯率

恆等式（不是模型）：
    美元營收MoM = (1 + 台幣營收MoM) / (1 + USDTWD月均MoM) - 1
    量MoM      = (1 + 美元營收MoM) / (1 + 合約價MoM) - 1

為什麼要匯率那一步：月營收是新台幣、DRAM 報價是美元。2026 台幣走貶，
不修正會讓台幣營收虛高、推出來的量被高估（實際萎縮比看到的更嚴重）。

★這個代理算的是「利基／消費端」的量，不是 AI 端：
  南亞科、華邦電做的是利基型與 DDR4，韓系做的是伺服器與 HBM。
  台系量萎縮 × 韓系量加速 的分岔本身就是訊號（AI 獨撐、消費端未回溫）。

跨專案唯讀依賴（需 pandas/pyarrow，故用月營收追蹤器的 venv 執行）：
  月營收 parquet：Projects\台股策略\月營收追蹤_monthly-revenue-tracker\data\revenue.parquet
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import pandas as pd
import requests

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
FX_FILE = DATA / "fx_usdtwd.json"
OUT_FILE = DATA / "bit_proxy.json"
CONTRACT = DATA / "contract_history.json"
KOREA = DATA / "korea_exports.json"
GUIDANCE = DATA / "memory_guidance.json"
REVENUE = Path(
    r"C:\Users\USER\Claude\Projects\台股策略\月營收追蹤_monthly-revenue-tracker\data\revenue.parquet"
)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
FX_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/USDTWD=X?range=5y&interval=1d"
)

# 台系記憶體廠。註記各自的主力產品，決定該用哪個報價當分母。
FIRMS = {
    "2408": ("南亞科", "純 DRAM，利基型/DDR4 為主"),
    "2344": ("華邦電", "DRAM + NOR Flash"),
}
PRICE_KEYS = ["DDR4 16Gb (2Gx8) 3200", "DDR5 16Gb (2Gx8) 4800/5600"]


def fetch_fx_monthly():
    """Yahoo chart API 日線 → 月均。比月線收盤精確（月線還有重複時間戳的問題）。"""
    r = requests.get(FX_URL, headers=UA, timeout=40)
    r.raise_for_status()
    d = r.json()["chart"]["result"][0]
    ts = d["timestamp"]
    close = d["indicators"]["quote"][0]["close"]
    bym = {}
    for t, c in zip(ts, close):
        if c is None:
            continue
        ym = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m")
        bym.setdefault(ym, []).append(c)
    monthly = {ym: round(mean(v), 4) for ym, v in sorted(bym.items())}
    FX_FILE.write_text(
        json.dumps(
            {
                "updated": datetime.now().isoformat(),
                "source": "Yahoo chart API USDTWD=X 日線自算月均",
                "note": "數值＝1 美元兌新台幣。上升＝台幣貶值。",
                "monthly_avg": monthly,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return monthly


def contract_monthly():
    d = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    out = {}
    for key in PRICE_KEYS:
        bym = {}
        for row in d["series"].get(key, []):
            bym.setdefault(row["date"][:7], []).append(row["price"])
        out[key] = {ym: round(mean(v), 3) for ym, v in sorted(bym.items())}
    return out


def main():
    print("抓 USD/TWD 月均 ...")
    fx = fetch_fx_monthly()
    px = contract_monthly()

    rev = pd.read_parquet(REVENUE)
    rev["code"] = rev["code"].astype(str)

    results = []
    print(f"\n{'=' * 100}")
    print("位元出貨量代理（匯率已修正）")
    print(f"{'=' * 100}")
    print(
        f"{'公司':<12}{'期間':<18}{'台幣營收MoM':>12}{'匯率MoM':>10}{'美元營收MoM':>13}"
        f"{'合約價MoM':>11}{'→ 量MoM':>11}  口徑"
    )
    print("-" * 100)

    for code, (name, desc) in FIRMS.items():
        sub = rev[rev["code"] == code].sort_values("ym")
        for key in PRICE_KEYS:
            pm = px[key]
            months = sorted(set(pm) & set(sub["ym"]) & set(fx))
            for i in range(1, len(months)):
                cur, prv = months[i], months[i - 1]
                rc = sub.loc[sub["ym"] == cur, "revenue"]
                rp = sub.loc[sub["ym"] == prv, "revenue"]
                if rc.empty or rp.empty:
                    continue
                twd_mom = rc.iloc[0] / rp.iloc[0] - 1
                fx_mom = fx[cur] / fx[prv] - 1  # 上升＝台幣貶
                usd_mom = (1 + twd_mom) / (1 + fx_mom) - 1  # 貶值→美元營收成長被打折
                p_mom = pm[cur] / pm[prv] - 1
                q_mom = (1 + usd_mom) / (1 + p_mom) - 1
                lbl = "DDR4" if "DDR4" in key else "DDR5"
                print(
                    f"{code} {name:<8}{prv}→{cur:<8}{twd_mom * 100:>11.1f}%{fx_mom * 100:>9.2f}%"
                    f"{usd_mom * 100:>12.1f}%{p_mom * 100:>10.1f}%{q_mom * 100:>10.1f}%   {lbl}"
                )
                results.append(
                    {
                        "code": code,
                        "name": name,
                        "from": prv,
                        "to": cur,
                        "price_key": key,
                        "twd_rev_mom_pct": round(twd_mom * 100, 2),
                        "fx_mom_pct": round(fx_mom * 100, 2),
                        "usd_rev_mom_pct": round(usd_mom * 100, 2),
                        "price_mom_pct": round(p_mom * 100, 2),
                        "bit_proxy_mom_pct": round(q_mom * 100, 2),
                    }
                )

    if not results:
        print("  （可對齊月份不足：合約價序列起點晚於營收，或營收尚未公布）")

    OUT_FILE.write_text(
        json.dumps(
            {
                "updated": datetime.now().isoformat(),
                "method": "量MoM = (1+台幣營收MoM)/(1+USDTWD月均MoM)/(1+合約價MoM) - 1",
                "caveat": "代理的是利基/消費端的量，非 AI 端；南亞科非純 DDR4，單一報價當分母有誤差",
                "rows": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"\n→ {OUT_FILE}")
    print(
        f"  USD/TWD 月均近三月："
        + "  ".join(f"{m}:{fx[m]}" for m in sorted(fx)[-3:])
        + "（上升＝台幣貶）"
    )

    # ── 對照：韓系總量與三雄 bit 指引，讓三個訊號並排看 ──
    if KOREA.exists():
        k = json.loads(KOREA.read_text(encoding="utf-8"))
        rows = [r for r in k["rows"] if r.get("semiconductor_yoy") is not None][-4:]
        print(
            f"\n{'-' * 100}\n對照A｜韓國半導體出口（總量代理，含系統半導體非純記憶體）"
        )
        for r in rows:
            print(
                f"   {r['ym']} {r['seg']:4s} {r['semiconductor'] / 1000:>9,.0f} 百萬美元"
                f"   YoY {r['semiconductor_yoy']:+7.1f}%   佔總出口 {r.get('semi_share')}%"
            )

    if GUIDANCE.exists():
        g = json.loads(GUIDANCE.read_text(encoding="utf-8"))
        print(f"\n對照B｜三雄 bit 指引（原廠實績，最直接）")
        for e in g["entries"]:
            print(
                f"   {e['company']:<10}{e['quarter']:<9}(至 {e['period_end']})  "
                f"DRAM量 {e['dram_bit_qoq_actual']:<12} 下季 {e['dram_bit_qoq_guide_next']:<16}"
                f"NAND量 {e['nand_bit_qoq_actual']:<10} 下季 {e['nand_bit_qoq_guide_next']}"
            )
    print()


if __name__ == "__main__":
    main()
