"""
計算所有 Signal 分數並輸出 signals.json + score_history.json
Phase 1: Signal 1 (Daily Spot) + Signal 4a (Hyperscaler Capex) 自動計算
其餘 Signal 從 manual_inputs.json 讀取（人工填入）
"""
import json
from datetime import date, datetime
from pathlib import Path
from statistics import mean

DATA_DIR = Path(__file__).parent.parent / "data"

def load_json(path, default):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def calc_ma(prices, window):
    if len(prices) < window:
        return None
    return mean(prices[-window:])

def score_signal_1(history):
    """Daily spot price signal (0-10)"""
    series = history.get("series", {})
    key = "DDR5 16Gb (2Gx8) 4800/5600"
    if key not in series or len(series[key]) < 5:
        return 5.0, "insufficient data"

    prices = [e["price"] for e in series[key]]
    current = prices[-1]
    ma5 = calc_ma(prices, 5)
    ma20 = calc_ma(prices, 20)

    score = 5.0
    detail = []

    if ma5:
        if current > ma5:
            score += 1.0
            detail.append("price > 5MA ↑")
        else:
            score -= 1.0
            detail.append("price < 5MA ↓")

    if ma20:
        if current > ma20:
            score += 1.0
            detail.append("price > 20MA ↑")
        else:
            score -= 1.0
            detail.append("price < 20MA ↓")

    if ma5 and ma20:
        if ma5 > ma20:
            score += 1.0
            detail.append("5MA > 20MA (bullish cross)")
        else:
            score -= 1.0
            detail.append("5MA < 20MA (bearish cross)")

    if len(prices) >= 2:
        chg = (prices[-1] - prices[-2]) / prices[-2] * 100
        if chg > 0.5:
            score += 0.5
            detail.append(f"daily +{chg:.1f}%")
        elif chg < -0.5:
            score -= 0.5
            detail.append(f"daily {chg:.1f}%")

    score = max(0.0, min(10.0, score))
    return round(score, 1), " | ".join(detail)

def calc_signal_4_composite(s4):
    """Signal 4 composite from sub-metrics (0-10 each, weighted)"""
    weights = {"4a": 0.30, "4b": 0.20, "4c": 0.20, "4d": 0.15, "4e": 0.15}
    total, w_sum = 0.0, 0.0
    for k, w in weights.items():
        if k in s4 and s4[k]["score"] is not None:
            total += s4[k]["score"] * w
            w_sum += w
    if w_sum == 0:
        return 5.0
    return round(total / w_sum, 1)

def compute_cycle_score(signals):
    weights = {
        "s1": 0.15, "s2": 0.15, "s3": 0.15,
        "s4": 0.25, "s5": 0.10, "s6": 0.10, "s7": 0.10
    }
    total = sum(signals.get(k, 5.0) * w for k, w in weights.items())
    return round(total, 2)

def score_to_status(score):
    if score < 4:    return "green",  "Early Cycle — Hold / 可加碼"
    if score < 7:    return "green",  "Mid Cycle — Hold"
    if score < 8:    return "yellow", "Late Cycle — 停止加碼"
    if score < 9:    return "yellow", "Late Cycle — 設移動停利、減 1/3 部位"
    if score < 10:   return "red",    "Peak — 減半部位"
    return "red", "Peak — 出清主要部位"

def main():
    today = date.today().isoformat()
    spot_history = load_json(DATA_DIR / "spot_history.json", {"series": {}})
    manual = load_json(DATA_DIR / "manual_inputs.json", {
        "s2": {"score": 5.0, "note": "未填入"},
        "s3": {"score": 5.0, "note": "未填入"},
        "s4": {
            "4a": {"score": 8.0, "status": "green", "note": "全部上修"},
            "4b": {"score": 8.0, "status": "green", "note": "Google +63%, AWS +28%, Azure +40%"},
            "4c": {"score": 8.0, "status": "green", "note": "Backlog > Capex"},
            "4d": {"score": 5.0, "status": "yellow", "note": "Meta -6%, MSFT -2.5%"},
            "4e": {"score": 8.0, "status": "green", "note": "Alphabet 2027 顯著增加"},
        },
        "s5": {"score": 5.0, "note": "未填入"},
        "s6": {"score": 5.0, "note": "未填入"},
        "s7": {"score": 5.0, "note": "未填入"},
    })

    s1_score, s1_detail = score_signal_1(spot_history)
    s4_composite = calc_signal_4_composite(manual["s4"])

    signal_scores = {
        "s1": s1_score,
        "s2": manual["s2"]["score"],
        "s3": manual["s3"]["score"],
        "s4": s4_composite,
        "s5": manual["s5"]["score"],
        "s6": manual["s6"]["score"],
        "s7": manual["s7"]["score"],
    }

    cycle_score = compute_cycle_score(signal_scores)
    status_color, status_text = score_to_status(cycle_score)

    # Check alerts
    alerts = []
    spot_series = spot_history.get("series", {}).get("DDR5 16Gb (2Gx8) 4800/5600", [])
    if len(spot_series) >= 3:
        recent = [e["price"] for e in spot_series[-3:]]
        ma5_vals = []
        for i in range(3):
            idx = -(3 - i)
            window = [e["price"] for e in spot_series[max(0, len(spot_series)+idx-5):len(spot_series)+idx+1]]
            if len(window) >= 5:
                ma5_vals.append((recent[i], mean(window)))
        if len(ma5_vals) == 3 and all(p < m for p, m in ma5_vals):
            alerts.append({"level": "yellow", "msg": "連續 3 天 DDR5 spot 跌破 5MA"})

    signals_out = {
        "updated": datetime.now().isoformat(),
        "date": today,
        "cycle_score": cycle_score,
        "status_color": status_color,
        "status_text": status_text,
        "alerts": alerts,
        "signals": {
            "s1": {"score": s1_score, "label": "Daily Spot Price", "detail": s1_detail},
            "s2": {"score": manual["s2"]["score"], "label": "月合約價 QoQ", "detail": manual["s2"]["note"]},
            "s3": {"score": manual["s3"]["score"], "label": "Spot/Contract Ratio", "detail": manual["s3"]["note"]},
            "s4": {
                "score": s4_composite, "label": "Hyperscaler Demand Floor",
                "sub": manual["s4"]
            },
            "s5": {"score": manual["s5"]["score"], "label": "Samsung HBM4 良率", "detail": manual["s5"]["note"]},
            "s6": {"score": manual["s6"]["score"], "label": "Micron 毛利率", "detail": manual["s6"]["note"]},
            "s7": {"score": manual["s7"]["score"], "label": "庫存週數", "detail": manual["s7"]["note"]},
        }
    }
    save_json(DATA_DIR / "signals.json", signals_out)

    # Update score history
    score_history = load_json(DATA_DIR / "score_history.json", {"entries": []})
    entries = score_history["entries"]
    if entries and entries[-1]["date"] == today:
        entries[-1]["score"] = cycle_score
        entries[-1]["color"] = status_color
    else:
        entries.append({"date": today, "score": cycle_score, "color": status_color})
    score_history["entries"] = entries[-365:]
    save_json(DATA_DIR / "score_history.json", score_history)

    print(f"Cycle Score: {cycle_score} ({status_color}) — {status_text}")
    print(f"Signals: {signal_scores}")
    if alerts:
        print(f"ALERTS: {alerts}")

if __name__ == "__main__":
    main()
