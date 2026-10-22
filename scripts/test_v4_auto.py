"""V4 自動訊號的故障注入測試（2026-10-22）。

存在理由：手填訊號改自動之後，最容易靜默壞掉的地方：
  ① 單季拆錯（現金流量表只給年初至今、10-K 只給全年，拆錯就是把累計當單季）
  ② 缺期時偷偷拿錯的基期（2H May 2026 沒存檔）
  ③ 某家公司沒抓到，總和少一家卻照樣算 YoY（看起來像 capex 暴跌）
  ④ 53 週年的第四季多一週，被當成營收加速
  ⑤ 缺資料時又填回 5.0 中性值
  ⑥ 已移除的手填欄位被填回去後默默進分數
跑法：venv\\Scripts\\python.exe scripts\\test_v4_auto.py　全綠才算守門還活著。
"""

import json
import sys
from pathlib import Path

if __name__ != "__main__":
    raise ImportError("test_v4_auto.py 是測試入口腳本，不可 import。")

sys.path.insert(0, str(Path(__file__).parent))

import calc_score as cs  # noqa: E402
from contract_period import parse_period  # noqa: E402
from sec_xbrl import instants, next_filing_due, quarterly  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(
        f"  [{'PASS' if cond else 'FAIL'}] {name}"
        + (f" — {detail}" if detail and not cond else "")
    )


def fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


print("── 1. 單季拆分（sec_xbrl.quarterly）──")
# 日曆年公司：Q1 直接值、6M／9M 累計、10-K 全年
ents = [
    fact("2026-01-01", "2026-03-31", 10, "2026-04-30"),
    fact("2026-01-01", "2026-06-30", 25, "2026-07-30"),
    fact("2026-01-01", "2026-09-30", 45, "2026-10-30"),
    fact("2026-01-01", "2026-12-31", 70, "2027-02-01", "10-K"),
]
q, mm = quarterly(ents)
check("Q2＝6M−Q1＝15", q["2026-06-30"]["val"] == 15, q.get("2026-06-30"))
check("Q3＝9M−6M＝20", q["2026-09-30"]["val"] == 20)
check("Q4＝全年−9M＝25（10-K 沒有單季數也拆得出來）", q["2026-12-31"]["val"] == 25)
check("Q4 起日＝9M 期末隔天", q["2026-12-31"]["start"] == "2026-10-01")
check("第幾季標記正確（Q4 fq=4）", q["2026-12-31"]["fq"] == 4)
check(
    "available＝第一次申報日（10-K 申報日）",
    q["2026-12-31"]["available"] == "2027-02-01",
)

# 重述：同一期間在下一年 10-Q 被重新揭露 → 值取最新、available 取第一次
ents2 = ents + [fact("2026-01-01", "2026-03-31", 11, "2027-04-30")]
q2, _ = quarterly(ents2)
check("重述後值取最新（11）", q2["2026-03-31"]["val"] == 11)
check(
    "重述後 available 仍是第一次申報（不讓舊季度變新資料）",
    q2["2026-03-31"]["available"] == "2026-04-30",
)

# 直接單季數與累計推算不一致 → 記下 mismatch，不默默挑一個
ents3 = ents + [fact("2026-04-01", "2026-06-30", 16, "2026-07-30")]
q3, mm3 = quarterly(ents3)
check("有直接單季數時優先用直接值（16）", q3["2026-06-30"]["val"] == 16)
check(
    "直接值與推算差 >1% 要記 mismatch", any(m["end"] == "2026-06-30" for m in mm3), mm3
)

# 累計鏈斷了（只有 12M 沒有 9M）→ Q4 不硬拆
ents4 = [ents[0], ents[1], ents[3]]
q4, _ = quarterly(ents4)
check("缺 9M 時不拿全年−6M 當 Q4", "2026-12-31" not in q4)

# TTM（同一起始日只有 3 個月與 12 個月）不能被當成累計鏈
ents5 = [
    fact("2025-07-01", "2025-09-30", 5, "2025-10-30"),
    fact("2025-07-01", "2026-06-30", 30, "2026-07-30"),
]
q5, _ = quarterly(ents5)
check("TTM 不被拆成假的單季", "2026-06-30" not in q5)
check("TTM 起始日的單季不被標成 fq=1", q5["2025-09-30"]["fq"] is None)

