"""真合約價期別與 s1b/s3 閘門的故障注入測試（2026-10-22）。

存在理由：合約價從「同源假資料」換成「晚一個月的期別價」之後，最容易靜默壞掉的有四處：
  ① 期別年份推錯一年（定價日早於月底時，實測就踩過）
  ② 合約價過期了比值照樣進分數
  ③ 門檻沒校準就偷偷用舊表給綠燈
  ④ 同一期別被改數字卻默默覆蓋
跑法：venv\\Scripts\\python.exe scripts\\test_contract_gate.py　全綠才算守門還活著。
"""

import copy
import sys
from pathlib import Path

if __name__ != "__main__":
    raise ImportError("test_contract_gate.py 是測試入口腳本，不可 import。")

sys.path.insert(0, str(Path(__file__).parent))

import calc_score  # noqa: E402
from contract_period import (  # noqa: E402
    DATA_AGE_DROP_DAYS,
    DATA_AGE_WARN_DAYS,
    freshness_status,
    parse_period,
    ratio_history,
)
from fetch_contract import update_period  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(
        f"  [{'PASS' if cond else 'FAIL'}] {name}"
        + (f" — {detail}" if detail and not cond else "")
    )


print("── 1. 期別解析 ──")
p = parse_period("2H Aug", "2026-09-30")
check(
    "2H Aug → 2026-08-16~08-31",
    p and p["start"] == "2026-08-16" and p["end"] == "2026-08-31",
    p,
)
p = parse_period("2H Feb", "2025-02-26")
check("定價日早於月底不會推回前一年", p and p["year"] == 2025, p)
p = parse_period("2H Dec", "2027-01-31")
check("跨年：1 月看到 2H Dec＝前一年", p and p["year"] == 2026, p)
check(
    "1H 期別結束日＝15 日", parse_period("1H Sep", "2026-10-30")["end"] == "2026-09-15"
)
check("讀不懂的標籤回 None", parse_period("Q3", "2026-10-01") is None)

print("── 2. 新鮮度門檻 ──")
check("正常延遲＝current", freshness_status(52) == "current")
check(
    f">{DATA_AGE_WARN_DAYS} 天＝stale",
    freshness_status(DATA_AGE_WARN_DAYS + 1) == "stale",
)
check(
    f">{DATA_AGE_DROP_DAYS} 天＝expired",
    freshness_status(DATA_AGE_DROP_DAYS + 1) == "expired",
)
check("無資料＝unavailable", freshness_status(None) == "unavailable")


def spot_days(start_day, n, price):
    return [
        {"date": f"2026-08-{d:02d}", "price": price}
        for d in range(start_day, start_day + n)
    ]


SPOT = {
    "series": {
        "DDR4 16Gb (2Gx8) 3200": spot_days(16, 12, 90.0)
        + [{"date": "2026-10-21", "price": 80.0}],
        "DDR4 8Gb (1Gx8) 3200": spot_days(16, 12, 45.0)
        + [{"date": "2026-10-21", "price": 40.0}],
    }
}
REAL = {
    "series": {"x": [{"date": "2026-10-21", "price": 1}]},
    "periods": {
        "2026-08-2H": {
            **parse_period("2H Aug", "2026-09-30"),
            "first_seen": "2026-09-30",
            "items": {"DDR4 16Gb 2Gx8": {"avg": 50.0}, "DDR4 8Gb 1Gx8": {"avg": 25.0}},
        }
    },
}

print("── 3. 比值：期別對齊 vs 即時 ──")
cr = calc_score.build_contract_ratio(SPOT, REAL, "2026-10-22")
check(
    "期別對齊只取期間內現貨（90/50＝1.8）",
    cr["primary"]["aligned"]["ratio"] == 1.8,
    cr["primary"],
)
check("即時用最新現貨（80/50＝1.6）", cr["primary"]["live"]["ratio"] == 1.6)
check("比值不再恆為 1.00", cr["primary"]["aligned"]["ratio"] != 1.0)
check("資料年齡＝今天−期末（52 天）", cr["data_age_days"] == 52)
thin = copy.deepcopy(SPOT)
thin["series"]["DDR4 16Gb (2Gx8) 3200"] = spot_days(16, 3, 90.0)
check("對齊視窗現貨不足 5 天＝不算", ratio_history(thin, REAL)[0]["ratio"] is None)

