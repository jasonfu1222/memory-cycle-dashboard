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
"""

import json
from datetime import date, datetime
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


def score_signal_1b(spot_history, contract_history):
    """DDR5 spot vs contract ratio.
    spot > contract = demand tight = low score (bullish/early).
    spot < contract = oversupply = high score (warning).

    2026-08-05 停用：TrendForce 的 dram_spot 與 dram_contract 已回傳同一份頁面，
    兩檔歷史 56 個重疊日期價格完全相同，比值恆為 1.00。這不是弱訊號，是沒有量測。
    回傳 None 讓上層排除並重新正規化權重，不要填中性值假裝測過。
    找到能分離現貨與合約的來源後再解除。
    """
    if contract_history.get("data_integrity", {}).get("duplicate_of_spot"):
        return None, "來源已合併：contract 頁與 spot 同源，比值恆為 1.00，訊號停用"

    spot_key = "DDR5 16Gb (2Gx8) 4800/5600"
    spot_series = spot_history.get("series", {}).get(spot_key, [])
    if not spot_series:
        return None, "no spot data"

    spot_price = spot_series[-1]["price"]

    contract_series = contract_history.get("series", {})
    ddr5_c_key = next((k for k in contract_series if "DDR5" in k and "16Gb" in k), None)
    if not ddr5_c_key or not contract_series[ddr5_c_key]:
        return None, "no contract data"

    contract_price = contract_series[ddr5_c_key][-1]["price"]
    if contract_price <= 0:
        return None, "invalid contract price"

    ratio = spot_price / contract_price

    if ratio >= 1.10:
        score, status = 2.0, "green"
    elif ratio >= 1.05:
        score, status = 2.5, "green"
    elif ratio >= 1.00:
        score, status = 3.0, "green"
    elif ratio >= 0.95:
        score, status = 5.5, "yellow"  # V3 yellow trigger: spot < contract × 0.95
    elif ratio >= 0.90:
        score, status = 7.5, "yellow"
    else:
        score, status = 9.0, "red"  # V3 red trigger: spot < contract × 0.90

    return (
        score,
        f"spot/contract = {ratio:.2f} (${spot_price:.1f}/${contract_price:.1f}) [{status}]",
    )


def score_signal_1c(spot_history, manual_override=None):
    """DDR5/DDR4 price ratio divergence.
    Narrowing ratio (DDR5 losing premium) = softening = higher score.
    Manual override takes precedence for qualitative Yellow judgment.
    """
    if manual_override is not None:
        return manual_override["score"], manual_override.get("note", "manual")

    series = spot_history.get("series", {})
    ddr5_key = "DDR5 16Gb (2Gx8) 4800/5600"
    ddr4_key = "DDR4 16Gb (2Gx8) 3200"

    if ddr5_key not in series or ddr4_key not in series:
        return None, "no data"

    ddr5_series = series[ddr5_key]
    ddr4_series = series[ddr4_key]

    if not ddr5_series or not ddr4_series:
        return None, "no data"

    ddr5_price = ddr5_series[-1]["price"]
    ddr4_price = ddr4_series[-1]["price"]

    if ddr4_price <= 0:
        return None, "invalid DDR4 price"

    ratio = ddr5_price / ddr4_price

    # 2026-08-05：回填 297 天正確均價後發現，這條階梯的「健康區 1.8~2.5x」在整段
    # 歷史從未成立——DDR5 16Gb ÷ DDR4 16Gb 實際落在 0.448~0.713，DDR4 一直比 DDR5 貴。
    # 也就是說沒有手填值蓋著時，自動路徑會每天固定吐出 8.5 紅燈（憑空的訊號）。
    # 階梯八成是照 DDR5 16Gb ÷ DDR4 **8Gb**（實測 1.09~1.98）校準的，但程式比的是 16Gb。
    # 在 Jason 裁定要比哪一對之前，寧可承認沒量到，不要報一個假紅燈。
    if ratio < 1.0:
        return None, (
            f"階梯未校準：實測比值 {ratio:.2f}x 遠低於校準區間（1.5~2.5x），"
            "DDR4 16Gb 長期貴於 DDR5 16Gb。待確認應比對哪一組品項後才恢復自動計分"
        )

    # Healthy zone: 1.8-2.5x. Below = DDR5 losing premium = warning.
    if ratio > 2.5:
        score = 2.5  # DDR5 strongly outperforming, very healthy
    elif ratio > 2.0:
        score = 4.5  # healthy range; DDR4 softening ongoing = slight yellow
    elif ratio > 1.8:
        score = 5.5  # approaching yellow threshold
    elif ratio > 1.5:
        score = 7.0  # yellow: divergence narrowing fast
    else:
        score = 8.5  # red: DDR5 premium collapsing

    return (
        round(score, 1),
        f"DDR5/DDR4 = {ratio:.2f}x (${ddr5_price:.1f} / ${ddr4_price:.1f})",
    )


S1_WEIGHTS = {"1a": 0.50, "1b": 0.30, "1c": 0.20}


def score_signal_1_composite(spot_history, contract_history, manual_1c=None):
    """S1 = 0.50 × 1a + 0.30 × 1b + 0.20 × 1c

    2026-08-05 改：缺項不再填中性值，改為排除後重新正規化（與 s4/s8 同慣例）。
    原本 s1a 無資料時填 5.0、s1b 無資料時抄 s1a，等於把「沒量到」報成「量到中性」，
    在序列重建的暖機期會直接偽造一個訊號。
    """
    subs = {
        "1a": score_signal_1a(spot_history),
        "1b": score_signal_1b(spot_history, contract_history),
        "1c": score_signal_1c(spot_history, manual_1c),
    }

    total, w_sum = 0.0, 0.0
    for key, w in S1_WEIGHTS.items():
        score = subs[key][0]
        if score is not None:
            total += score * w
            w_sum += w

    detail = {
        "1a": {"score": subs["1a"][0], "detail": subs["1a"][1]},
        "1b": {"score": subs["1b"][0], "detail": subs["1b"][1]},
        "1c": {
            "score": subs["1c"][0],
            "detail": subs["1c"][1],
            "status": (
                "unavailable"
                if subs["1c"][0] is None
                else (
                    "green"
                    if subs["1c"][0] < 5
                    else "yellow" if subs["1c"][0] < 7 else "red"
                )
            ),
        },
    }
    if w_sum == 0:
        detail["_note"] = "1a/1b/1c 全部無資料，S1 不計入總分"
        return None, detail

    excluded = [k for k in S1_WEIGHTS if subs[k][0] is None]
    if excluded:
        detail["_note"] = f"已排除 {'/'.join(excluded)}，權重在其餘子項間重新正規化"
    return round(total / w_sum, 1), detail


# ──────────────────────────────────────────────
# Signal 2: Monthly contract QoQ
# ──────────────────────────────────────────────


def score_signal_2_auto(contract_history):
    """Auto-computed contract QoQ. High QoQ (bullish) = low score.
    Note: auto data is daily snapshot; manual assessment preferred for V3.
    """
    series = contract_history.get("series", {})
    ddr5_key = next((k for k in series if "DDR5 16Gb" in k), None)
    if not ddr5_key or len(series[ddr5_key]) < 4:
        return None, "insufficient data"

    entries = series[ddr5_key]
    current = entries[-1]["price"]

    try:
        from datetime import timedelta

        current_dt = date.fromisoformat(entries[-1]["date"])
        target = current_dt - timedelta(days=90)
        past_entry = next(
            (
                e
                for e in reversed(entries[:-1])
                if date.fromisoformat(e["date"]) <= target
            ),
            entries[0],
        )
    except (ValueError, IndexError):
        return None, "date parse error"

    past = past_entry["price"]
    qoq = (current - past) / past * 100

    # V3: high QoQ = bullish = LOW score
    if qoq > 40:
        base = 2.0
    elif qoq > 20:
        base = 2.5
    elif qoq > 10:
        base = 3.5
    elif qoq > 0:
        base = 4.5
    elif qoq > -5:
        base = 5.5  # flat = neutral-yellow
    elif qoq > -15:
        base = 7.0  # declining = yellow
    else:
        base = 8.5  # sharply declining = red

    return round(base, 1), f"[auto] QoQ {qoq:+.1f}% | DDR5 contract ${current}"


# ──────────────────────────────────────────────
# Signal 4: Hyperscaler composite (V3: 6 sub-metrics)
# ──────────────────────────────────────────────

S4_WEIGHTS = {
    "4a": 0.25,  # capex revision direction
    "4b": 0.18,  # cloud revenue growth
    "4c": 0.18,  # backlog vs capex
    "4d": 0.12,  # capex announcement stock reaction
    "4e": 0.12,  # 2027 capex guidance
    "4f": 0.15,  # NVDA supply commitments (NEW V3)
}


def calc_signal_4_composite(s4_sub):
    total, w_sum = 0.0, 0.0
    for k, w in S4_WEIGHTS.items():
        if k in s4_sub and s4_sub[k].get("score") is not None:
            total += s4_sub[k]["score"] * w
            w_sum += w
    if w_sum == 0:
        return 5.0
    return round(total / w_sum, 1)


# ──────────────────────────────────────────────
# Signal 6: Micron composite (V3: 3 sub-metrics)
# ──────────────────────────────────────────────

S6_WEIGHTS = {
    "6a": 0.50,  # GM trajectory (auto)
    "6b": 0.30,  # quarterly earnings outcome (manual/event card)
    "6c": 0.20,  # HBM revenue (manual)
}


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


def calc_signal_6_composite(micron_gross, s6_manual_sub):
    """S6 = 0.50 × 6a + 0.30 × 6b + 0.20 × 6c"""
    s6a, d6a = score_signal_6a(micron_gross)
    if s6a is None:
        s6a = 5.0
        d6a = "no data"

    s6b_entry = s6_manual_sub.get("6b", {})
    s6b = s6b_entry.get("score", 5.0)
    d6b = s6b_entry.get("note", "pending")

    s6c_entry = s6_manual_sub.get("6c", {})
    s6c = s6c_entry.get("score", 5.0)
    d6c = s6c_entry.get("note", "")

    composite = round(
        S6_WEIGHTS["6a"] * s6a + S6_WEIGHTS["6b"] * s6b + S6_WEIGHTS["6c"] * s6c, 1
    )
    return composite, {
        "6a": {
            "score": s6a,
            "detail": d6a,
            "status": "green" if s6a < 5 else "yellow" if s6a < 7 else "red",
        },
        "6b": {
            "score": s6b,
            "detail": d6b,
            "status": s6b_entry.get(
                "status", "green" if s6b < 5 else "yellow" if s6b < 7 else "red"
            ),
        },
        "6c": {
            "score": s6c,
            "detail": d6c,
            "status": s6c_entry.get(
                "status", "green" if s6c < 5 else "yellow" if s6c < 7 else "red"
            ),
        },
    }


# ──────────────────────────────────────────────
# Signal 8: China competitor expansion (all manual)
# ──────────────────────────────────────────────

S8_WEIGHTS = {
    "8a": 0.30,  # CXMT IPO progress
    "8b": 0.25,  # CXMT customer expansion
    "8c": 0.20,  # YMTC IPO progress
    "8d": 0.15,  # China HBM progress
    "8e": 0.10,  # CXMT/YMTC monthly capacity ramp
}


def calc_signal_8_composite(s8_sub):
    total, w_sum = 0.0, 0.0
    for k, w in S8_WEIGHTS.items():
        if k in s8_sub and s8_sub[k].get("score") is not None:
            total += s8_sub[k]["score"] * w
            w_sum += w
    if w_sum == 0:
        return 5.0
    return round(total / w_sum, 1)


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
    for k, w in WEIGHTS_V3.items():
        score = signal_scores.get(k)
        if score is None:
            excluded.append(k)
            continue
        total += score * w
        w_sum += w
    if w_sum == 0:
        return None, excluded
    return round(total / w_sum, 2), excluded


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

    # Signal 1c warning
    s1_sub = signals_detail.get("s1", {}).get("sub", {})
    if (s1_sub.get("1c", {}).get("score") or 0) >= 7:
        alerts.append(
            {
                "level": "yellow",
                "msg": "Signal 1c Yellow：DDR5/DDR4 比值跌破 1.8x，DDR5 溢價收窄",
            }
        )

    # Signal 8 yellow
    if (signal_scores.get("s8") or 5) >= 6:
        alerts.append(
            {
                "level": "yellow",
                "msg": "Signal 8 Yellow：中國對手擴產進度出現多個觀察點（CXMT/YMTC IPO）",
            }
        )

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
    contract_history = load_json(DATA_DIR / "contract_history.json", {"series": {}})
    micron_gross = load_json(DATA_DIR / "micron_gross.json", {"entries": []})
    manual = load_json(DATA_DIR / "manual_inputs.json", {})

    # ── Signal 1 (composite: 1a + 1b + 1c) ──
    manual_1c = manual.get("s1_sub", {}).get("1c")
    s1_score, s1_sub = score_signal_1_composite(
        spot_history, contract_history, manual_1c
    )
    s1_detail = f"1a={s1_sub['1a']['score']} | 1b={s1_sub['1b']['score']} | 1c={s1_sub['1c']['score']}"

    # ── Signal 2 (manual preferred; auto fallback) ──
    if manual.get("s2", {}).get("score") is not None:
        s2_score = manual["s2"]["score"]
        s2_detail = f"[manual] {manual['s2']['note']}"
    else:
        s2_score, s2_detail = score_signal_2_auto(contract_history)
        if s2_score is None:
            s2_score = 5.0
            s2_detail = "no data"

    # ── Signal 3 (manual) ──
    # 2026-08-05 停用：s3 量的就是 spot÷contract，而兩個來源頁面已合併，
    # 手填一個 5.0 只是把「沒得量」寫成「量到中性」。改為排除並重新正規化。
    s3 = manual.get("s3", {})
    if contract_history.get("data_integrity", {}).get("duplicate_of_spot"):
        s3_score = None
        s3_detail = "來源已合併：contract 頁與 spot 同源，無法計算比值，訊號停用"
    else:
        s3_score = s3.get("score", 5.0)
        s3_detail = f"[manual] {s3.get('note', '')}"

    # ── Signal 4 (composite: 4a–4f) ──
    s4_sub = manual.get("s4", {})
    s4_score = calc_signal_4_composite(s4_sub)

    # ── Signal 5 (manual) ──
    s5 = manual.get("s5", {})
    s5_score = s5.get("score", 5.0)
    s5_detail = f"[manual] {s5.get('note', '')}"

    # ── Signal 6 (composite: 6a auto + 6b/6c manual) ──
    s6_manual_sub = manual.get("s6_sub", {})
    s6_score, s6_sub = calc_signal_6_composite(micron_gross, s6_manual_sub)

    # ── Signal 7 (manual) ──
    s7 = manual.get("s7", {})
    s7_score = s7.get("score", 5.0)
    s7_detail = f"[manual] {s7.get('note', '')}"

    # ── Signal 8 (composite: 8a–8e, all manual) ──
    s8_sub = manual.get("s8", {})
    s8_score = calc_signal_8_composite(s8_sub)

    # ── Signal 9 (meta-signal, manual) ──
    s9 = manual.get("s9", {})
    s9_score = s9.get("score", 5.0)
    s9_detail = f"[manual] {s9.get('note', '')}"

    signal_scores = {
        "s1": s1_score,
        "s2": s2_score,
        "s3": s3_score,
        "s4": s4_score,
        "s5": s5_score,
        "s6": s6_score,
        "s7": s7_score,
        "s8": s8_score,
        "s9": s9_score,
    }

    cycle_score, excluded_signals = compute_cycle_score(signal_scores)
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
            "label": "DRAM/NAND 月合約價 QoQ",
            "detail": s2_detail,
        },
        "s3": {
            "score": s3_score,
            "label": "Spot ÷ Contract Ratio",
            "detail": s3_detail,
        },
        "s4": {"score": s4_score, "label": "Hyperscaler Demand Floor", "sub": s4_sub},
        "s5": {
            "score": s5_score,
            "label": "Samsung HBM4 良率進度",
            "detail": s5_detail,
        },
        "s6": {
            "score": s6_score,
            "label": "Micron 毛利率 + 財報 Trajectory",
            "sub": s6_sub,
        },
        "s7": {
            "score": s7_score,
            "label": "Samsung/SK Hynix 庫存週數",
            "detail": s7_detail,
        },
        "s8": {"score": s8_score, "label": "中國對手擴產進度", "sub": s8_sub},
        "s9": {
            "score": s9_score,
            "label": "Cycle Ending 時間軸校準",
            "detail": s9_detail,
        },
    }

    alerts = generate_alerts(signal_scores, signals_detail, spot_history)

    # ── 手填訊號過期偵測（2026-07-31 新增）──────────────────
    # 背景：9 個訊號有 5 個是 manual，內容曾停在 5/27 整整兩個月沒動，期間 Micron Q3、
    # hynix Q2、三星 Q2 全部開牌過，分數卻固定 3.2 綠燈 40 個交易日。儀表板不會自己
    # 喊「我很久沒被餵資料了」，看的人就會把僵化誤讀成穩定。這裡讓它自己承認。
    STALE_WARN_DAYS, STALE_RED_DAYS = 30, 60
    stale = []
    for sig_key, entry in (
        ("s1c", manual.get("s1_sub", {}).get("1c", {})),
        ("s2", manual.get("s2", {})),
        ("s3", manual.get("s3", {})),
        ("s5", manual.get("s5", {})),
        ("s6b", manual.get("s6_sub", {}).get("6b", {})),
        ("s7", manual.get("s7", {})),
        ("s8a", manual.get("s8", {}).get("8a", {})),
        ("s9", manual.get("s9", {})),
    ):
        stamp = entry.get("updated") or manual.get("_last_updated")
        if not stamp:
            continue
        try:
            age = (date.fromisoformat(today) - date.fromisoformat(stamp)).days
        except ValueError:
            continue
        if age >= STALE_WARN_DAYS:
            stale.append({"signal": sig_key, "updated": stamp, "age_days": age})

    if stale:
        worst = max(s["age_days"] for s in stale)
        lvl = "red" if worst >= STALE_RED_DAYS else "yellow"
        names = ", ".join(
            f"{s['signal']}({s['age_days']}天)"
            for s in sorted(stale, key=lambda x: -x["age_days"])
        )
        alerts.append(
            {
                "level": lvl,
                "msg": f"手填訊號過期：{len(stale)} 個逾 {STALE_WARN_DAYS} 天未更新 → {names}。分數可能沒有反映最新事件。",
            }
        )

    signals_out = {
        "updated": datetime.now().isoformat(),
        "date": today,
        "methodology": "V3",
        "cycle_score": cycle_score,
        "status_color": status_color,
        "status_text": status_text,
        "alerts": alerts,
        "manual_last_updated": manual.get("_last_updated"),
        "stale_signals": stale,
        "excluded_signals": excluded_signals,
        "effective_weight": round(
            sum(w for k, w in WEIGHTS_V3.items() if k not in excluded_signals), 3
        ),
        "events": manual.get("events", []),
        "signals": signals_detail,
    }
    save_json(DATA_DIR / "signals.json", signals_out)

    # ── Update score history ──
    score_history = load_json(DATA_DIR / "score_history.json", {"entries": []})
    entries = score_history["entries"]
    if entries and entries[-1]["date"] == today:
        entries[-1].update(
            {"score": cycle_score, "color": status_color, "methodology": "V3"}
        )
    else:
        entries.append(
            {
                "date": today,
                "score": cycle_score,
                "color": status_color,
                "methodology": "V3",
            }
        )
    score_history["entries"] = entries[-365:]
    # Mark V3 start date for chart annotation
    score_history.setdefault("v3_start", today)
    save_json(DATA_DIR / "score_history.json", score_history)

    print(f"Cycle Score V3: {cycle_score} ({status_color})")
    print(f"  → {status_text}")
    shown = {
        k: (round(v, 1) if v is not None else "—") for k, v in signal_scores.items()
    }
    print(f"Signals: {shown}")
    if excluded_signals:
        live = len(WEIGHTS_V3) - len(excluded_signals)
        kept_w = sum(w for k, w in WEIGHTS_V3.items() if k not in excluded_signals)
        print(
            f"  [排除] {'/'.join(excluded_signals)} 無資料，未計入；"
            f"總分由其餘 {live} 個訊號重新正規化（原權重合計 {kept_w:.0%}）"
        )
    if alerts:
        for a in alerts:
            print(f"  [{a['level'].upper()}] {a['msg']}")


if __name__ == "__main__":
    main()