# Micron 53 週年：FY 371 天、9M 273 天 → Q4 98 天
mu = [
    fact("2025-08-29", "2025-11-27", 13.64, "2025-12-18"),
    fact("2025-08-29", "2026-02-26", 37.50, "2026-03-19"),
    fact("2025-08-29", "2026-05-28", 78.96, "2026-06-25"),
    fact("2025-08-29", "2026-09-03", 133.19, "2026-10-09", "10-K"),
]
qm, _ = quarterly(mu)
check("53 週年 Q4 天數＝98", qm["2026-09-03"]["days"] == 98, qm.get("2026-09-03"))
check("Q4＝133.19−78.96＝54.23", abs(qm["2026-09-03"]["val"] - 54.23) < 1e-6)

inst = instants(
    [
        {"end": "2026-05-28", "val": 8.57, "filed": "2026-06-25", "form": "10-Q"},
        {"end": "2026-05-28", "val": 8.57, "filed": "2027-06-25", "form": "10-Q"},
    ]
)
check(
    "存貨（instant）available 取第一次申報",
    inst["2026-05-28"]["available"] == "2026-06-25",
)

print("── 2. 法定申報期限（next_due 只能是外部事件日）──")
d = next_filing_due("2026-06-30", (12,), True, 2)
check(
    "日曆年 Q2 → Q3 10-Q 期限 11/09（9/30＋40）",
    d["due"] == "2026-11-09" and d["next_form"] == "10-Q",
    d,
)
d = next_filing_due("2026-09-30", (12,), True, 3)
check(
    "Q3 → Q4 是 10-K，期限 3/01（12/31＋60）",
    d["next_form"] == "10-K" and d["due"] == "2027-03-01",
    d,
)
d = next_filing_due("2026-06-30", (6,), True, 4)
check("MSFT 6 月年結 → 下一份是 10-Q", d["next_form"] == "10-Q", d)
d = next_filing_due("2026-09-03", (8, 9), False, 4)
check("Micron FQ4 → FQ1 10-Q，期末估 12/03、期限 1/12", d["due"] == "2027-01-12", d)

print("── 3. s2 真合約價動能（缺期基期）──")


def per(label, seen, items):
    p = parse_period(label, seen)
    return p["key"], {
        **p,
        "first_seen": seen,
        "items": {k: {"avg": v} for k, v in items.items()},
    }


periods = dict(
    [
        per(
            "2H Apr", "2026-06-07", {"DDR5 8GB SO-DIMM": 109.0, "DDR4 16Gb 2Gx8": 33.5}
        ),
        per(
            "2H Jun", "2026-08-10", {"DDR5 8GB SO-DIMM": 115.0, "DDR4 16Gb 2Gx8": 42.0}
        ),
        per(
            "2H Aug", "2026-09-30", {"DDR5 8GB SO-DIMM": 133.0, "DDR4 16Gb 2Gx8": 50.0}
        ),
    ]
)
s, det, info = cs.score_signal_2_contract({"periods": periods}, "2026-10-22")
check(
    "缺 2H May → 改用 4 個月前（2H Apr）",
    all(r["months"] == 4 for r in info["rows"]),
    info["rows"],
)
want = ((133 / 109) ** 0.75 - 1 + (50 / 33.5) ** 0.75 - 1) / 2 * 100
check(
    "幾何換算成 3 個月（兩品項平均 ≈ +25.6%）",
    abs(info["qoq_equiv_pct"] - want) < 0.01,
    info,
)
check("+25.6% → 2.5（>20 那格）", s == 2.5, (s, det))
check(
    "下一期期限＝期末＋75 天（11/14）",
    info["next_due"] == "2026-11-14",
    info["next_due"],
)
periods3 = dict(periods)
periods3.update(
    dict(
        [
            per(
                "2H May",
                "2026-07-10",
                {"DDR5 8GB SO-DIMM": 112.0, "DDR4 16Gb 2Gx8": 38.0},
            )
        ]
    )
)
s3_, _, info3 = cs.score_signal_2_contract({"periods": periods3}, "2026-10-22")
check(
    "有 3 個月前就用 3 個月前",
    all(r["months"] == 3 for r in info3["rows"]),
    info3["rows"],
)
s, det, info = cs.score_signal_2_contract({"periods": periods}, "2027-01-30")
check(
    "合約價失效（距期末 >105 天）→ None，不填中性值", s is None and "過期" in det, det
)
s, det, _ = cs.score_signal_2_contract({}, "2026-10-22")
check("無期別 → None", s is None)
for q, want in [
    (40.01, 2.0),
    (40, 2.5),
    (20, 3.5),
    (10, 4.5),
    (0, 5.5),
    (-5, 7.0),
    (-15, 8.5),
]:
    check(f"s2 階梯 {q}% → {want}", cs._s2_ladder(q) == want, cs._s2_ladder(q))