print("── 4. 閘門（2026-10-22 起：s3＝水準、s1b＝方向，開關 RATIO_SCORING_ACTIVE）──")
ev = calc_score.evaluate_ratio_signals(None)
check(
    "無合約價＝兩者 None/unavailable",
    ev["gate"] == "unavailable"
    and ev["s3"]["score"] is None
    and ev["s1b"]["score"] is None,
)
ev = calc_score.evaluate_ratio_signals(cr)
check("1.80 水準 → s3 2.0（≥1.50）", ev["s3"]["score"] == 2.0, ev["s3"])
check(
    "只有 1 期比值 → s1b 方向不算（至少 3 期）", ev["s1b"]["score"] is None, ev["s1b"]
)
check(
    "明細帶比值與期別", "1.80" in ev["s3"]["detail"] and "52 天" in ev["s3"]["detail"]
)
check("開關預設關閉", calc_score.RATIO_SCORING_ACTIVE is False)
check("開關關著時 mode＝observe_only", calc_score.contract_mode(ev) == "observe_only")
s, d = calc_score.score_signal_1b(ev)
check("開關關著時 s1b 進總分的分數＝None", s is None and "若啟用" in d, d)
stale = dict(cr, freshness="stale", data_age_days=80)
ev = calc_score.evaluate_ratio_signals(stale)
check(
    "過期＝照算但標過期",
    ev["s3"]["score"] == 2.0
    and ev["gate"] == "scored_stale"
    and "過期" in ev["s3"]["detail"],
)
expired = dict(cr, freshness="expired", data_age_days=120)
ev = calc_score.evaluate_ratio_signals(expired)
check(
    "失效＝連若啟用分數都不算",
    ev["s3"]["score"] is None
    and ev["s1b"]["score"] is None
    and ev["gate"] == "dropped_expired",
)

print("── 4b. s3 水準門檻邊界 ──")
for r, want in [
    (1.50, 2.0),
    (1.4999, 3.0),
    (1.20, 3.0),
    (1.1999, 5.0),
    (1.05, 5.0),
    (1.0499, 6.5),
    (0.95, 6.5),
    (0.9499, 8.5),
    (0.0, 8.5),
]:
    check(
        f"水準 {r} → {want}",
        calc_score.score_ratio_level(r)[0] == want,
        calc_score.score_ratio_level(r),
    )

print("── 4c. s1b 方向門檻邊界 ──")
for delta, level, want in [
    (0.05, 1.8, 2.5),
    (0.0499, 1.8, 4.5),
    (-0.0499, 1.8, 4.5),
    (-0.05, 1.8, 6.0),
    (-0.1499, 1.8, 6.0),
    (-0.15, 1.8, 7.5),
    (-0.01, 1.04, 8.5),
    (0.01, 1.04, 4.5),
    (-0.30, 1.04, 8.5),
]:
    got = calc_score.score_ratio_direction(delta, level)
    check(f"Δ{delta:+.4f} 水準 {level} → {want}", got == want, got)


def hist_row(key, ratio):
    y, m = int(key[:4]), int(key[5:7])
    return {"period_key": key, "period_full": f"2H {m:02d} {y}", "ratio": ratio}


