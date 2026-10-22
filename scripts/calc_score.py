"""
Memory Cycle Dashboard — Score Calculator V3 (2026-05-27)

Scoring philosophy (INVERTED from V2):
  LOW score (1-3) = signal is bullish / early cycle = safe zone
  MID score (4-6) = signal mixed or neutral = monitor zone
  HIGH score (7-9) = signal deteriorating = late cycle / peak warning

V3 changes from V2:
  - 9 signals (was 7): added S8 China expansion, S9 Cycle ending calibration
  - S1 composite: 1a (spot MA) ×50% + 1b (spot/contract) ×30% + 1c (DDR5/DDR4 ratio) ×20%
  - S4 adds 4f (NVDA supply commitments) at 15%, other sub-weights redistributed
  - S6 composite: 6a (GM trajectory) ×50% + 6b (event outcome) ×30% + 6c (HBM revenue) ×20%
  - S3 weight: 15% → 12%
  - S4 weight: 25% → 20%
  - S7 weight: 10% → 8%
  - New S8: 7%, S9: 3%
  - S2 prefers manual over auto (auto data captures daily snapshots, not monthly QoQ averages)

V4 (2026-10-22，Jason 裁決「手填訊號改成自動化或直接移除」)：
  - 移除（只能靠人讀新聞做質化判斷、沒有可重現的一手數字）：
      s1c DDR5÷DDR4（前提已被推翻）、s4b/4d/4e、s4f（NVDA 供應承諾無標準 XBRL 標籤）、
      s5 HBM 良率、s6c HBM 營收（Micron 未揭露金額）、s8 中國擴產、s9 週期終點校準
  - 改自動：s2＝真合約價期別變動（contract_real_history）；s4a＝四大雲端 capex（SEC XBRL）；
      s4c＝MSFT＋GOOGL RPO vs capex；s6b＝Micron 營收（日均）QoQ；s7＝Micron 存貨天數 DIO
  - s1b／s3 拆用途：s3＝比值水準、s1b＝比值方向；RATIO_SCORING_ACTIVE 開關，關著時只列「若啟用」對照
  - 權重：剩餘訊號按 V3 原比例重新正規化（WEIGHTS_V4 由 _renorm 算出，不手打數字）
  ★移除的多半是「高分＝警訊」的項目（s8 6.4、s5 5.5、s9 5.0），總分會因此變低——
    那是少了資訊，不是週期變好。
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

DATA_DIR = Path(__file__).parent.parent / "data"

WEIGHTS_V3 = {
    "s1": 0.15,
    "s2": 0.15,
    "s3": 0.12,
    "s4": 0.20,
    "s5": 0.10,
    "s6": 0.10,
    "s7": 0.08,
    "s8": 0.07,
    "s9": 0.03,
}


def _renorm(table, keep):
    w = sum(table[k] for k in keep)
    return {k: round(table[k] / w, 4) for k in keep}


# V4：s5／s8／s9 移除，其餘按 V3 原比例放大（÷0.80）。
#   s1 18.75%／s2 18.75%／s3 15%／s4 25%／s6 12.5%／s7 10%
WEIGHTS_V4 = _renorm(WEIGHTS_V3, ["s1", "s2", "s3", "s4", "s6", "s7"])
WEIGHTS = WEIGHTS_V4
METHODOLOGY = "V4"

# 已移除的訊號（看板與 signals.json 列出，不計分、不讀 manual_inputs）
RETIRED = {
    "s1c": "DDR5÷DDR4 現貨比：前提已被推翻（DDR4 因停產長期貴於 DDR5，量到的是 DDR4 退場速度），無資訊量。觀測層 ratio_watch 保留",
    "s4b": "雲端營收成長：四家分部口徑不一（Google Cloud／AWS／Azure 只給成長率），XBRL 無一致標籤可重現",
    "s4d": "capex 公告股價反應：需人工選事件窗與對照組，無客觀口徑",
    "s4e": "2027 capex 指引：只存在於法說口頭與第三方預估，沒有一手可抓數字",
    "s4f": "NVDA 供應與產能承諾：$279B 那個數字沒有標準 XBRL 標籤（PurchaseObligation 停在 2025-07），程式抓不到",
    "s5": "Samsung／SK hynix HBM 良率：只有媒體轉述，無一手揭露",
    "s6c": "Micron HBM 營收：公司自 FQ4 起不揭露金額，只有相對描述",
    "s8": "中國對手擴產（CXMT／YMTC IPO、客戶、產能）：純質化新聞判斷。供給側不計分觀測層 supply_expansion 保留",
    "s9": "週期終點時間軸校準：元指標、純人工判斷",
}
RETIRED_SINCE = "2026-10-22"


def load_json(path, default):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else default


def save_json(path, data):
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def calc_ma(prices, window):
    if len(prices) < window:
        return None
    return mean(prices[-window:])


# ──────────────────────────────────────────────
# Signal 1 sub-metrics
# ──────────────────────────────────────────────


def score_signal_1a(spot_history):
    """DDR5 spot price vs moving averages.
    Falling below MAs = cycle deteriorating = higher score.
    """
    key = "DDR5 16Gb (2Gx8) 4800/5600"
    series = spot_history.get("series", {}).get(key, [])
    if len(series) < 5:
        return None, "insufficient data"

    prices = [e["price"] for e in series]
    current = prices[-1]
    ma5 = calc_ma(prices, 5)
    ma20 = calc_ma(prices, 20)

    score = 4.0  # neutral base
    detail = []

    if ma5:
        if current > ma5:
            score -= 1.5  # bullish = earlier cycle = lower score
            detail.append(f">${ma5:.1f} 5MA ↑")
        else:
            score += 1.5
            detail.append(f"<{ma5:.1f} 5MA ↓")

    if ma20:
        if current > ma20:
            score -= 1.0
            detail.append(f">${ma20:.1f} 20MA ↑")
        else:
            score += 1.0
            detail.append(f"<{ma20:.1f} 20MA ↓")

    if ma5 and ma20:
        if ma5 > ma20:
            score -= 0.5  # golden cross = early cycle
            detail.append("golden cross")
        else:
            score += 0.5  # death cross = late cycle
            detail.append("death cross")

    if len(prices) >= 2:
        chg = (prices[-1] - prices[-2]) / prices[-2] * 100
        if chg > 0.5:
            score -= 0.5
            detail.append(f"+{chg:.1f}%")
        elif chg < -0.5:
            score += 0.5
            detail.append(f"{chg:.1f}%")

    score = max(1.0, min(9.0, score))
    return round(score, 1), f"DDR5 ${current:.1f} | " + " | ".join(detail)


# ──────────────────────────────────────────────
# 真合約價觀測（不評分）
# ──────────────────────────────────────────────
# 2026-08-19：真合約表自 8/10 起獨立累積。它現在還不能餵 s1b/s3（理由見下方
# score_signal_1b 的三條），但「不能評分」不等於「不用看」——華邦電／SNXX 的論點
# 失效線寫的是「4Q26 合約價轉負＝價格水準見頂確認」，那條線在此之前根本沒有自動來源，
# 只能靠手填的 s2 每隔一個月更新一次。這裡把可觀測的事實原樣攤開，不轉成分數：
#   ①期別與停滯天數 ②官方自報的期別變動% ③同口徑 DDR4 顆粒的 spot/contract 比值
# 比值序列同時是未來重新校準 s1b 門檻的原料，從今天開始累積。
sys.path.insert(0, str(Path(__file__).parent))
from contract_period import (  # noqa: E402
    DATA_AGE_DROP_DAYS,
    DATA_AGE_WARN_DAYS,
    DIE_PAIRS,
    VINTAGE_STALE_DAYS,
    data_age_days,
    freshness_status,
    latest_period,
    ratio_history,
    spot_mean,
)

# ──────────────────────────────────────────────
# 真合約價比值（2026-10-22 接入 s1b/s3 的量測層）
# ──────────────────────────────────────────────
# 合約價是期別價（免費層每月月底放上個月 2H），所以比值分兩種，用途不同：
#   aligned＝同一期別期間的現貨均價 ÷ 該期合約價。口徑正確、與 s1a 不共線，但晚 1.5~2 個月。
#   live   ＝今天現貨 ÷ 最近一期合約價。是當下的，但分母舊，日變動 100% 來自現貨＝與 s1a 共線。
# 評分只准用 aligned；live 只給人看「現在離上一期合約多遠」。
#
# ★2026-10-22 s1b／s3 拆用途（Jason 已採用）：兩者原本量同一個比值＝同一件事投兩票。
#   s3＝比值「水準」：現貨溢價 ≥20% 時合約價下一期幾乎必漲（10 期資料 1.37~3.00 期間合約價
#     每期都漲：14.8→50）；接近 1＝沒有再漲的壓力；跌破 1＝買方改買現貨、合約要降＝見頂。
#   s1b＝比值「方向」：最新一期對前兩期平均的變化率。水準還高但在收斂，比水準本身早。
# ★開關：Jason 2026-09-02 裁決 11/10 才校準，10/22 只問了「多高才合理」還沒拍板 → 先關著。
#   關著＝s1b/s3 分數 None、照降級規則重新正規化，signals.json 與看板列「若啟用」對照。
#   打開＝照下面門檻計分。舊表（0.90~1.10）已證實不適用（DDR4 顆粒比值恆 >1.10＝恆判綠燈），已刪。
RATIO_SCORING_ACTIVE = False

# s3 水準門檻（由高到低，下限含）
S3_LEVEL_BANDS = [
    (1.50, 2.0, "green"),
    (1.20, 3.0, "green"),
    (1.05, 5.0, "yellow"),
    (0.95, 6.5, "yellow"),
    (0.0, 8.5, "red"),
]
# s1b 方向門檻：Δ＝最新一期 ÷ 前兩期平均 − 1
S1B_DIR_UP, S1B_DIR_DOWN, S1B_DIR_PLUNGE = 0.05, -0.05, -0.15
S1B_PEAK_LEVEL = 1.05  # 水準 <1.05 且 Δ<0 → 8.5（比值已貼近 1 還在往下＝見頂型態）
S1B_MAX_SPAN_MONTHS = (
    5  # 三期跨度上限：容許中間缺兩個月（如 2H May 2026 無存檔），再多就不算方向
)


def _band_score(ratio, bands):
    for lower, score, status in bands:
        if ratio >= lower:
            return score, status
    return bands[-1][1], bands[-1][2]


def _status_of(score):
    return "green" if score < 5 else ("yellow" if score < 7 else "red")


def score_ratio_level(ratio):
    """s3：比值水準 → (分數, 燈號)。"""
    return _band_score(ratio, S3_LEVEL_BANDS)


def score_ratio_direction(delta, level):
    """s1b：比值方向 → 分數。水準已 <1.05 又在往下，直接給 8.5，不管跌幅大小。"""
    if level is not None and level < S1B_PEAK_LEVEL and delta < 0:
        return 8.5
    if delta >= S1B_DIR_UP:
        return 2.5
    if delta > S1B_DIR_DOWN:
        return 4.5
    if delta > S1B_DIR_PLUNGE:
        return 6.0
    return 7.5


def _month_index(period_key):
    return int(period_key[:4]) * 12 + int(period_key[5:7])


def ratio_direction(cr):
    """最新一期期別對齊比值 vs 前兩期平均。回傳 (dict 或 None, 不算的理由)。"""
    hist = [h for h in (cr.get("history") or []) if h.get("ratio") is not None]
    hist.sort(key=lambda h: h["period_key"])
    if not hist or hist[-1]["period_key"] != cr["period_key"]:
        return None, "最新一期沒有期別對齊比值（對齊視窗現貨天數不足）"
    if len(hist) < 3:
        return None, f"有比值的期別只有 {len(hist)} 期，方向至少要 3 期"
    last, p1, p2 = hist[-1], hist[-2], hist[-3]
    span = _month_index(last["period_key"]) - _month_index(p2["period_key"])
    if span > S1B_MAX_SPAN_MONTHS:
        return None, (
            f"三期跨 {span} 個月（{p2['period_full']}→{last['period_full']}），"
            f"缺期太多不算方向（上限 {S1B_MAX_SPAN_MONTHS}）"
        )
    base = (p1["ratio"] + p2["ratio"]) / 2
    return {
        "latest": last["ratio"],
        "latest_period": last["period_full"],
        "prev": [p2["period_full"], p1["period_full"]],
        "prev_mean": round(base, 3),
        "delta": round(last["ratio"] / base - 1, 4),
        "span_months": span,
    }, ""


def evaluate_ratio_signals(cr):
    """s1b（方向）與 s3（水準）的「若啟用」分數。開關只決定是否進總分，不決定算不算。

    回傳 {"gate": mode, "s1b": {...}, "s3": {...}}；mode：
      unavailable / dropped_expired / scored / scored_stale（過期照算但標示）
    """
    out = {"gate": "unavailable", "s1b": {"score": None}, "s3": {"score": None}}
    if not cr:
        msg = "無真合約價（contract_real_history.periods 為空）"
        out["s1b"]["detail"] = out["s3"]["detail"] = msg
        return out
    desc = _ratio_desc(cr)
    if cr["freshness"] == "expired":
        msg = (
            f"停用：合約價已過期（距期末 {cr['data_age_days']} 天 > {DATA_AGE_DROP_DAYS}）｜"
            + desc
        )
        out.update(gate="dropped_expired")
        out["s1b"]["detail"] = out["s3"]["detail"] = msg
        return out
    stale = cr["freshness"] == "stale"
    tag = "[合約價過期]" if stale else ""
    out["gate"] = "scored_stale" if stale else "scored"

    level = cr["primary"]["aligned"]["ratio"]
    if level is None:
        out["s3"]["detail"] = "期別對齊視窗內現貨天數不足｜" + desc
    else:
        sc, st = score_ratio_level(level)
        out["s3"] = {
            "score": sc,
            "status": st,
            "level": level,
            "detail": f"[{st}]{tag} 水準 {level:.2f}｜" + desc,
        }

    dirn, why = ratio_direction(cr)
    if dirn is None:
        out["s1b"]["detail"] = f"方向不算：{why}｜" + desc
    else:
        sc = score_ratio_direction(dirn["delta"], level)
        st = _status_of(sc)
        out["s1b"] = {
            "score": sc,
            "status": st,
            "direction": dirn,
            "detail": (
                f"[{st}]{tag} 方向 {dirn['delta'] * 100:+.1f}%"
                f"（{dirn['latest_period']} {dirn['latest']:.2f} vs "
                f"{'、'.join(dirn['prev'])} 平均 {dirn['prev_mean']:.2f}）"
            ),
        }
    return out


def build_contract_ratio(spot_history, contract_real, today):
    """真合約價比值的單一來源（s1b、s3、contract_watch、看板都讀這份）。無資料回 None。"""
    p = latest_period(contract_real)
    if not p:
        return None
    age = data_age_days(p, today)
    spot_series = spot_history.get("series", {})
    pairs = []
    for spot_key, c_key in DIE_PAIRS:
        item = (p.get("items") or {}).get(c_key)
        sp = spot_series.get(spot_key, [])
        if not item or not item.get("avg") or not sp:
            continue
        c = item["avg"]
        m, n = spot_mean(sp, p["start"], p["end"])
        # ★即時比值取最後一筆「有價格」的現貨：抓價失敗那天若寫進 None，sp[-1] 直接 TypeError
        last_sp = next((e for e in reversed(sp) if e.get("price")), None)
        if last_sp is None:
            continue
        pairs.append(
            {
                "pair": f"{spot_key} ÷ {c_key}",
                "contract": c,
                "aligned": {
                    "window": f"{p['start']}~{p['end']}",
                    "spot_mean": round(m, 3) if m is not None else None,
                    "spot_days": n,
                    "ratio": round(m / c, 3) if m is not None else None,
                },
                "live": {
                    "spot": last_sp["price"],
                    "spot_date": last_sp.get("date"),
                    "ratio": round(last_sp["price"] / c, 3),
                },
            }
        )
    if not pairs:
        return None
    return {
        "period": p["label"],
        "period_key": p["key"],
        "period_window": f"{p['start']}~{p['end']}",
        "source_updated": p.get("source_updated"),
        "first_seen": p.get("first_seen"),
        "data_age_days": age,
        "freshness": freshness_status(age),
        "thresholds": {
            "warn_days": DATA_AGE_WARN_DAYS,
            "drop_days": DATA_AGE_DROP_DAYS,
        },
        "primary": pairs[0],
        "pairs": pairs,
        "history": ratio_history(spot_history, contract_real),
        "scoring_active": RATIO_SCORING_ACTIVE,
    }


def _ratio_desc(cr):
    a, lv = cr["primary"]["aligned"], cr["primary"]["live"]
    al = f"{a['ratio']:.2f}" if a["ratio"] is not None else "n/a"
    name = cr["primary"]["pair"].split(" ÷ ")[-1]
    return (
        f"{name} 期別對齊 {al}（{cr['period']} {a['window']} 現貨均 {a['spot_mean']}"
        f" ÷ 合約 {cr['primary']['contract']}）｜即時 {lv['ratio']:.2f}"
        f"｜資料期別 {cr['period']}，距期末 {cr['data_age_days']} 天（{cr['freshness']}）"
    )


MODE_TEXT = {
    "scored": "真合約價計分中",
    "scored_stale": "計分中，但合約價已過期（標示）",
    "observe_only": "開關關閉：只量測不計分（11/10 決定是否開啟）",
    "dropped_expired": "合約價失效，比值不進計算",
    "unavailable": "無真合約價",
}


def contract_mode(ratio_eval):
    """總分實際採用的狀態：開關關著時，能算也只是 observe_only。"""
    gate = ratio_eval["gate"]
    if gate in ("scored", "scored_stale") and not RATIO_SCORING_ACTIVE:
        return "observe_only"
    return gate


def build_contract_status(ratio_eval, signal_scores, s1_sub):
    """降級規則寫死並攤開：s1b/s3 沒分數時權重去哪、看板怎麼標、若啟用會是幾分。"""
    mode = contract_mode(ratio_eval)
    out = {
        "mode": mode,
        "mode_text": MODE_TEXT.get(mode, mode),
        "scoring_active": RATIO_SCORING_ACTIVE,
        "switch": "calc_score.RATIO_SCORING_ACTIVE",
        "degrade_rule": (
            f"s1b 無分數 → S1 內部 {S1_WEIGHTS['1b']:.1%} 權重由 1a 吸收；"
            f"s3 無分數 → 總分的 {WEIGHTS['s3']:.0%} 權重由其餘有分數的訊號按原權重比例吸收"
            "（compute_cycle_score）。合約價距期末 >"
            f"{DATA_AGE_WARN_DAYS} 天＝過期：啟用時照算但標過期、黃燈告警；"
            f">{DATA_AGE_DROP_DAYS} 天＝失效：比值不進任何計算（連對照分數也不算）、紅燈告警。"
        ),
        "split_note": (
            "s3＝比值水準（≥1.50→2.0／1.20~1.50→3.0／1.05~1.20→5.0／0.95~1.05→6.5／<0.95→8.5）；"
            "s1b＝比值方向（最新一期 ÷ 前兩期平均 − 1：≥+5%→2.5／±5%→4.5／−5~−15%→6.0／≤−15%→7.5；"
            "水準 <1.05 且方向 <0→8.5；有比值的期別不足 3 期→不算）。"
        ),
        "s1b_preview": ratio_eval["s1b"],
        "s3_preview": ratio_eval["s3"],
    }
    s1b, s3 = ratio_eval["s1b"]["score"], ratio_eval["s3"]["score"]
    if s1b is None and s3 is None:
        return out
    parts = {"1a": s1_sub["1a"]["score"], "1b": s1b}
    live = {k: v for k, v in parts.items() if v is not None}
    s1_hypo = (
        round(
            sum(v * S1_WEIGHTS[k] for k, v in live.items())
            / sum(S1_WEIGHTS[k] for k in live),
            1,
        )
        if live
        else None
    )
    hypo_score, _ = compute_cycle_score(dict(signal_scores, s1=s1_hypo, s3=s3))
    out["if_activated"] = {
        "basis": "照上面門檻計分、開關打開時的總分（目前開關關著，此列不進總分）",
        "s1b": s1b,
        "s3": s3,
        "s1": s1_hypo,
        "cycle_score": hypo_score,
    }
    return out


def build_contract_watch(spot_history, contract_real, today, contract_ratio=None):
    """回傳觀測 dict；資料不足就回 None（不填中性值）。"""
    series = contract_real.get("series", {})
    if not series:
        return None

    vintage = contract_real.get("vintage")
    span = contract_real.get("vintage_span_days")
    stalled = span is not None and span >= VINTAGE_STALE_DAYS

    items, changes = {}, []
    for key, entries in series.items():
        if not entries:
            continue
        last = entries[-1]
        items[key] = {"price": last.get("price"), "change_pct": last.get("change_pct")}
        if last.get("change_pct") is not None:
            changes.append(last["change_pct"])

    spot_series = spot_history.get("series", {})
    # 2026-10-22：比值改由 build_contract_ratio 單一來源供應（期別對齊＋即時兩種），
    # 這裡只轉成看板用的扁平列；ratio 欄維持「即時」口徑以相容舊看板。
    ratios = []
    for pr in (contract_ratio or {}).get("pairs", []):
        ratios.append(
            {
                "pair": pr["pair"],
                "spot": pr["live"]["spot"],
                "contract": pr["contract"],
                "ratio": pr["live"]["ratio"],
                "spot_date": pr["live"]["spot_date"],
                "aligned_ratio": pr["aligned"]["ratio"],
                "aligned_window": pr["aligned"]["window"],
                "aligned_spot_mean": pr["aligned"]["spot_mean"],
            }
        )

    med = round(sorted(changes)[len(changes) // 2], 2) if changes else None

    # ★2026-09-02 Jason 裁決的過渡措施：s3（現貨÷合約）停用到 11 月中重新校準之前，
    #   把兩邊的變動率**並排**給人看，不相除、不評分。
    #   相除需要門檻（門檻正是現在沒有的東西），但「一邊在跌、另一邊還在漲」不需要門檻也看得出來。
    #   現貨通常領先合約 1~2 個月轉弱，這是儀表板目前唯一還摸得到那條線的地方。
    spot_key = "DDR5 16Gb (2Gx8) 4800/5600"
    s = spot_series.get(spot_key, [])
    spot_chg = None
    if len(s) >= 21 and s[-21].get("price"):
        spot_chg = round((s[-1]["price"] - s[-21]["price"]) / s[-21]["price"] * 100, 2)
    diverging = spot_chg is not None and med is not None and spot_chg < 0 < med
    # 背離之前還有一個中間狀態：兩邊都還在漲，但現貨的漲幅已經跟不上合約。
    # 現貨領先合約 1~2 個月，所以「現貨先鈍化」比「現貨轉負」更早出現。
    # 只判斷有／沒有，不給分——這層本來就是替代觀察不是訊號。
    spot_lagging = (
        spot_chg is not None and med is not None and 0 <= spot_chg < med and med > 0
    )

    return {
        "as_of": today,
        "vintage": vintage,
        "vintage_span_days": span,
        "vintage_stalled": stalled,
        "period_change_median_pct": med,
        "spot_vs_contract": {
            "spot_key": spot_key,
            "spot_chg_20d_pct": spot_chg,
            "contract_period_chg_pct": med,
            "diverging": diverging,
            "spot_lagging": spot_lagging,
            "state": (
                "背離：現貨已轉負、合約仍漲"
                if diverging
                else (
                    "現貨鈍化：兩邊都漲，但現貨漲幅已低於合約"
                    if spot_lagging
                    else "同向"
                )
            ),
            "note": (
                "s3 停用期間的替代觀察：現貨 20 日變動與合約期別變動並排，不相除也不評分。"
                "現貨通常領先合約 1~2 個月，所以順序是『現貨鈍化 → 現貨轉負 → 合約跟跌』。"
            ),
        },
        "items": items,
        "die_ratios": ratios,
        "scored": False,
        "note": (
            "期別價非日價，同期別內每日相同；期別變動%為 TrendForce 自報（對上一個公開期別）。"
            "die_ratios：ratio＝即時（今天現貨÷最近一期合約，與 s1a 共線），"
            "aligned_ratio＝期別對齊（同期間現貨均價÷該期合約，s1b/s3 評分只認這個）。"
            "★校準樣本要數「期別」不是數「天」：逐日的即時比值只是同一個分母配不同現貨。"
        ),
    }


# ──────────────────────────────────────────────
# DDR5/DDR4 比值觀測（不評分）— 2026-09-02
# ──────────────────────────────────────────────
# s1c 停用後留下的空位。停用理由不是「品項選錯」而是「分母被供給端人為決策主導」：
# DDR4 自 2025-10 起比 DDR5 貴，是原廠停產減量的結果，不是需求強弱。
# 所以現在無論比哪一組，量到的都是 DDR4 退場速度。
# 這裡把三組口徑同時攤開累積，讓將來重新校準時有得選、也看得出彼此差多少。
# ★解除條件寫死：樣本要**跨越一次 DDR4 價格轉折**（例如 DDR4 由漲轉跌或反之），
#   不是「累積夠多天」——現有 297 天全部落在同一種狀態裡，再多天也是同一個特例。
RATIO_PAIRS = [
    ("DDR5 16Gb (2Gx8) 4800/5600", "DDR4 16Gb (2Gx8) 3200", "同容量（原程式比的這組）"),
    (
        "DDR5 16Gb (2Gx8) 4800/5600",
        "DDR4 8Gb (1Gx8) 3200",
        "異容量（舊階梯疑似照這組校準）",
    ),
]


def build_ratio_watch(spot_history, today, lookback=60):
    """DDR5/DDR4 比值觀測，回傳現值與區間；資料不足回 None（不填中性值）。"""
    series = spot_history.get("series", {})
    rows = []
    for num_key, den_key, label in RATIO_PAIRS:
        num, den = series.get(num_key, []), series.get(den_key, [])
        if not num or not den:
            continue
        by_date = {e["date"]: e["price"] for e in den if e.get("price")}
        pairs = [
            (e["date"], e["price"] / by_date[e["date"]])
            for e in num
            if e.get("price") and by_date.get(e["date"])
        ]
        if not pairs:
            continue
        window = [r for _, r in pairs[-lookback:]]
        rows.append(
            {
                "pair": f"{num_key} ÷ {den_key}",
                "label": label,
                "ratio": round(pairs[-1][1], 3),
                "as_of": pairs[-1][0],
                "window_days": len(window),
                "window_min": round(min(window), 3),
                "window_max": round(max(window), 3),
                "n_total": len(pairs),
            }
        )
    if not rows:
        return None

    # DDR4 自身的方向＝解除條件在等的那件事，一併攤出來
    ddr4 = series.get("DDR4 16Gb (2Gx8) 3200", [])
    ddr4_trend = None
    if len(ddr4) >= 21:
        now, past = ddr4[-1]["price"], ddr4[-21]["price"]
        ddr4_trend = {
            "price": now,
            "chg_20d_pct": round((now - past) / past * 100, 2),
            "direction": "上漲" if now > past else ("下跌" if now < past else "持平"),
        }
    return {
        "as_of": today,
        "scored": False,
        "rows": rows,
        "ddr4_trend": ddr4_trend,
        "release_condition": (
            "s1c 已於 2026-10-22 移除，本層只觀測。若日後要恢復計分，條件是樣本跨越一次 DDR4 價格轉折"
            "（由漲轉跌或由跌轉漲）；只累積天數不算——現有歷史全落在 DDR4 停產稀缺的同一種狀態。"
        ),
    }


def score_signal_1b(ratio_eval):
    """2026-10-22 起：s1b＝期別對齊比值的「方向」（s3 是水準），見 evaluate_ratio_signals。
    RATIO_SCORING_ACTIVE 關著時回 None（若啟用的分數放在 contract_status.if_activated）。
    舊版（讀 contract_history、DDR5 顆粒、0.90~1.10 表）在 git 歷史（2026-10-22 之前的 calc_score.py）。

    歷史紀錄——2026-08-05 停用：TrendForce 的 dram_spot 與 dram_contract 已回傳同一份頁面，
    兩檔歷史 56 個重疊日期價格完全相同，比值恆為 1.00。這不是弱訊號，是沒有量測。
    回傳 None 讓上層排除並重新正規化權重，不要填中性值假裝測過。

    ★2026-08-19 覆核（真合約表已於 8/10 起獨立累積，仍維持停用）——三個理由，
      任一條成立就不該給分，目前三條全成立：
      ① 真合約表沒有 DDR5 顆粒，只有 DDR5 8GB SO-DIMM 模組。模組價含 PCB/SPD/組裝，
         與顆粒現貨相除得到的不是供需鬆緊，是模組加工價差。
      ② 改用同口徑的 DDR4 顆粒對（spot 89.4 / contract 42.0）比值 2.13，
         整個落在門檻表（0.90~1.10）之外 → 恆判 green 2.0＝假確認，不是量測。
      ③ 合約價是半月報價、期別停在 2H Jun（vintage_log 追蹤中）。分母幾週不動，
         日頻比值的變動 100% 來自分子 spot → 與 s1a 共線，等於同一件事投兩票。
      解除條件：期別恢復前進（③解）＋累積 ≥60 個交易日的比值分布可重新校準門檻（②解）。
      在那之前 spot/contract 只做「觀測不評分」，見 main() 的 contract_watch。
    ★2026-10-22 對照三條：①仍成立（改用 DDR4 顆粒，DDR5 顆粒合約價只給付費會員）
      ②仍成立（DDR4 16Gb 期別對齊比值 2H Oct 2025~2H Aug 2026 共 10 期落在 1.37~3.00，
      全部 >1.10，舊表恆判綠燈＝無鑑別力）③已解：改用期別對齊比值，分母與分子同期，
      不再與 s1a 共線；期別每月月底前進一次是免費層的正常節奏（實測），不是停更。
      ②的解法＝拆用途重訂門檻（水準給 s3、方向給 s1b），不再拿舊表硬套。
    """
    e = ratio_eval["s1b"]
    if not RATIO_SCORING_ACTIVE:
        return None, "開關關閉（11/10 決定是否開啟）｜若啟用：" + (
            f"{e['score']}｜{e['detail']}" if e["score"] is not None else e["detail"]
        )
    return e["score"], e["detail"]


# s1c（DDR5÷DDR4）2026-10-22 移除：前提已被推翻（DDR4 因停產減量長期貴於 DDR5，
# 這個比值量到的是 DDR4 退場速度，換哪一組品項都改不掉），自 9/02 起就是 None。
# 觀測層 ratio_watch 保留。舊函式在 git 歷史。
S1_WEIGHTS_V3 = {"1a": 0.50, "1b": 0.30, "1c": 0.20}
S1_WEIGHTS = _renorm(S1_WEIGHTS_V3, ["1a", "1b"])  # 1a 62.5%／1b 37.5%


def _composite(subs, weights):
    """複合訊號：缺項排除後重新正規化；全缺回 None（不填 5.0）。"""
    live = {k: s for k, s in subs.items() if s is not None}
    if not live:
        return None
    w = sum(weights[k] for k in live)
    return round(sum(s * weights[k] for k, s in live.items()) / w, 1)


def score_signal_1_composite(spot_history, ratio_eval):
    """S1 = 62.5% × 1a + 37.5% × 1b（V3 的 50/30 按比例放大）。

    2026-08-05 改：缺項不再填中性值，改為排除後重新正規化（與 s4/s8 同慣例）。
    原本 s1a 無資料時填 5.0、s1b 無資料時抄 s1a，等於把「沒量到」報成「量到中性」，
    在序列重建的暖機期會直接偽造一個訊號。
    """
    subs = {
        "1a": score_signal_1a(spot_history),
        "1b": score_signal_1b(ratio_eval),
    }
    detail = {k: {"score": v[0], "detail": v[1]} for k, v in subs.items()}
    score = _composite({k: v[0] for k, v in subs.items()}, S1_WEIGHTS)
    if score is None:
        detail["_note"] = "1a/1b 全部無資料，S1 不計入總分"
        return None, detail
    excluded = [k for k in S1_WEIGHTS if subs[k][0] is None]
    if excluded:
        detail["_note"] = f"已排除 {'/'.join(excluded)}，權重在其餘子項間重新正規化"
    return score, detail


# ──────────────────────────────────────────────
# Signal 2: Monthly contract QoQ
# ──────────────────────────────────────────────


# 2026-10-22 起 s2 改自動：真合約價（contract_real_history.periods）的期別間變動。
#   原手填 s2 用的是 TrendForce 新聞稿的「下一季預估」（前瞻）；這裡量的是「已成交的過去三個月」
#   （落後）。換來的是可重現與不會過期，代價是少了前瞻——轉折會晚一期才看得到。
#   舊 auto（讀 contract_history）讀的其實是現貨，已刪。
#   品項：DDR5 8GB SO-DIMM（主流 PC 模組）＋DDR4 16Gb 顆粒，兩者等權平均。
#     DDR4 受停產稀缺放大（漲得比 DDR5 兇），單用 DDR4 會高估動能，所以一定要配 DDR5 模組。
#   基期：同半月的「三個月前」那期；免費層有缺期（如 2H May 2026 無存檔），
#     依序改用 4、2、5 個月前，並以幾何換算成三個月變動（(P/P0)^(3/m) − 1），不跨期硬補。
#   階梯沿用 V3 auto 的 QoQ 階梯（>40→2.0／>20→2.5／>10→3.5／>0→4.5／>−5→5.5／>−15→7.0／其餘 8.5），
#     手填時代 3.5 對應「10~20%」也是同一張表。
S2_ITEMS = ["DDR5 8GB SO-DIMM", "DDR4 16Gb 2Gx8"]
S2_BASE_PREF = (3, 4, 2, 5)
S2_LADDER = [(40, 2.0), (20, 2.5), (10, 3.5), (0, 4.5), (-5, 5.5), (-15, 7.0)]


def _s2_ladder(qoq_pct):
    for lower, score in S2_LADDER:
        if qoq_pct > lower:
            return score
    return 8.5


def score_signal_2_contract(contract_real, today):
    """回傳 (score 或 None, detail, info)。info 帶資料期別、first_seen、下一期應出現的期限。"""
    periods = contract_real.get("periods") or {}
    if not periods:
        return None, "無真合約價期別（contract_real_history.periods 為空）", {}
    latest = periods[max(periods)]
    age = data_age_days(latest, today)
    fr = freshness_status(age)
    info = {
        "period": f"{latest['label']} {latest['year']}",
        "period_key": latest["key"],
        "first_seen": latest.get("first_seen"),
        "data_age_days": age,
        "freshness": fr,
        # 下一期該出現的期限＝contract_period 自己對「過期」的定義（期末 + 75 天），單一來源
        "next_due": (
            date.fromisoformat(latest["end"]) + timedelta(days=DATA_AGE_WARN_DAYS)
        ).isoformat(),
    }
    tail = f"｜資料期別 {info['period']}，距期末 {age} 天（{fr}）"
    if fr == "expired":
        return (
            None,
            f"停用：合約價已過期（距期末 {age} 天 > {DATA_AGE_DROP_DAYS}）" + tail,
            info,
        )
    same_half = {
        p["year"] * 12 + p["month"]: p
        for p in periods.values()
        if p.get("half") == latest.get("half")
    }
    li = latest["year"] * 12 + latest["month"]
    rows = []
    for item in S2_ITEMS:
        cur = ((latest.get("items") or {}).get(item) or {}).get("avg")
        if not cur:
            continue
        for m in S2_BASE_PREF:
            bp = same_half.get(li - m)
            base = (
                ((bp or {}).get("items") or {}).get(item, {}).get("avg") if bp else None
            )
            if base:
                q = (cur / base) ** (3 / m) - 1
                rows.append(
                    {
                        "item": item,
                        "latest": cur,
                        "base": base,
                        "base_period": f"{bp['label']} {bp['year']}",
                        "months": m,
                        "qoq_equiv_pct": round(q * 100, 2),
                    }
                )
                break
    info["rows"] = rows
    if not rows:
        return None, "找不到 2~5 個月前的同半月期別可比" + tail, info
    qoq = sum(r["qoq_equiv_pct"] for r in rows) / len(rows)
    info["qoq_equiv_pct"] = round(qoq, 2)
    score = _s2_ladder(qoq)
    parts = "；".join(
        f"{r['item']} {r['base']}→{r['latest']}（{r['base_period']} 起 {r['months']} 個月"
        + ("" if r["months"] == 3 else "，換算 3 個月")
        + f" {r['qoq_equiv_pct']:+.1f}%）"
        for r in rows
    )
    stale = "[合約價過期]" if fr == "stale" else ""
    return (
        score,
        f"[auto]{stale} 合約價 3 個月變動 {qoq:+.1f}%（{parts}）" + tail,
        info,
    )


# ──────────────────────────────────────────────
# Signal 4: Hyperscaler composite (V3: 6 sub-metrics)
# ──────────────────────────────────────────────

S4_WEIGHTS_V3 = {
    "4a": 0.25,  # capex revision direction
    "4b": 0.18,  # cloud revenue growth（V4 移除）
    "4c": 0.18,  # backlog vs capex
    "4d": 0.12,  # capex announcement stock reaction（V4 移除）
    "4e": 0.12,  # 2027 capex guidance（V4 移除）
    "4f": 0.15,  # NVDA supply commitments（V4 移除：無標準 XBRL 標籤）
}
S4_WEIGHTS = _renorm(S4_WEIGHTS_V3, ["4a", "4c"])  # 4a 58.1%／4c 41.9%

HYPERSCALERS = ("GOOGL", "MSFT", "AMZN", "META")
RPO_FIRMS = ("MSFT", "GOOGL")  # AMZN 2020 起不用標準標籤揭露 RPO、META 沒有 RPO
# 4a：四家合計單季 capex 的 YoY（由高到低，下限含）；QoQ<0 加 0.5、QoQ<−10% 加 1.0（第一次砍支出）
S4A_YOY_BANDS = [(40, 2.0), (20, 3.0), (5, 4.5), (-5, 6.0)]
# 4c：兩家合計 RPO 的 YoY；RPO 成長跑輸同兩家 capex 成長＝積壓追不上花錢速度，加 1.0
S4C_YOY_BANDS = [(50, 2.0), (25, 3.0), (10, 4.5), (0, 6.0)]


def _ladder_ge(value, bands, floor_score):
    for lower, score in bands:
        if value >= lower:
            return score
    return floor_score


def _sec_company(sec, ticker):
    return ((sec or {}).get("companies") or {}).get(ticker) or {}


def _sec_company_list(sec):
    return sorted(((sec or {}).get("companies") or {}).keys())


def _qmap(sec, ticker, name):
    rows = (_sec_company(sec, ticker).get("quarterly") or {}).get(name) or []
    return {r["end"]: r for r in rows}


def _imap(sec, ticker, name):
    rows = (_sec_company(sec, ticker).get("instant") or {}).get(name) or []
    return {r["end"]: r for r in rows}


def _qend_shift(end, quarters):
    """日曆季末日平移 n 季（2026-06-30, -4 → 2025-06-30）。只給日曆季公司用。"""
    y, m = int(end[:4]), int(end[5:7]) + 3 * quarters
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def _cache_note(sec, tickers):
    """有公司沿用舊快取時要寫進明細：分數是用哪天抓到的資料算的。"""
    stale = [
        f"{t} 沿用 {_sec_company(sec, t).get('fetched_at', '?')} 的抓取"
        for t in tickers
        if _sec_company(sec, t).get("stale_cache")
    ]
    return f"｜★{'、'.join(stale)}" if stale else ""


def score_signal_4a(sec):
    maps = {t: _qmap(sec, t, "capex") for t in HYPERSCALERS}
    missing = [t for t, m in maps.items() if not m]
    if missing:
        return None, f"無 capex 資料：{'/'.join(missing)}", {}
    common = set.intersection(*(set(m) for m in maps.values()))
    latest = next(
        (
            e
            for e in sorted(common, reverse=True)
            if _qend_shift(e, -1) in common and _qend_shift(e, -4) in common
        ),
        None,
    )
    if latest is None:
        return None, "四家沒有共同的「本季＋上季＋去年同季」", {}

    def tot(e):
        return sum(maps[t][e]["val"] for t in HYPERSCALERS)

    cur, prv, ya = (
        tot(latest),
        tot(_qend_shift(latest, -1)),
        tot(_qend_shift(latest, -4)),
    )
    yoy, qoq = (cur / ya - 1) * 100, (cur / prv - 1) * 100
    score = _ladder_ge(yoy, S4A_YOY_BANDS, 8.0)
    if qoq < -10:
        score += 1.0
    elif qoq < 0:
        score += 0.5
    score = min(9.0, score)
    ahead = [t for t in HYPERSCALERS if max(maps[t]) > latest]
    info = {
        "quarter_end": latest,
        "total_usd_b": round(cur / 1e9, 2),
        "yoy_pct": round(yoy, 1),
        "qoq_pct": round(qoq, 1),
        "by_company_usd_b": {
            t: round(maps[t][latest]["val"] / 1e9, 2) for t in HYPERSCALERS
        },
        "available": max(maps[t][latest]["available"] for t in HYPERSCALERS),
    }
    detail = (
        f"[auto] 四大單季 capex 合計 ${info['total_usd_b']}B（{latest} 季）"
        f"｜YoY {yoy:+.1f}%｜QoQ {qoq:+.1f}%｜"
        + " ".join(f"{t} {v}" for t, v in info["by_company_usd_b"].items())
        + (f"｜{'/'.join(ahead)} 已申報下一季、等其餘公司" if ahead else "")
        + _cache_note(sec, HYPERSCALERS)
    )
    return round(score, 1), detail, info


def score_signal_4c(sec):
    rpo = {t: _imap(sec, t, "rpo") for t in RPO_FIRMS}
    cap = {t: _qmap(sec, t, "capex") for t in RPO_FIRMS}
    if any(not rpo[t] or not cap[t] for t in RPO_FIRMS):
        return None, "無 RPO 或 capex 資料（MSFT／GOOGL）", {}
    common = set.intersection(*(set(rpo[t]) & set(cap[t]) for t in RPO_FIRMS))
    latest = next(
        (e for e in sorted(common, reverse=True) if _qend_shift(e, -4) in common), None
    )
    if latest is None:
        return None, "MSFT／GOOGL 沒有共同的「本季＋去年同季」RPO 與 capex", {}
    ya = _qend_shift(latest, -4)
    r_now = sum(rpo[t][latest]["val"] for t in RPO_FIRMS)
    r_ya = sum(rpo[t][ya]["val"] for t in RPO_FIRMS)
    c_now = sum(cap[t][latest]["val"] for t in RPO_FIRMS)
    c_ya = sum(cap[t][ya]["val"] for t in RPO_FIRMS)
    rpo_yoy, cap_yoy = (r_now / r_ya - 1) * 100, (c_now / c_ya - 1) * 100
    score = _ladder_ge(rpo_yoy, S4C_YOY_BANDS, 8.0)
    lagging = rpo_yoy < cap_yoy
    if lagging:
        score = min(9.0, score + 1.0)
    info = {
        "quarter_end": latest,
        "rpo_usd_b": round(r_now / 1e9, 1),
        "rpo_yoy_pct": round(rpo_yoy, 1),
        "capex_yoy_pct": round(cap_yoy, 1),
        "backlog_lagging_capex": lagging,
        "available": max(rpo[t][latest]["available"] for t in RPO_FIRMS),
    }
    detail = (
        f"[auto] MSFT＋GOOGL RPO ${info['rpo_usd_b']}B（{latest}）YoY {rpo_yoy:+.1f}%"
        f" vs 同兩家 capex YoY {cap_yoy:+.1f}%"
        + ("→積壓成長跑輸花錢速度（+1.0）" if lagging else "→積壓跑贏花錢速度")
        + "｜★RPO 含單一大客戶長約（如 MSFT 的 OpenAI），集中度風險不在這個數字裡"
        + _cache_note(sec, RPO_FIRMS)
    )
    return round(score, 1), detail, info


def calc_signal_4_composite(s4_sub):
    """缺項排除後重新正規化；全缺回 None（2026-10-22 前是回 5.0＝把沒量到報成中性）。"""
    return _composite(
        {k: (s4_sub.get(k) or {}).get("score") for k in S4_WEIGHTS}, S4_WEIGHTS
    )


# ──────────────────────────────────────────────
# Signal 6: Micron composite (V3: 3 sub-metrics)
# ──────────────────────────────────────────────

S6_WEIGHTS_V3 = {
    "6a": 0.50,  # GM trajectory (auto)
    "6b": 0.30,  # V3＝財報 vs 指引（手填）；V4＝營收日均 QoQ（自動，SEC XBRL）
    "6c": 0.20,  # HBM revenue（V4 移除：Micron 不揭露金額）
}
S6_WEIGHTS = _renorm(S6_WEIGHTS_V3, ["6a", "6b"])  # 6a 62.5%／6b 37.5%

# 6b：Micron 營收「日均」QoQ。用日均是因為 53 週年的第四季有 14 週（FY26 FQ4 98 天 vs 91 天），
#   直接比 QoQ 會多出約 7.7pp 純粹是多一週。為什麼不跟 6a 重複：毛利率在 85% 以上接近天花板，
#   delta 會鈍化；營收動能在毛利率見頂後仍有資訊（量×價的斜率）。與 s2（合約價）部分共線，已知。
S6B_QOQ_BANDS = [(20, 2.0), (10, 3.0), (0, 4.5), (-10, 6.5)]


def score_signal_6b(sec):
    rows = (_sec_company(sec, "MU").get("quarterly") or {}).get("revenue") or []
    if len(rows) < 2:
        return None, "Micron 營收季度不足 2 季", {}
    cur, prv = rows[-1], rows[-2]
    expect_prev_end = (date.fromisoformat(cur["start"]) - timedelta(days=1)).isoformat()
    if prv["end"] != expect_prev_end:
        return None, f"Micron 營收季度不連續（{prv['end']} → {cur['start']}）", {}
    d_cur, d_prv = cur["val"] / cur["days"], prv["val"] / prv["days"]
    qoq = (d_cur / d_prv - 1) * 100
    raw = (cur["val"] / prv["val"] - 1) * 100
    score = _ladder_ge(qoq, S6B_QOQ_BANDS, 8.0)
    info = {
        "quarter_end": cur["end"],
        "revenue_usd_b": round(cur["val"] / 1e9, 2),
        "days": cur["days"],
        "qoq_per_day_pct": round(qoq, 1),
        "qoq_raw_pct": round(raw, 1),
        "available": cur["available"],
    }
    detail = (
        f"[auto] Micron 營收 ${info['revenue_usd_b']}B（{cur['end']}，{cur['days']} 天）"
        f"｜日均 QoQ {qoq:+.1f}%（未調天數 {raw:+.1f}%）" + _cache_note(sec, ["MU"])
    )
    return score, detail, info


def score_signal_6a(micron_gross):
    """Micron GM trajectory. RISING GM = early cycle = LOW score.
    Yellow: first quarter of decline. Red: consecutive decline.
    """
    entries = micron_gross.get("entries", [])
    if not entries:
        return None, "no data"

    latest = entries[-1]
    margin = latest["margin_pct"]
    period = latest["date"][:7]

    if len(entries) >= 2:
        delta = margin - entries[-2]["margin_pct"]
    else:
        delta = 0.0

    # Score based on TRAJECTORY, not absolute level
    if margin < 0:
        base = 1.0  # deep trough = very early upcycle
    elif margin < 15:
        base = 1.5  # trough recovery = early cycle
    elif margin < 30:
        base = 2.5  # recovering
    else:
        # High margin territory: direction is the key signal
        if delta > 5:
            base = 2.5  # accelerating up
        elif delta > 2:
            base = 3.0  # steadily rising
        elif delta > 0:
            base = 3.5  # barely rising, may plateau
        elif delta > -3:
            base = 5.5  # plateau / first sign of stall
        elif delta > -8:
            base = 7.0  # one quarter meaningful decline (V3 Yellow trigger)
        else:
            base = 9.0  # sharp decline (V3 Red trigger)

    trend = ("↑" if delta > 0 else "↓" if delta < 0 else "→") + f" {delta:+.1f}pp"
    return round(base, 1), f"GM {margin:.1f}% ({period}) {trend}"


def _sub_entry(score, detail):
    return {
        "score": score,
        "detail": detail,
        "status": "unavailable" if score is None else _status_of(score),
    }


def calc_signal_6_composite(micron_gross, sec):
    """S6 = 62.5% × 6a（毛利率軌跡）+ 37.5% × 6b（營收日均 QoQ），缺項排除後正規化。
    2026-10-22 前缺項填 5.0，已改成排除。"""
    s6a, d6a = score_signal_6a(micron_gross)
    s6b, d6b, info6b = score_signal_6b(sec)
    sub = {"6a": _sub_entry(s6a, d6a), "6b": _sub_entry(s6b, d6b)}
    return _composite({"6a": s6a, "6b": s6b}, S6_WEIGHTS), sub, info6b


# ──────────────────────────────────────────────
# Signal 7: Micron 存貨天數（2026-10-22 起自動，取代手填的三星／海力士庫存週數）
# ──────────────────────────────────────────────
# 為什麼換成 Micron：三星／SK hynix 不在 SEC 申報，庫存週數只有媒體轉述（5/27 以來從未取得一手數字）。
# Micron 的 DIO 可由 10-Q／10-K 的 InventoryNet 與銷貨成本重算，而且口徑與公司自報一致：
#   DIO＝(期初＋期末存貨)/2 × 當季天數 ÷ 當季銷貨成本
#   FY26 FQ4 重算 129.2 天、FQ3 119.7 天，與公司說的「129 天、QoQ +9」吻合。
# 看「變化」為主：Micron 結構性持有約 120 天存貨，水準本身不是警訊；
#   2023~24 過剩期 DIO 150~160 天，所以 ≥150 再加 1 分。
# ★已知代價：公司說 FQ4 存貨上升有非需求原因（停產前備貨、獎金資本化），程式看不到理由，照數字給分。
S7_DELTA_BANDS = [(-10, 2.0), (0, 3.0), (10, 4.5), (20, 6.0)]  # Δ ≤ 門檻 → 分數
S7_GLUT_DIO = 150


def score_signal_7(sec):
    cogs = (_sec_company(sec, "MU").get("quarterly") or {}).get("cogs") or []
    inv = _imap(sec, "MU", "inventory")

    def dio(row):
        begin = (date.fromisoformat(row["start"]) - timedelta(days=1)).isoformat()
        if row["end"] not in inv or begin not in inv or not row["val"]:
            return None
        avg = (inv[row["end"]]["val"] + inv[begin]["val"]) / 2
        return avg * row["days"] / row["val"]

    pts = [(r, dio(r)) for r in cogs]
    pts = [(r, d) for r, d in pts if d is not None]
    if len(pts) < 2:
        return None, "Micron 存貨／銷貨成本不足兩季可算 DIO 變化", {}
    (r_now, d_now), (r_prv, d_prv) = pts[-1], pts[-2]
    if (date.fromisoformat(r_now["start"]) - timedelta(days=1)).isoformat() != r_prv[
        "end"
    ]:
        return None, f"Micron DIO 季度不連續（{r_prv['end']} → {r_now['start']}）", {}
    delta = d_now - d_prv
    score = next((s for lim, s in S7_DELTA_BANDS if delta <= lim), 7.5)
    if d_now >= S7_GLUT_DIO:
        score = min(9.0, score + 1.0)
    info = {
        "quarter_end": r_now["end"],
        "dio_days": round(d_now, 1),
        "dio_prev_days": round(d_prv, 1),
        "delta_days": round(delta, 1),
        "inventory_usd_b": round(inv[r_now["end"]]["val"] / 1e9, 2),
        "available": max(r_now["available"], inv[r_now["end"]]["available"]),
    }
    detail = (
        f"[auto] Micron DIO {d_now:.1f} 天（{r_now['end']}）vs 上季 {d_prv:.1f}｜"
        f"Δ {delta:+.1f} 天｜期末存貨 ${info['inventory_usd_b']}B"
        + (f"｜≥{S7_GLUT_DIO} 天過剩區（+1.0）" if d_now >= S7_GLUT_DIO else "")
        + _cache_note(sec, ["MU"])
    )
    return score, detail, info


# ──────────────────────────────────────────────
# Cycle Score & Status
# ──────────────────────────────────────────────


def compute_cycle_score(signal_scores):
    """2026-08-05 改：無資料的訊號排除後重新正規化，不再以 5.0 頂替。

    舊寫法 signal_scores.get(k, 5.0) 會把「沒量到」當成「量到中性 5.0」，
    在暖機期或訊號停用時會把總分往中間拉，看起來像市場變化。
    與 calc_signal_4_composite / calc_signal_8_composite 的既有慣例一致。
    回傳 (分數, 被排除的訊號清單)；全部缺項時分數為 None。
    """
    total, w_sum, excluded = 0.0, 0.0, []
    for k, w in WEIGHTS.items():
        score = signal_scores.get(k)
        if score is None:
            excluded.append(k)
            continue
        total += score * w
        w_sum += w
    if w_sum == 0:
        return None, excluded
    return round(total / w_sum, 2), excluded


# ──────────────────────────────────────────────
# 新鮮度 / 過期守門（2026-09-02 重寫成單一來源）
# ──────────────────────────────────────────────
# 這裡原本是兩套邏輯：過期偵測走一份手寫白名單，新鮮度權重走另一份 parts 字典。
# 兩套遲早分岔，而且分岔了沒有任何機制會發現——實際上早就分岔了：
#   ① 白名單裡沒有 6c、8b、8d、8e，這四個子項永遠不會被喊過期；
#   ② 過期偵測的 `entry.get("updated") or manual["_last_updated"]` 這個 fallback
#      會讓「從來沒填過戳記」的子項自動繼承全域日期＝假新鮮（8b/8d/8e 就是這樣，
#      它們的內容其實停在 5/27，卻被當成 7/31）；
#   ③ 新鮮度那邊的 _sub_stamps 只收有戳記的子項，沒戳記的被靜靜跳過，
#      父訊號照樣拿到一個「最舊 = 7/31」的好看數字。
# 改法：所有手填葉節點自動展開 → 一份資料 → 過期告警與新鮮度權重都從它算，
# 沒有戳記就是沒有戳記，不繼承、不猜、不當成新的。
STALE_WARN_DAYS, STALE_RED_DAYS = 30, 60

# 可信度門檻（fresh 權重佔有效權重的比例）。
# ★首版為拍板值，不是實測校準：定 0.70／0.40 的理由是「一半以上權重是舊資料時，
#   分數已經比較像歷史快照而不是現況」。校準方式＝下次補完 manual 後，比對補前補後
#   的分數落差有多大，若落差 <0.5 分表示門檻可以放寬，>1.5 分表示要收緊。
RELIABILITY_OK, RELIABILITY_DEGRADED = 0.70, 0.40


def iter_manual_leaves(manual):
    """展開 manual_inputs 中所有「帶 score 的葉節點」。

    回傳 [(leaf_key, parent_signal, entry)]，例如
    ("s2", "s2", {...})、("s4a", "s4", {...})、("s1c", "s1", {...})。
    新增子項會自動納管，不必回來改白名單——白名單漏項這件事本身沒有守門。
    """
    leaves = []
    for top, val in manual.items():
        if top.startswith("_") or top == "events" or not isinstance(val, dict):
            continue
        if "score" in val:  # s2/s3/s5/s7/s9 單層
            leaves.append((top, top, val))
            continue
        for sub, entry in sorted(val.items()):  # s1_sub/s4/s6_sub/s8 子項
            if isinstance(entry, dict) and "score" in entry:
                leaves.append((f"s{sub}", f"s{sub[0]}", entry))
    return leaves


def _parse_date(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def build_freshness(manual, auto_stamps, today, excluded_signals):
    """單一新鮮度來源：手填葉節點 + 自動源，聚合到父訊號後按權重分桶。

    auto_stamps: {父訊號: [(來源標籤, date 或 None), ...]}
    回傳 dict，同時含葉節點層的 stale_items / unstamped_items，
    讓告警能講「哪一個子項舊」而不是只講「這支訊號舊」。
    """
    today_d = date.fromisoformat(today)
    per_signal, stale_items, unstamped_items = {}, [], []
    awaiting_items, overdue_items = [], []

    # 先把葉節點與自動源歸到父訊號底下
    collected = {
        k: {"stamps": [], "sources": set(), "leaves": [], "awaiting": []}
        for k in WEIGHTS
    }
    for leaf_key, parent, entry in iter_manual_leaves(manual):
        if parent not in collected:
            continue
        # ★停用中的子項不參與新鮮度（比照被排除的父訊號）：它的分數沒有進總分，
        #   拿它的日期去影響父訊號的新鮮度只會失真——可能讓父訊號看起來比實際新，
        #   也可能因為它沒人維護而拖累父訊號。它的待辦另由 disabled_signals 常駐追蹤。
        if entry.get("scored") is False or entry.get("disabled_since"):
            continue
        d = _parse_date(entry.get("updated"))
        collected[parent]["sources"].add("manual")
        collected[parent]["leaves"].append(leaf_key)
        # ★2026-09-02：「該來的資料還沒到」與「該更新卻沒更新」不是同一件事。
        #   6b/6c 要等 Micron 開牌、4b/4c 要等雲端季報——在那之前天天喊過期，
        #   結果就是所有告警一起被忽略（記憶索引那邊已經踩過這個坑：
        #   守門天天喊、喊到沒人看）。允許葉節點宣告 next_due 暫緩，但有三條硬規則：
        #     ① next_due 只能指向外部事件日（財報、公告、開牌），不能是「我下次想更新的日子」；
        #     ② 過了 next_due 還沒更新 → 直接 overdue 紅燈，沒有 30 天寬限；
        #     ③ 卡在人（等裁決、等決定）的項目不准用 next_due，那種就是該一直喊。
        due = _parse_date(entry.get("next_due"))
        if due and d and today_d < due and d <= due:
            collected[parent]["awaiting"].append((leaf_key, due))
            if parent not in excluded_signals:
                awaiting_items.append(
                    {
                        "signal": leaf_key,
                        "parent": parent,
                        "next_due": due.isoformat(),
                        "waiting_for": entry.get("due_reason", ""),
                        "days_to_due": (due - today_d).days,
                    }
                )
            continue
        if due and d and d < due <= today_d and parent not in excluded_signals:
            overdue_items.append(
                {
                    "signal": leaf_key,
                    "parent": parent,
                    "next_due": due.isoformat(),
                    "waiting_for": entry.get("due_reason", ""),
                    "days_overdue": (today_d - due).days,
                }
            )
        if d is None:
            # ★沒戳記就是沒戳記：不再 fallback 到 _last_updated
            collected[parent]["stamps"].append((leaf_key, None))
            if parent not in excluded_signals:
                unstamped_items.append(leaf_key)
        else:
            collected[parent]["stamps"].append((leaf_key, d))
    for parent, rows in (auto_stamps or {}).items():
        if parent not in collected:
            continue
        for row in rows:
            # 自動源也可以宣告 next_due：Micron 的毛利率序列停在上一份 10-Q 不是
            # 「抓取壞掉」，是下一份還沒發表。少了這個，s6a 會從財報隔天開始
            # 一路喊到下次開牌，把真正壞掉的抓取淹沒在裡面。
            label, d, due_raw, reason = (list(row) + [None, None, None])[:4]
            due = _parse_date(due_raw)
            collected[parent]["sources"].add("auto")
            collected[parent]["leaves"].append(label)
            if due and d and today_d < due and d <= due:
                collected[parent]["awaiting"].append((label, due))
                if parent not in excluded_signals:
                    awaiting_items.append(
                        {
                            "signal": label,
                            "parent": parent,
                            "next_due": due.isoformat(),
                            "waiting_for": reason or "",
                            "days_to_due": (due - today_d).days,
                        }
                    )
                continue
            if due and d and d < due <= today_d and parent not in excluded_signals:
                overdue_items.append(
                    {
                        "signal": label,
                        "parent": parent,
                        "next_due": due.isoformat(),
                        "waiting_for": reason or "",
                        "days_overdue": (today_d - due).days,
                    }
                )
            collected[parent]["stamps"].append((label, d))
            if d is None and parent not in excluded_signals:
                unstamped_items.append(label)

    buckets = {
        "fresh": 0.0,
        "stale": 0.0,
        "frozen": 0.0,
        "unstamped": 0.0,
        "awaiting": 0.0,
    }
    unstamped_signals, awaiting_signals = [], []
    for k, w in WEIGHTS.items():
        if k in excluded_signals:
            continue
        info = collected[k]
        src = "+".join(sorted(info["sources"])) or "?"
        dated = [(name, d) for name, d in info["stamps"] if d is not None]
        has_undated = any(d is None for _, d in info["stamps"])
        if not dated and info["awaiting"]:
            # 整支都在等外部事件（例如 s6 只剩財報要開）＝不是「沒更新」，是「還沒得更新」
            nxt = min(d for _, d in info["awaiting"])
            buckets["awaiting"] += w
            per_signal[k] = {
                "weight": w,
                "source": src,
                "as_of": None,
                "age_days": None,
                "bucket": "awaiting",
                "next_due": nxt.isoformat(),
                "items": info["leaves"],
            }
            awaiting_signals.append(k)
            continue
        if not dated:
            buckets["unstamped"] += w
            per_signal[k] = {
                "weight": w,
                "source": src,
                "as_of": None,
                "age_days": None,
                "bucket": "unstamped",
                "items": info["leaves"],
            }
            unstamped_signals.append(k)
            continue
        # 最舊成分決定整支訊號的新鮮度（保守）
        oldest_name, oldest = min(dated, key=lambda x: x[1])
        age = (today_d - oldest).days
        bucket = (
            "fresh"
            if age < STALE_WARN_DAYS
            else ("stale" if age < STALE_RED_DAYS else "frozen")
        )
        # ★有任一成分沒戳記，整支不得判 fresh：看不到的東西不能算新的
        if has_undated and bucket == "fresh":
            bucket = "stale"
        buckets[bucket] += w
        per_signal[k] = {
            "weight": w,
            "source": src,
            "as_of": oldest.isoformat(),
            "age_days": age,
            "bucket": bucket,
            "oldest_item": oldest_name,
            "items": info["leaves"],
        }
        for name, d in dated:
            a = (today_d - d).days
            if a >= STALE_WARN_DAYS:
                stale_items.append(
                    {
                        "signal": name,
                        "parent": k,
                        "updated": d.isoformat(),
                        "age_days": a,
                    }
                )

    eff_w = sum(w for k, w in WEIGHTS.items() if k not in excluded_signals)
    # ★可信度的分母是「現在就可以更新的權重」＝有效權重扣掉在等外部事件的部分。
    #   拿等財報的權重去扣自己的分數，等於因為 Micron 還沒開牌而說儀表板不可信，
    #   那是兩件事：一件是我沒去更新，一件是世界還沒產生新資料。
    actionable_w = round(eff_w - buckets["awaiting"], 3)
    fresh_share = round(buckets["fresh"] / eff_w, 3) if eff_w else None
    fresh_share_actionable = (
        round(buckets["fresh"] / actionable_w, 3) if actionable_w else None
    )
    basis = fresh_share_actionable
    if basis is None:
        level, caveat = "unknown", "無可更新的有效權重，分數不成立"
    elif overdue_items:
        # 過了宣告的到期日還沒補＝比一般過期更嚴重：那是「說好要看的東西沒去看」
        names = "、".join(
            f"{o['signal']}（逾期 {o['days_overdue']} 天）" for o in overdue_items
        )
        level, caveat = (
            "overdue",
            f"★已宣告到期卻未更新：{names}。這些項目的資料早該有了，分數不得視為最新。",
        )
    elif basis >= RELIABILITY_OK:
        level, caveat = "ok", ""
    elif basis >= RELIABILITY_DEGRADED:
        level, caveat = (
            "degraded",
            f"資料可信度降級：可更新的權重裡只有 {basis:.0%} 是 {STALE_WARN_DAYS} 天內的新資料，"
            "分數偏向歷史快照，可看方向但不宜當作進出依據。",
        )
    else:
        level, caveat = (
            "unreliable",
            f"★分數不可用於決策：可更新的權重裡真正新的只佔 {basis:.0%}，"
            "其餘是過期或僵化的手填值。補完 manual 訊號前，這個燈號不代表現在的市況。",
        )

    return {
        "as_of": today,
        "effective_weight": round(eff_w, 3),
        "fresh_weight": round(buckets["fresh"], 3),
        "stale_weight": round(buckets["stale"], 3),
        "frozen_weight": round(buckets["frozen"], 3),
        "unstamped_weight": round(buckets["unstamped"], 3),
        "awaiting_weight": round(buckets["awaiting"], 3),
        "actionable_weight": actionable_w,
        # ★這一格才是「這個分數有多少是真的新資訊」：分母用有效權重不是 1.0，
        #   否則被排除的訊號會被算成「不新鮮」，兩件事會混在一起。
        "fresh_share_of_effective": fresh_share,
        # 可信度判定用的是這一格（分母再扣掉在等外部事件的權重）
        "fresh_share_of_actionable": fresh_share_actionable,
        "reliability": level,
        "caveat": caveat,
        "unstamped_signals": unstamped_signals,
        "unstamped_items": sorted(set(unstamped_items)),
        "awaiting_signals": awaiting_signals,
        "awaiting_items": sorted(awaiting_items, key=lambda x: x["next_due"]),
        "overdue_items": sorted(overdue_items, key=lambda x: -x["days_overdue"]),
        "stale_items": sorted(stale_items, key=lambda x: -x["age_days"]),
        "by_signal": per_signal,
        "thresholds": {
            "warn_days": STALE_WARN_DAYS,
            "red_days": STALE_RED_DAYS,
            "reliability_ok": RELIABILITY_OK,
            "reliability_degraded": RELIABILITY_DEGRADED,
        },
    }


def score_to_status(score):
    """V3 zone interpretation."""
    if score <= 3:
        return "green", "Early Cycle — 基本面強勁，持有 / 可加碼"
    if score <= 6:
        return "green", "Mid Cycle — 多數訊號正面，持有，密切監控"
    if score <= 7:
        return "yellow", "Late Cycle — 訊號開始惡化，停止加碼，設移動停利"
    if score <= 8:
        return "yellow", "Late Cycle — 主動減 1/3 部位，剩餘設緊 trailing stop"
    if score <= 9:
        return "red", "Peak — 減半部位，8 週內分批降至 25%"
    return "red", "Peak — 出清主要部位，不在單日全部出清"


# ──────────────────────────────────────────────
# Alert generation (V3)
# ──────────────────────────────────────────────


def generate_alerts(signal_scores, signals_detail, spot_history):
    alerts = []

    # DDR5 spot below 5MA for 3 consecutive days
    key = "DDR5 16Gb (2Gx8) 4800/5600"
    spot_series = spot_history.get("series", {}).get(key, [])
    if len(spot_series) >= 8:
        prices = [e["price"] for e in spot_series]
        ma5_checks = []
        for i in range(-3, 0):
            window = prices[max(0, len(prices) + i - 5) : len(prices) + i + 1]
            if len(window) >= 5:
                ma5_checks.append((prices[i], mean(window)))
        if len(ma5_checks) == 3 and all(p < m for p, m in ma5_checks):
            alerts.append(
                {
                    "level": "yellow",
                    "msg": "Signal 1 Yellow：連續 3 天 DDR5 spot 跌破 5MA",
                }
            )

    # 1c、s8 的告警隨訊號於 2026-10-22 移除

    # Two or more top-level signals in Red zone
    red_signals = [k for k, v in signal_scores.items() if v is not None and v >= 8]
    if len(red_signals) >= 2:
        alerts.append(
            {
                "level": "red",
                "msg": f"Red Alert：{len(red_signals)} 個訊號進入紅燈區，強制 review 部位",
            }
        )

    # Cycle score climbing fast
    return alerts


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────


def main():
    today = date.today().isoformat()

    spot_history = load_json(DATA_DIR / "spot_history.json", {"series": {}})
    contract_real = load_json(DATA_DIR / "contract_real_history.json", {"series": {}})
    micron_gross = load_json(DATA_DIR / "micron_gross.json", {"entries": []})
    sec = load_json(DATA_DIR / "sec_fundamentals.json", {})
    manual = load_json(DATA_DIR / "manual_inputs.json", {})
    supply_expansion = load_json(DATA_DIR / "supply_expansion.json", {"items": []})
    # ★V4 起總分不讀 manual_inputs 的任何評分欄位（只讀 events）。
    #   若有人把已移除的欄位填回去，這裡大聲喊，不會被默默吃進分數。
    manual_leftovers = [leaf for leaf, _, _ in iter_manual_leaves(manual)]

    contract_ratio = build_contract_ratio(spot_history, contract_real, today)
    ratio_eval = evaluate_ratio_signals(contract_ratio)

    # ── Signal 1 (composite: 1a + 1b) ──
    s1_score, s1_sub = score_signal_1_composite(spot_history, ratio_eval)
    s1_detail = f"1a={s1_sub['1a']['score']} | 1b={s1_sub['1b']['score']}"

    # ── Signal 2（真合約價期別變動，自動）──
    s2_score, s2_detail, s2_info = score_signal_2_contract(contract_real, today)

    # ── Signal 3（比值水準）──
    # 2026-08-05 停用（合約來源與現貨同頁）→ 2026-10-22 接真合約價期別對齊比值，拆成水準（s3）。
    # ★不再回退到手填 5.0：那正是 8/05 修掉的「沒得量寫成量到中性」。
    s3e = ratio_eval["s3"]
    if RATIO_SCORING_ACTIVE:
        s3_score, s3_detail = s3e["score"], s3e["detail"]
    else:
        s3_score = None
        s3_detail = "開關關閉（11/10 決定是否開啟）｜若啟用：" + (
            f"{s3e['score']}｜{s3e['detail']}"
            if s3e["score"] is not None
            else s3e["detail"]
        )

    # ── Signal 4（4a capex＋4c RPO，SEC XBRL 自動）──
    s4a, d4a, info4a = score_signal_4a(sec)
    s4c, d4c, info4c = score_signal_4c(sec)
    s4_sub = {"4a": _sub_entry(s4a, d4a), "4c": _sub_entry(s4c, d4c)}
    s4_score = calc_signal_4_composite(s4_sub)

    # ── Signal 6（6a 毛利率＋6b 營收動能，自動）──
    s6_score, s6_sub, info6b = calc_signal_6_composite(micron_gross, sec)

    # ── Signal 7（Micron DIO，自動）──
    s7_score, s7_detail, info7 = score_signal_7(sec)

    signal_scores = {
        "s1": s1_score,
        "s2": s2_score,
        "s3": s3_score,
        "s4": s4_score,
        "s6": s6_score,
        "s7": s7_score,
    }

    cycle_score, excluded_signals = compute_cycle_score(signal_scores)
    contract_status = build_contract_status(ratio_eval, signal_scores, s1_sub)
    status_color, status_text = (
        score_to_status(cycle_score)
        if cycle_score is not None
        else ("grey", "無足夠訊號")
    )

    signals_detail = {
        "s1": {
            "score": s1_score,
            "label": "Daily 記憶體現貨報價",
            "detail": s1_detail,
            "sub": s1_sub,
        },
        "s2": {
            "score": s2_score,
            "label": "DRAM 合約價 3 個月變動（真合約價）",
            "detail": s2_detail,
            "data": s2_info,
        },
        "s3": {
            "score": s3_score,
            "label": "現貨÷合約 比值水準",
            "detail": s3_detail,
        },
        "s4": {
            "score": s4_score,
            "label": "Hyperscaler Demand Floor（capex＋RPO）",
            "sub": s4_sub,
            "data": {"4a": info4a, "4c": info4c},
        },
        "s6": {
            "score": s6_score,
            "label": "Micron 毛利率＋營收動能",
            "sub": s6_sub,
            "data": {"6b": info6b},
        },
        "s7": {
            "score": s7_score,
            "label": "Micron 存貨天數（DIO）",
            "detail": s7_detail,
            "data": info7,
        },
    }
    retired = [
        {"signal": k, "since": RETIRED_SINCE, "reason": v} for k, v in RETIRED.items()
    ]

    alerts = generate_alerts(signal_scores, signals_detail, spot_history)
    if manual_leftovers:
        alerts.append(
            {
                "level": "red",
                "msg": (
                    f"manual_inputs.json 出現評分欄位：{'/'.join(manual_leftovers)}。"
                    "V4 起手填訊號已全數移除或自動化，這些值沒有進總分；"
                    "要恢復手填得先改 calc_score，不是填回 JSON。"
                ),
            }
        )
    # SEC 抓取守門：分數是用哪天的資料算的，抓失敗時要看得到
    fetch = (sec or {}).get("fetch") or {}
    if not sec:
        alerts.append(
            {
                "level": "red",
                "msg": "找不到 sec_fundamentals.json：s4／s6b／s7 全部無資料、已排除。先跑 fetch_sec_fundamentals.py。",
            }
        )
    elif fetch.get("date") != today or fetch.get("failed"):
        failed = fetch.get("failed") or {}
        who = "、".join(
            f"{t}（沿用 {_sec_company(sec, t).get('fetched_at', '無')} 的抓取，"
            f"資料期末 {_sec_company(sec, t).get('latest_period_end', '無')}）"
            for t in (failed or _sec_company_list(sec))
        )
        alerts.append(
            {
                "level": "yellow",
                "msg": (
                    f"SEC 基本面今天沒抓成功（最後一次執行 {fetch.get('date', '無')}）：{who}。"
                    "s4／s6b／s7 用的是上一份資料，數字本身沒有過期但不是今天確認的。"
                ),
            }
        )

    # ── 手填訊號過期偵測（2026-07-31 新增；2026-09-02 改走 build_freshness 單一來源）──
    # 背景：9 個訊號有 5 個是 manual，內容曾停在 5/27 整整兩個月沒動，期間 Micron Q3、
    # hynix Q2、三星 Q2 全部開牌過，分數卻固定 3.2 綠燈 40 個交易日。儀表板不會自己
    # 喊「我很久沒被餵資料了」，看的人就會把僵化誤讀成穩定。這裡讓它自己承認。
    # 自動源的「這份資訊何時到手」：
    # ★2026-09-02 修：原本拿季末日（date）當新鮮度基準，害 FY26Q3 在 6/24 已經開牌、
    #   數字也已進表的情況下，還被判 96 天過期。季末到公告差約 4 週，且下一份財報未發表前
    #   本來就沒有新資料可抓——用 filed（SEC 收件日）才是「這份資訊何時到手」。
    def _last_series_date(hist):
        ds = [
            _parse_date(p.get("date"))
            for s in hist.get("series", {}).values()
            for p in s[-1:]
        ]
        ds = [d for d in ds if d]
        return max(ds) if ds else None

    micron_dates = [
        _parse_date(e.get("filed") or e.get("date"))
        for e in micron_gross.get("entries", [])
    ]
    micron_dates = [d for d in micron_dates if d]
    # ★V4：全部訊號都是自動源，新鮮度一律看「資料本身第一次出現的日子」，
    #   下一份資料的期限用外部事件日：SEC 申報的法定期限（10-Q 40 天／10-K 60 天）、
    #   合約價的「期末 + 75 天」（contract_period 對過期的定義）。在期限前＝等外部事件，
    #   過了期限還沒新資料＝overdue 紅燈。
    mu = _sec_company(sec, "MU")
    mu_due = mu.get("due")
    mu_reason = f"Micron 下一份 {mu.get('next_form', '季報')} 法定申報期限"

    def _sec_stamp(label, ticker, info_available=None):
        c = _sec_company(sec, ticker)
        return (
            label,
            _parse_date(info_available or c.get("latest_available")),
            c.get("due"),
            f"{ticker} 下一份 {c.get('next_form', '季報')} 法定申報期限",
        )

    contract_stamp = (
        _parse_date(s2_info.get("first_seen")),
        s2_info.get("next_due"),
        "下一期合約價（免費層每月月底放上個月 2H；期限＝最近一期期末 + 75 天）",
    )
    auto_stamps = {
        "s1": [("s1a(auto:spot)", _last_series_date(spot_history))],
        "s2": [("s2(auto:contract)",) + contract_stamp],
        "s4": [_sec_stamp(f"s4({t})", t) for t in HYPERSCALERS],
        "s6": [
            (
                "s6a(auto:micron)",
                max(micron_dates) if micron_dates else None,
                mu_due,
                mu_reason,
            ),
            _sec_stamp("s6b(auto:MU營收)", "MU", info6b.get("available")),
        ],
        "s7": [_sec_stamp("s7(auto:MU存貨)", "MU", info7.get("available"))],
    }
    if RATIO_SCORING_ACTIVE:
        auto_stamps["s1"].append(("s1b(auto:contract)",) + contract_stamp)
        auto_stamps["s3"] = [("s3(auto:contract)",) + contract_stamp]

    # 評分用不到 manual，新鮮度也不吃 manual（leftover 已另外告警）
    freshness = build_freshness({}, auto_stamps, today, excluded_signals)
    stale = freshness["stale_items"]

    if stale:
        worst = max(s["age_days"] for s in stale)
        lvl = "red" if worst >= STALE_RED_DAYS else "yellow"
        # 按父訊號聚合再列出：逐子項全列會變成 12 條的長字串，讀的人會直接略過。
        by_parent = {}
        for s in stale:
            cur = by_parent.setdefault(s["parent"], {"n": 0, "worst": 0})
            cur["n"] += 1
            cur["worst"] = max(cur["worst"], s["age_days"])
        names = ", ".join(
            f"{p}({v['worst']}天" + (f"／{v['n']} 個子項" if v["n"] > 1 else "") + ")"
            for p, v in sorted(by_parent.items(), key=lambda x: -x[1]["worst"])
        )
        alerts.append(
            {
                "level": lvl,
                "msg": f"訊號過期：{len(stale)} 個項目逾 {STALE_WARN_DAYS} 天未更新 → {names}（含自動源）。分數可能沒有反映最新事件。",
            }
        )

    if freshness["overdue_items"]:
        names = "、".join(
            f"{o['signal']}（{o['next_due']} 到期，已逾 {o['days_overdue']} 天"
            + (f"｜等的是：{o['waiting_for']}" if o["waiting_for"] else "")
            + "）"
            for o in freshness["overdue_items"]
        )
        alerts.append(
            {
                "level": "red",
                "msg": f"已到期未補：{names}。這是自己宣告過『那天會有資料』的項目，沒有寬限期。",
            }
        )

    if freshness["unstamped_items"]:
        items = "/".join(freshness["unstamped_items"])
        sig_note = (
            f"整支無戳記：{'/'.join(freshness['unstamped_signals'])}"
            f"（合計權重 {freshness['unstamped_weight']:.0%}）。"
            if freshness["unstamped_signals"]
            else ""
        )
        alerts.append(
            {
                "level": "yellow",
                "msg": f"無更新戳記：{items}——過期偵測看不到它們，一律不採信為新資料。{sig_note}",
            }
        )

    # ★2026-09-02 新增：守門要有效力，不能只有偵測。
    # 之前的狀態是「紅色過期告警天天出現，分數照樣輸出 3.32 綠燈、旁邊寫著可加碼」——
    # 告警與結論各說各話時，人只會看結論。這裡把可信度掛到結論本身（仍不動評分）。
    if freshness["caveat"]:
        alerts.append(
            {
                "level": "red" if freshness["reliability"] != "degraded" else "yellow",
                "msg": freshness["caveat"],
            }
        )
        status_text = f"【資料可信度：{freshness['reliability']}】{status_text}"

    # 停用中的訊號：不進告警（會天天吵），改成常駐狀態塊。
    # 「排除即遺忘」是上一版的另一個洞——s3 停用 33 天，待辦（找可分離現貨源／
    # 重分配 12% 權重）沒有任何地方會再提起它。
    # ★V4：停用中的（還在權重表裡、但這次沒分數）與已移除的（不在權重表）分開列。
    #   停用天數的起點寫死在程式：s3 自 2026-07-31（合約來源失效）起就沒進過總分。
    #   用 disabled_since 不用 updated：停用天數問的是「這支癱了多久」。
    DISABLED_SINCE = {"s3": "2026-07-31", "s1b": "2026-08-05"}
    ratio_todo = (
        "比值開關 RATIO_SCORING_ACTIVE 關著：11/10 決定是否開啟、門檻是否微調"
        "（trigger memory-dashboard-s3-recalibrate）。若啟用的分數見 contract_status.if_activated。"
    )
    disabled = []
    for k in excluded_signals:
        d = _parse_date(DISABLED_SINCE.get(k))
        disabled.append(
            {
                "signal": k,
                "level": "signal",
                "weight": WEIGHTS.get(k),
                "since": d.isoformat() if d else None,
                "days": (date.fromisoformat(today) - d).days if d else None,
                "todo": (
                    ratio_todo
                    if k == "s3"
                    else (signals_detail.get(k) or {}).get("detail", "本次無資料")
                ),
            }
        )
    # ★子項層：父訊號還在跑、但子項這次沒分數（例如 s1b 開關關著、4c 抓不到）。
    #   不在這裡列出來，它就從看板上完全消失了——那正是 9/02 修掉的「排除即遺忘」。
    SUB_WEIGHT_TABLES = {"s1": S1_WEIGHTS, "s4": S4_WEIGHTS, "s6": S6_WEIGHTS}
    for parent, table in SUB_WEIGHT_TABLES.items():
        if parent in excluded_signals:
            continue
        subs = (signals_detail.get(parent) or {}).get("sub") or {}
        for sk, sw in table.items():
            if (subs.get(sk) or {}).get("score") is not None:
                continue
            leaf = f"s{sk}"
            d = _parse_date(DISABLED_SINCE.get(leaf))
            disabled.append(
                {
                    "signal": leaf,
                    "level": "sub",
                    "parent": parent,
                    "weight": round(sw * WEIGHTS[parent], 4),
                    "since": d.isoformat() if d else None,
                    "days": (date.fromisoformat(today) - d).days if d else None,
                    "todo": (
                        ratio_todo
                        if leaf == "s1b"
                        else (subs.get(sk) or {}).get("detail", "本次無資料")
                    ),
                }
            )

    # ★複合訊號的「還有幾個子項在運作」：s1 停掉 1b 與 1c 之後只剩 1a 獨撐 15% 權重，
    #   分數看起來照常但資訊量只剩三分之一。不標出來，讀的人會以為它還是三腳架。
    for k, det in signals_detail.items():
        subs = det.get("sub")
        if not isinstance(subs, dict):
            continue
        keys = [x for x in subs if not x.startswith("_")]
        live = [
            x
            for x in keys
            if isinstance(subs[x], dict) and subs[x].get("score") is not None
        ]
        det["subs_active"], det["subs_total"] = len(live), len(keys)
        if keys and len(live) < len(keys):
            det["subs_note"] = f"{len(live)}/{len(keys)} 個子項在運作" + (
                f"（僅 {live[0]} 獨撐這支訊號的全部權重）" if len(live) == 1 else ""
            )

    ratio_watch = build_ratio_watch(spot_history, today)
    contract_watch = build_contract_watch(
        spot_history, contract_real, today, contract_ratio
    )
    # 真合約價過期守門：完整性檢查的下游版。fetch_contract 那邊喊的是「抓到什麼」，
    # 這裡喊的是「分數是否因此少了一條腿」，兩邊都要有，看板才看得到。
    fr = (contract_ratio or {}).get("freshness", "unavailable")
    fr_word = {"stale": "過期", "expired": "已失效", "unavailable": "不可用"}.get(fr)
    if fr_word:
        alerts.append(
            {
                "level": "red" if fr != "stale" else "yellow",
                "msg": (
                    f"真合約價{fr_word}："
                    + (
                        f"最近一期 {contract_ratio['period']}，距期末 {contract_ratio['data_age_days']} 天"
                        f"（免費層正常 ≤{DATA_AGE_WARN_DAYS} 天）。"
                        if contract_ratio
                        else "contract_real_history 無期別資料。"
                    )
                    + "s2 合約價動能與 s1b/s3 比值"
                    + ("仍計算但標過期。" if fr == "stale" else "不進任何計算。")
                ),
            }
        )
    if contract_watch and contract_watch["vintage_stalled"]:
        alerts.append(
            {
                "level": "yellow",
                "msg": (
                    f"合約價期別停滯：仍是 {contract_watch['vintage']}，"
                    f"已 {contract_watch['vintage_span_days']} 天未前進"
                    f"（免費層每月月底換一期，正常 ≤31 天；門檻 {VINTAGE_STALE_DAYS} 天）。"
                    "該來的月底更新沒來：s2 動能與比值的分母都停在舊期別。"
                ),
            }
        )

    signals_out = {
        "updated": datetime.now().isoformat(),
        "date": today,
        "methodology": METHODOLOGY,
        "weights": WEIGHTS,
        "sub_weights": {"s1": S1_WEIGHTS, "s4": S4_WEIGHTS, "s6": S6_WEIGHTS},
        "cycle_score": cycle_score,
        "status_color": status_color,
        "status_text": status_text,
        "alerts": alerts,
        "manual_last_updated": manual.get("_last_updated"),
        "stale_signals": stale,
        "excluded_signals": excluded_signals,
        "disabled_signals": disabled,
        "retired_signals": retired,
        "retired_note": (
            "V4（2026-10-22）移除只能靠人讀新聞判斷的訊號。被移除的多半是高分＝警訊的項目"
            "（V3 最後一天 s8 6.4、s5 5.5、s9 5.0），所以總分變低是少了資訊，不是週期變好。"
        ),
        "sec_fetch": (sec or {}).get("fetch"),
        "effective_weight": freshness["effective_weight"],
        "reliability": freshness["reliability"],
        "freshness": freshness,
        "events": manual.get("events", []),
        "contract_watch": contract_watch,
        "contract_ratio": contract_ratio,
        "contract_status": contract_status,
        "ratio_watch": ratio_watch,
        "supply_expansion": supply_expansion,
        "signals": signals_detail,
    }
    save_json(DATA_DIR / "signals.json", signals_out)

    # ── Update score history ──
    score_history = load_json(DATA_DIR / "score_history.json", {"entries": []})
    entries = score_history["entries"]
    if entries and entries[-1]["date"] == today:
        entries[-1].update(
            {"score": cycle_score, "color": status_color, "methodology": METHODOLOGY}
        )
    else:
        entries.append(
            {
                "date": today,
                "score": cycle_score,
                "color": status_color,
                "methodology": METHODOLOGY,
            }
        )
    score_history["entries"] = entries[-365:]
    # Mark V3/V4 start date for chart annotation（V4 起點前後不可直接比：訊號組成不同）
    score_history.setdefault("v3_start", today)
    score_history.setdefault("v4_start", today)
    save_json(DATA_DIR / "score_history.json", score_history)

    print(f"Cycle Score {METHODOLOGY}: {cycle_score} ({status_color})")
    print(f"  → {status_text}")
    shown = {
        k: (round(v, 1) if v is not None else "—") for k, v in signal_scores.items()
    }
    print(f"Signals: {shown}")
    if excluded_signals:
        live = len(WEIGHTS) - len(excluded_signals)
        kept_w = sum(w for k, w in WEIGHTS.items() if k not in excluded_signals)
        print(
            f"  [排除] {'/'.join(excluded_signals)} 無資料，未計入；"
            f"總分由其餘 {live} 個訊號重新正規化（原權重合計 {kept_w:.0%}）"
        )
    f = freshness
    print(
        f"  [新鮮度] 有效權重 {f['effective_weight']:.0%} 之中："
        f"新 {f['fresh_weight']:.0%}／過期 {f['stale_weight']:.0%}"
        f"／僵化 {f['frozen_weight']:.0%}／無戳記 {f['unstamped_weight']:.0%}"
        f"／等外部事件 {f['awaiting_weight']:.0%}"
        + (
            f"　→ 可更新的 {f['actionable_weight']:.0%} 裡，真正新的佔 {f['fresh_share_of_actionable']:.0%}"
            if f["fresh_share_of_actionable"] is not None
            else "　→ 無可更新權重"
        )
    )
    for a in f["awaiting_items"]:
        print(
            f"  [等資料] {a['signal']} → {a['next_due']}（還有 {a['days_to_due']} 天）"
            + (f"｜等的是：{a['waiting_for']}" if a["waiting_for"] else "")
        )
    print(
        f"  [可信度] {f['reliability']}" + (f" — {f['caveat']}" if f["caveat"] else "")
    )
    for k, v in sorted(
        f["by_signal"].items(), key=lambda x: -(x[1]["age_days"] or 9999)
    )[:4]:
        if v["bucket"] == "awaiting":
            age = f"等外部事件 → {v.get('next_due')}"
        elif v["age_days"] is None:
            age = "無戳記"
        else:
            age = (
                f"{v['age_days']}天前（{v['as_of']}，最舊＝{v.get('oldest_item', k)}）"
            )
        print(f"      {k} w={v['weight']:.0%} {v['source']:<11} {age}")
    for d in disabled:
        w = f" w={d['weight']:.1%}" if d.get("weight") else ""
        scope = "訊號" if d.get("level") == "signal" else f"子項於 {d.get('parent')}"
        print(
            f"  [停用中·{scope}] {d['signal']}{w}"
            + (f"，已 {d['days']} 天" if d["days"] is not None else "")
            + (f"｜待辦：{d['todo'][:60]}" if d["todo"] else "")
        )
    for k, det in signals_detail.items():
        if det.get("subs_note"):
            print(f"  [資訊量] {k}：{det['subs_note']}")
    if contract_watch:
        cw = contract_watch
        med = cw["period_change_median_pct"]
        cr = contract_ratio or {}
        print(
            f"  [真合約價·{contract_status['mode_text']}] 期別 {cw['vintage']}"
            + (f"（{cr['period_window']}）" if cr else "")
            + f"｜本站已顯示 {cw['vintage_span_days']} 天"
            + (f"｜距期末 {cr['data_age_days']} 天（{cr['freshness']}）" if cr else "")
            + (f"｜期別變動中位數 {med:+.2f}%" if med is not None else "｜期別變動 n/a")
        )
        for r in cw["die_ratios"]:
            al = r.get("aligned_ratio")
            print(
                f"      {r['pair']}：期別對齊 "
                + (
                    f"{r['aligned_spot_mean']} / {r['contract']} = {al:.3f}"
                    if al
                    else "n/a"
                )
                + f"｜即時 {r['spot']} / {r['contract']} = {r['ratio']:.3f}"
            )
        hist = [h for h in (cr.get("history") or []) if h["ratio"] is not None]
        if hist:
            print(
                f"      期別對齊歷史（DDR4 16Gb，{len(hist)} 期；現貨序列起點前的期別不列）："
                + "  ".join(f"{h['period_full']} {h['ratio']:.2f}" for h in hist)
            )
        ia = contract_status.get("if_activated")
        if ia:
            print(
                f"      [若啟用] s1b={ia['s1b']}（方向）、s3={ia['s3']}（水準），"
                f"S1 {s1_score}→{ia['s1']}，總分 {cycle_score}→{ia['cycle_score']}"
                + ("" if RATIO_SCORING_ACTIVE else "（開關關著，不進總分）")
            )
        sv = cw.get("spot_vs_contract") or {}
        if sv.get("spot_chg_20d_pct") is not None:
            print(
                f"      [s3 替代觀察] 現貨 20 日 {sv['spot_chg_20d_pct']:+.2f}%"
                f"　vs　合約期別 "
                + (
                    f"{sv['contract_period_chg_pct']:+.2f}%"
                    if sv.get("contract_period_chg_pct") is not None
                    else "n/a"
                )
                + "　→ "
                + ("★" if sv.get("diverging") or sv.get("spot_lagging") else "")
                + str(sv.get("state", ""))
            )

    if ratio_watch:
        print("  [DDR5/DDR4 比值觀測·不評分]")
        for r in ratio_watch["rows"]:
            print(
                f"      {r['label']}：{r['ratio']:.3f}"
                f"（近 {r['window_days']} 日 {r['window_min']:.3f}~{r['window_max']:.3f}，"
                f"總樣本 {r['n_total']} 日）"
            )
        t = ratio_watch.get("ddr4_trend")
        if t:
            print(
                f"      DDR4 16Gb 現價 {t['price']}，20 日 {t['chg_20d_pct']:+.2f}%（{t['direction']}）"
                "　←解除條件在等這條轉折"
            )

    sx = supply_expansion.get("items", [])
    if sx:
        print(f"  [供給側擴產觀測·不評分] {len(sx)} 筆")
        for it in sx:
            if it.get("first_output_est"):
                print(
                    f"      {it['company']}｜{it['item']}｜宣布 {it['date']}"
                    f"｜產出 {it['first_output_est']}"
                )
    if alerts:
        for a in alerts:
            print(f"  [{a['level'].upper()}] {a['msg']}")


if __name__ == "__main__":
    main()