print("── 4. s4 capex／RPO ──")


def qrows(vals):
    """vals: {期末: 單季值} → quarterly rows（日曆季）"""
    out = []
    for e, v in sorted(vals.items()):
        out.append(
            {"end": e, "start": e[:8] + "01", "days": 91, "val": v, "available": e}
        )
    return out


ends = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]


def company(capex, rpo=None):
    c = {
        "quarterly": {"capex": qrows(dict(zip(ends, capex)))},
        "instant": {},
        "due": "2026-11-09",
    }
    if rpo:
        c["instant"]["rpo"] = [
            {"end": e, "val": v, "available": e} for e, v in zip(ends, rpo)
        ]
    return c


sec = {
    "companies": {
        "GOOGL": company([22, 24, 28, 36, 45], [108, 158, 243, 468, 520]),
        "MSFT": company([17, 19, 30, 31, 36], [375, 398, 631, 633, 684]),
        "AMZN": company([32, 35, 40, 44, 54]),
        "META": company([17, 19, 21, 19, 30]),
    }
}
s, det, info = cs.score_signal_4a(sec)
check(
    "4a YoY＝165/88−1≈+87.5% → 2.0",
    s == 2.0 and abs(info["yoy_pct"] - 87.5) < 0.1,
    (s, info),
)
sec_missing = json.loads(json.dumps(sec))
del sec_missing["companies"]["META"]
s, det, _ = cs.score_signal_4a(sec_missing)
check("少一家公司 → None（不拿三家總和算 YoY）", s is None and "META" in det, det)
sec_lag = json.loads(json.dumps(sec))
sec_lag["companies"]["GOOGL"]["quarterly"]["capex"].append(
    {
        "end": "2026-09-30",
        "start": "2026-07-01",
        "days": 92,
        "val": 50,
        "available": "2026-10-28",
    }
)
s, det, info = cs.score_signal_4a(sec_lag)
check(
    "一家先申報下一季 → 用四家共同的最新季，並註明",
    info["quarter_end"] == "2026-06-30" and "GOOGL" in det,
    det,
)
sec_cut = json.loads(json.dumps(sec))
for t, v in {"GOOGL": 20, "MSFT": 15, "AMZN": 30, "META": 15}.items():
    sec_cut["companies"][t]["quarterly"]["capex"][-1]["val"] = v
s, det, info = cs.score_signal_4a(sec_cut)
check("YoY −9%、QoQ −38% → 8.0＋1.0＝9.0", s == 9.0, (s, info))
s, det, info = cs.score_signal_4c(sec)
check(
    "4c RPO YoY +149% 跑贏 capex → 2.0",
    s == 2.0 and not info["backlog_lagging_capex"],
    (s, info),
)
sec_rpo = json.loads(json.dumps(sec))
for t in ("GOOGL", "MSFT"):
    sec_rpo["companies"][t]["instant"]["rpo"][-1]["val"] = (
        sec_rpo["companies"][t]["instant"]["rpo"][0]["val"] * 1.3
    )
s, det, info = cs.score_signal_4c(sec_rpo)
check(
    "RPO +30% 跑輸 capex +104% → 3.0＋1.0＝4.0",
    s == 4.0 and info["backlog_lagging_capex"],
    (s, info),
)
check("s4 子項全缺 → None（不再回 5.0）", cs.calc_signal_4_composite({}) is None)
check(
    "s4 只剩 4a → 等於 4a",
    cs.calc_signal_4_composite({"4a": {"score": 3.0}, "4c": {"score": None}}) == 3.0,
)

