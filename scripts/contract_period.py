"""合約價期別工具（fetch_contract / calc_score / calc_bit_proxy 共用，2026-10-22）。

背景（2026-10-22 實測，窮舉 TrendForce 英/繁/簡三站、page 參數、DRAMeXchange 首頁與其
JSON 端點 /Home/HomePrice?Source=NationalDramContract）：
  免費層的 DRAM 合約表一個月只換一次、而且晚一個月——每月月底才放出「上個月下半月」那期。
  實測軌跡：8/31 起顯示 2H Jul、9/30 起顯示 2H Aug（表頭 Last Update 2026-08-31 14:00）。
  1H 期別在免費層從未出現過。所以「期別停在 2H Aug」到 10 月底前都是正常狀態，不是停更。
  同一份數字在三站與 JSON 端點完全一致；更即時的期別與 DDR5 16Gb 顆粒合約價只給付費會員。

因此合約價在這裡一律當「期別價」處理：
  ① 期別 → 起訖日（2H Aug ＝ 8/16~8/31），年份用「第一次看到它的日期」反推，不猜。
  ② 資料年齡 ＝ 今天 − 期別結束日。免費層正常範圍約 30~61 天。
  ③ 比值有兩種：期別對齊（同一段時間的現貨均價 ÷ 合約價）與即時（今天現貨 ÷ 最近一期合約）。
     前者口徑正確但晚約 1.5~2 個月；後者是當下的，但分母是舊的，日變動 100% 來自現貨。
"""

import calendar
from datetime import date

MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}

# 期別「多久沒換」：免費層正常 ≈30 天換一次，45 天＝漏掉一次月底更新又過半個月。
VINTAGE_STALE_DAYS = 45
# 資料年齡（距期別結束日）：正常最舊 ≈61 天（例：2H Aug 8/31 結束，10/31 才被 2H Sep 取代）。
DATA_AGE_WARN_DAYS = 75  # 超過＝該換期的月底更新沒來，比值要標「過期」
DATA_AGE_DROP_DAYS = 105  # 超過＝連漏兩次，這份合約價不准再進任何計算

# 同口徑顆粒配對（現貨鍵, 合約鍵）。免費合約表沒有 DDR5 顆粒，只有 DDR5 8GB SO-DIMM 模組，
# 模組含 PCB/SPD/組裝，不可與顆粒現貨相除——所以比值只能用 DDR4 顆粒。
DIE_PAIRS = [
    ("DDR4 16Gb (2Gx8) 3200", "DDR4 16Gb 2Gx8"),
    ("DDR4 8Gb (1Gx8) 3200", "DDR4 8Gb 1Gx8"),
]
PRIMARY_PAIR = DIE_PAIRS[0]
MIN_ALIGNED_SPOT_DAYS = 5  # 對齊視窗內現貨天數不足就不算（半月約 11 個交易日）


def parse_period(label, seen_on):
    """'2H Aug' + 第一次看到的日期 → {key, label, year, month, half, start, end}。
    年份＝起始日不晚於 seen_on 的最近一年（期別不可能在開始前公布）。
    ★不能用「結束日 ≤ seen_on」：來源定價日常落在月底前一兩天（實測 2025-02-26 定 2H Feb、
      2025-08-29 定 2H Aug），用結束日判會把年份推回前一年，錯一整年。讀不懂回 None。"""
    if not label:
        return None
    parts = label.strip().split()
    if len(parts) != 2 or parts[0] not in ("1H", "2H") or parts[1][:3] not in MONTHS:
        return None
    half, month = parts[0], MONTHS[parts[1][:3]]
    seen = date.fromisoformat(str(seen_on)[:10])
    for year in (seen.year, seen.year - 1):
        last = calendar.monthrange(year, month)[1]
        start = date(year, month, 1 if half == "1H" else 16)
        end = date(year, month, 15 if half == "1H" else last)
        if start <= seen:
            return {
                "key": f"{year}-{month:02d}-{half}",
                "label": label,
                "year": year,
                "month": month,
                "half": half,
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
    return None


def data_age_days(period, today):
    return (date.fromisoformat(today) - date.fromisoformat(period["end"])).days


def freshness_status(age_days):
    """current＝免費層正常延遲內；stale＝該來的月底更新沒來；expired＝不准再用。"""
    if age_days is None:
        return "unavailable"
    if age_days > DATA_AGE_DROP_DAYS:
        return "expired"
    if age_days > DATA_AGE_WARN_DAYS:
        return "stale"
    return "current"


def latest_period(contract_real):
    periods = contract_real.get("periods") or {}
    if not periods:
        return None
    return periods[max(periods)]


def spot_mean(spot_series, start, end):
    """[start, end] 期間現貨均價（Session Average）；天數不足回 (None, n)。"""
    vals = [
        e["price"]
        for e in spot_series
        if e.get("price") and start <= e.get("date", "") <= end
    ]
    if len(vals) < MIN_ALIGNED_SPOT_DAYS:
        return None, len(vals)
    return sum(vals) / len(vals), len(vals)


def ratio_history(spot_history, contract_real, pair=PRIMARY_PAIR):
    """每一期的期別對齊比值：同期間現貨均價 ÷ 該期合約價。"""
    spot_key, c_key = pair
    sp = spot_history.get("series", {}).get(spot_key, [])
    out = []
    for key in sorted(contract_real.get("periods") or {}):
        p = contract_real["periods"][key]
        item = (p.get("items") or {}).get(c_key)
        if not item or not item.get("avg"):
            continue
        m, n = spot_mean(sp, p["start"], p["end"])
        out.append(
            {
                "period": p["label"],
                "period_full": f"{p['label']} {p['year']}",
                "period_key": key,
                "source": p.get("source")
                or ("backfilled" if p.get("backfilled") else "unknown"),
                "window": f"{p['start']}~{p['end']}",
                "spot_mean": round(m, 3) if m is not None else None,
                "spot_days": n,
                "contract": item["avg"],
                "ratio": round(m / item["avg"], 3) if m is not None else None,
            }
        )
    return out
