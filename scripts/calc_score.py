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


# ──────────────────────────────────────────────
# 真合約價觀測（不評分）
# ──────────────────────────────────────────────
# 2026-08-19：真合約表自 8/10 起獨立累積。它現在還不能餵 s1b/s3（理由見下方
# score_signal_1b 的三條），但「不能評分」不等於「不用看」——華邦電／SNXX 的論點
# 失效線寫的是「4Q26 合約價轉負＝價格水準見頂確認」，那條線在此之前根本沒有自動來源，
# 只能靠手填的 s2 每隔一個月更新一次。這裡把可觀測的事實原樣攤開，不轉成分數：
#   ①期別與停滯天數 ②官方自報的期別變動% ③同口徑 DDR4 顆粒的 spot/contract 比值
# 比值序列同時是未來重新校準 s1b 門檻的原料，從今天開始累積。
DIE_PAIRS = [
    ("DDR4 16Gb (2Gx8) 3200", "DDR4 16Gb 2Gx8"),
    ("DDR4 8Gb (1Gx8) 3200", "DDR4 8Gb 1Gx8"),
]
VINTAGE_STALE_DAYS = (
    45  # ★與 fetch_contract.VINTAGE_STALE_DAYS 是同一條線，改一邊要改兩邊
)


def build_contract_watch(spot_history, contract_real, today):
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
    ratios = []
    for spot_key, c_key in DIE_PAIRS:
        sp = spot_series.get(spot_key, [])
        cp = series.get(c_key, [])
        if not sp or not cp or not cp[-1].get("price"):
            continue
        ratios.append(
            {
                "pair": f"{spot_key} ÷ {c_key}",
                "spot": sp[-1]["price"],
                "contract": cp[-1]["price"],
                "ratio": round(sp[-1]["price"] / cp[-1]["price"], 3),
                "spot_date": sp[-1].get("date"),
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
            "觀測不評分。期別價非日價，同期別內每日相同；期別變動%為 TrendForce 自報。"
            "die_ratios 為同口徑顆粒比值，累積 ≥60 個交易日後才具備重新校準 s1b 門檻的樣本。"
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
            "樣本需跨越一次 DDR4 價格轉折（由漲轉跌或由跌轉漲）才具備重新校準門檻的條件；"
            "只累積天數不算——現有歷史全落在 DDR4 停產稀缺的同一種狀態。"
        ),
    }