print("── 5. s6b 營收動能／s7 DIO（Micron）──")
mu_sec = {
    "companies": {
        "MU": {
            "quarterly": {
                "revenue": [
                    {
                        "start": "2026-02-27",
                        "end": "2026-05-28",
                        "days": 91,
                        "val": 41.46e9,
                        "available": "2026-06-25",
                    },
                    {
                        "start": "2026-05-29",
                        "end": "2026-09-03",
                        "days": 98,
                        "val": 54.23e9,
                        "available": "2026-10-09",
                    },
                ],
                "cogs": [
                    {
                        "start": "2025-11-28",
                        "end": "2026-02-26",
                        "days": 91,
                        "val": 6.11e9,
                        "available": "2026-03-19",
                    },
                    {
                        "start": "2026-02-27",
                        "end": "2026-05-28",
                        "days": 91,
                        "val": 6.40e9,
                        "available": "2026-06-25",
                    },
                    {
                        "start": "2026-05-29",
                        "end": "2026-09-03",
                        "days": 98,
                        "val": 7.18e9,
                        "available": "2026-10-09",
                    },
                ],
            },
            "instant": {
                "inventory": [
                    {"end": "2025-11-27", "val": 8.205e9, "available": "2025-12-18"},
                    {"end": "2026-02-26", "val": 8.267e9, "available": "2026-03-19"},
                    {"end": "2026-05-28", "val": 8.567e9, "available": "2026-06-25"},
                    {"end": "2026-09-03", "val": 10.372e9, "available": "2026-10-09"},
                ]
            },
        }
    }
}
s, det, info = cs.score_signal_6b(mu_sec)
check(
    "日均 QoQ（扣掉多一週）≈ +21.5%，不是 +30.8%",
    abs(info["qoq_per_day_pct"] - 21.5) < 0.1 and abs(info["qoq_raw_pct"] - 30.8) < 0.1,
    info,
)
check("+21.5% → 2.0", s == 2.0)
bad = json.loads(json.dumps(mu_sec))
bad["companies"]["MU"]["quarterly"]["revenue"][0]["end"] = "2026-05-20"
s, det, _ = cs.score_signal_6b(bad)
check("季度不連續 → None", s is None and "不連續" in det, det)
s, det, info = cs.score_signal_7(mu_sec)
check(
    "FQ4 DIO≈129.2 天（與 Micron 自報 129 天一致）",
    abs(info["dio_days"] - 129.2) < 0.2,
    info,
)
check("Δ≈+9.5 天 → 4.5", s == 4.5 and abs(info["delta_days"] - 9.5) < 0.2, (s, info))
glut = json.loads(json.dumps(mu_sec))
glut["companies"]["MU"]["instant"]["inventory"][-1]["val"] = 14.0e9
s, det, info = cs.score_signal_7(glut)
check(
    "DIO ≥150 且 Δ>+20 → 7.5＋1.0＝8.5", s == 8.5 and info["dio_days"] >= 150, (s, info)
)
for delta, want in [
    (-10, 2.0),
    (-9.9, 3.0),
    (0, 3.0),
    (0.1, 4.5),
    (10, 4.5),
    (20, 6.0),
    (20.1, 7.5),
]:
    got = next((sc for lim, sc in cs.S7_DELTA_BANDS if delta <= lim), 7.5)
    check(f"s7 Δ{delta:+} → {want}", got == want, got)
s, det, _ = cs.score_signal_7({})
check("無 SEC 資料 → s7 None", s is None)
score6, sub6, _ = cs.calc_signal_6_composite({"entries": []}, {})
check("s6 兩子項全缺 → None（不再填 5.0）", score6 is None, sub6)

print("── 6. 移除的訊號真的被移除 ──")
check("權重表不含 s5／s8／s9", not {"s5", "s8", "s9"} & set(cs.WEIGHTS))
check("權重合計＝1", abs(sum(cs.WEIGHTS.values()) - 1) < 1e-3, cs.WEIGHTS)
check("V4 權重＝V3 原比例放大（s4 25%）", abs(cs.WEIGHTS["s4"] - 0.25) < 1e-4)
check("S1 子項不含 1c", "1c" not in cs.S1_WEIGHTS)
check("S4 子項只剩 4a／4c", set(cs.S4_WEIGHTS) == {"4a", "4c"})
check("S6 子項只剩 6a／6b", set(cs.S6_WEIGHTS) == {"6a", "6b"})
manual = json.loads(
    (cs.DATA_DIR / "manual_inputs.json").read_text(encoding="utf-8-sig")
)
check(
    "manual_inputs.json 已沒有任何評分欄位",
    cs.iter_manual_leaves(manual) == [],
    cs.iter_manual_leaves(manual),
)
check(
    "手填欄位填回去會被偵測到",
    cs.iter_manual_leaves({"s8": {"8a": {"score": 7.5}}}) != [],
)

print("\n" + "=" * 46)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
print("守門完整，全綠。" if not FAIL else "有紅燈：先修再跑每日更新。")
sys.exit(1 if FAIL else 0)