cr3 = dict(
    cr,
    period_key="2026-08-2H",
    history=[
        hist_row("2026-06-2H", 1.683),
        hist_row("2026-07-2H", 1.719),
        hist_row("2026-08-2H", 1.81),
    ],
)
d3, why = calc_score.ratio_direction(cr3)
check(
    "三期方向＝1.81 ÷ 平均(1.683,1.719) − 1 ≈ +6.4%",
    d3 and abs(d3["delta"] - 0.0641) < 0.001,
    (d3, why),
)
cr_gap = dict(
    cr3,
    history=[
        hist_row("2026-02-2H", 2.67),
        hist_row("2026-04-2H", 1.96),
        hist_row("2026-08-2H", 1.81),
    ],
)
d3, why = calc_score.ratio_direction(cr_gap)
check("三期跨 6 個月（缺期太多）→ 不算方向", d3 is None and "缺期" in why, why)
cr_okgap = dict(
    cr3,
    history=[
        hist_row("2026-03-2H", 2.58),
        hist_row("2026-04-2H", 1.96),
        hist_row("2026-06-2H", 1.68),
    ],
)
cr_okgap["period_key"] = "2026-06-2H"
d3, why = calc_score.ratio_direction(cr_okgap)
check("缺一期（2H May 2026）仍算方向", d3 is not None and d3["span_months"] == 3, why)
cr_latest_none = dict(
    cr3, history=cr3["history"][:2] + [dict(hist_row("2026-08-2H", None))]
)
d3, why = calc_score.ratio_direction(cr_latest_none)
check("最新一期沒有對齊比值 → 不拿舊期冒充", d3 is None, why)

print("── 5. 開關開／關與降級規則 ──")
subs = {"1a": {"score": 1.0}, "1b": {"score": None}}
scores = {k: 3.0 for k in calc_score.WEIGHTS}
scores["s3"] = None
ev = calc_score.evaluate_ratio_signals(cr3)
st = calc_score.build_contract_status(ev, scores, subs)
check(
    "關著：if_activated 有算、s3 仍 None", "if_activated" in st and scores["s3"] is None
)
check(
    "若啟用 s1b＝2.5、s3＝2.0",
    st["if_activated"]["s1b"] == 2.5 and st["if_activated"]["s3"] == 2.0,
    st["if_activated"],
)
check(
    "若啟用 S1＝1a×62.5%＋1b×37.5%＝1.6",
    st["if_activated"]["s1"] == 1.6,
    st["if_activated"],
)
check("降級規則寫明權重去向", "1a" in st["degrade_rule"] and "%" in st["degrade_rule"])
calc_score.RATIO_SCORING_ACTIVE = True
try:
    check("開著：mode＝scored", calc_score.contract_mode(ev) == "scored")
    s, d = calc_score.score_signal_1b(ev)
    check("開著：s1b 進總分＝2.5", s == 2.5, (s, d))
finally:
    calc_score.RATIO_SCORING_ACTIVE = False
check("測試後開關還原為關閉", calc_score.RATIO_SCORING_ACTIVE is False)

print("── 6. 同期別改數字要留紀錄 ──")
hist = {
    "vintage_log": [
        {"period": "2H Aug", "first_seen": "2026-09-30", "last_seen": "2026-10-21"}
    ],
    "periods": {},
}
rows = {
    "DDR4 16Gb 2Gx8": {"price": 50.0, "high": 59.0, "low": 47.0, "change_pct": 4.17}
}
update_period(hist, "2H Aug", rows, "2026-08-31 14:00", "2026-10-21")
rows2 = {
    "DDR4 16Gb 2Gx8": {"price": 51.0, "high": 59.0, "low": 47.0, "change_pct": 4.17}
}
rec = update_period(hist, "2H Aug", rows2, "2026-08-31 14:00", "2026-10-22")
check(
    "修訂被記下（50→51）",
    rec.get("revisions", [{}])[0].get("changed", {}).get("DDR4 16Gb 2Gx8")
    == {"old": 50.0, "new": 51.0},
)
check("期別鍵用第一次看到的日期推年份", "2026-08-2H" in hist["periods"])

print("\n" + "=" * 46)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
print("守門完整，全綠。" if not FAIL else "有紅燈：先修再跑每日更新。")
sys.exit(1 if FAIL else 0)