def score_signal_1b(spot_history, contract_history):
    """DDR5 spot vs contract ratio.
    spot > contract = demand tight = low score (bullish/early).
    spot < contract = oversupply = high score (warning).

    2026-08-05 停用：TrendForce 的 dram_spot 與 dram_contract 已回傳同一份頁面，
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
    """
    if contract_history.get("data_integrity", {}).get("duplicate_of_spot"):
        return (
            None,
            "停用：真合約表無 DDR5 顆粒、DDR4 比值 2.13 出門檻表、期別半月不動與 s1a 共線",
        )

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
        # ★2026-09-02 Jason 裁決：手填值為 null＝觀測不評分（與 s1b/s3 同一種處理）。
        #   回 None 讓 S1 複合排除它並重新正規化，不要用一個沒有資訊的 5.0 佔著權重。
        if manual_override.get("score") is None:
            return None, (
                "觀測不評分：DDR4 因停產減量而長期貴於 DDR5，分母被供給端人為決策主導，"
                "此比值現在量到的是 DDR4 退場速度而非 DDR5 的週期位置。"
                "序列改由 ratio_watch 累積，樣本跨越一次 DDR4 價格轉折後再定門檻。"
            )
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

    ★2026-08-19 加閘門：contract_history.json 自 8/05 起裝的其實是現貨模組價
    （dram_contract 與 dram_spot 同頁）。手填 s2 一旦被清空就會掉進這個 auto，
    把現貨 QoQ 當合約 QoQ 報出來——分數照樣是綠的，沒有人會發現。
    來源不對就不算，讓 s2 走「no data」而不是走一個錯的數字。
    """
    if contract_history.get("data_integrity", {}).get("duplicate_of_spot"):
        return None, "來源無效：contract 檔實為現貨，不以現貨代算合約 QoQ"
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
        for k in WEIGHTS_V3
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
    for k, w in WEIGHTS_V3.items():
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

    eff_w = sum(w for k, w in WEIGHTS_V3.items() if k not in excluded_signals)
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
    contract_real = load_json(DATA_DIR / "contract_real_history.json", {"series": {}})
    micron_gross = load_json(DATA_DIR / "micron_gross.json", {"entries": []})
    manual = load_json(DATA_DIR / "manual_inputs.json", {})
    supply_expansion = load_json(DATA_DIR / "supply_expansion.json", {"items": []})

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
        s3_detail = (
            "停用：真合約表已在累積但配對不成立（無 DDR5 顆粒／DDR4 比值 2.13 出門檻表／"
            "期別半月不動與 s1a 共線）。改以 contract_watch 觀測不評分，理由詳 score_signal_1b"
        )
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
    # s6a 的下一份資料與 6b 是同一場財報，直接沿用它宣告的 next_due，
    # 免得兩邊各寫一個日期然後分岔（這支檔案的老毛病）。
    micron_due = manual.get("s6_sub", {}).get("6b", {}).get("next_due")
    auto_stamps = {
        "s1": [("s1a(auto:spot)", _last_series_date(spot_history))],
        "s6": [
            (
                "s6a(auto:micron)",
                max(micron_dates) if micron_dates else None,
                micron_due,
                "Micron FQ4 FY26 財報（與 6b 同一場，毛利率序列要等新的 10-Q/10-K）",
            )
        ],
    }
    if manual.get("s2", {}).get("score") is None:
        auto_stamps["s2"] = [("s2(auto:contract)", _last_series_date(contract_history))]

    freshness = build_freshness(manual, auto_stamps, today, excluded_signals)
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
    disabled = []
    for k in excluded_signals:
        entry = manual.get(k, {}) if isinstance(manual.get(k), dict) else {}
        # ★用 disabled_since 不用 updated：停用天數問的是「這支癱了多久」，
        #   而 updated 會因為我今天去補了一句 note 就歸零，把積欠洗掉。
        d = _parse_date(entry.get("disabled_since")) or _parse_date(
            entry.get("updated")
        )
        disabled.append(
            {
                "signal": k,
                "level": "signal",
                "weight": WEIGHTS_V3.get(k),
                "since": d.isoformat() if d else None,
                "days": (date.fromisoformat(today) - d).days if d else None,
                "todo": entry.get("todo")
                or (entry.get("note", "").split("待辦：")[-1] if entry else ""),
            }
        )
    # ★子項層的停用（如 2026-09-02 起的 s1c）：父訊號還在跑，但這個子項已經不評分。
    #   不在這裡列出來，它就從看板上完全消失了——那正是剛修掉的「排除即遺忘」。
    SUB_WEIGHT_TABLES = {
        "s1": S1_WEIGHTS,
        "s4": S4_WEIGHTS,
        "s6": S6_WEIGHTS,
        "s8": S8_WEIGHTS,
    }
    for leaf_key, parent, entry in iter_manual_leaves(manual):
        if parent in excluded_signals or entry.get("score") is not None:
            continue
        d = _parse_date(entry.get("disabled_since")) or _parse_date(
            entry.get("updated")
        )
        sub_w = SUB_WEIGHT_TABLES.get(parent, {}).get(leaf_key[1:])
        disabled.append(
            {
                "signal": leaf_key,
                "level": "sub",
                "parent": parent,
                "weight": (
                    round(sub_w * WEIGHTS_V3[parent], 4)
                    if sub_w and parent in WEIGHTS_V3
                    else None
                ),
                "since": d.isoformat() if d else None,
                "days": (date.fromisoformat(today) - d).days if d else None,
                "todo": entry.get("todo", ""),
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
    contract_watch = build_contract_watch(spot_history, contract_real, today)
    if contract_watch and contract_watch["vintage_stalled"]:
        alerts.append(
            {
                "level": "yellow",
                "msg": (
                    f"合約價期別停滯：仍是 {contract_watch['vintage']}，"
                    f"已 {contract_watch['vintage_span_days']} 天未前進"
                    f"（半月報價正常最多約 16 天）。"
                    "以合約價為分母的任何比值，變動將全部來自現貨端。"
                ),
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
        "disabled_signals": disabled,
        "effective_weight": freshness["effective_weight"],
        "reliability": freshness["reliability"],
        "freshness": freshness,
        "events": manual.get("events", []),
        "contract_watch": contract_watch,
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
        print(
            f"  [合約價觀測·不評分] 期別 {cw['vintage']}（已 {cw['vintage_span_days']} 天）"
            + (f"｜期別變動中位數 {med:+.2f}%" if med is not None else "｜期別變動 n/a")
        )
        for r in cw["die_ratios"]:
            print(
                f"      {r['pair']}：{r['spot']} / {r['contract']} = {r['ratio']:.2f}"
                f"（門檻表 0.90~1.10 之外，故不評分）"
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
