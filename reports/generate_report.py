"""
Memory Cycle Dashboard — Report Generator
Usage:
    python reports/generate_report.py
    python reports/generate_report.py --output C:/path/to/custom_report

Outputs:
    docs/reports/memory_cycle_report_YYYY-MM-DD.html  (always)
    docs/reports/memory_cycle_report_YYYY-MM-DD.pdf   (if weasyprint available)
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "docs" / "reports"

ZONE_LABELS = {
    (0, 3):   ("Early Cycle", "#22c55e"),
    (4, 6):   ("Mid Cycle",   "#4ade80"),
    (7, 8):   ("Late Cycle",  "#f59e0b"),
    (9, 10):  ("Peak",        "#ef4444"),
}

SIGNAL_LABELS = {
    "s1": "Daily 記憶體現貨報價",
    "s2": "DRAM/NAND 月合約價 QoQ",
    "s3": "Spot ÷ Contract Ratio",
    "s4": "Hyperscaler Demand Floor",
    "s5": "Samsung HBM4 良率進度",
    "s6": "Micron 財務指標",
    "s7": "Samsung/SK Hynix 庫存週數",
    "s8": "中國對手擴產進度",
    "s9": "Cycle Ending 時間軸校準",
}

WEIGHTS = {
    "s1": 15, "s2": 15, "s3": 12, "s4": 20,
    "s5": 10, "s6": 10, "s7":  8, "s8":  7, "s9": 3,
}

SUB_LABELS = {
    "s4": {"4a":"Capex Revision","4b":"Cloud 營收成長","4c":"Backlog vs Capex",
           "4d":"Capex 股價反應","4e":"2027 Guidance","4f":"NVDA Supply Commitments"},
    "s6": {"6a":"GM 軌跡（Auto）","6b":"Q3 FY26 財報 Outcome","6c":"HBM Revenue"},
    "s8": {"8a":"CXMT IPO 進度","8b":"CXMT 客戶擴大","8c":"YMTC IPO 進度",
           "8d":"中國 HBM 進度","8e":"月產能 Ramp"},
}


def load(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else (default or {})


def get_zone(score):
    for (lo, hi), (label, color) in ZONE_LABELS.items():
        if lo <= score <= hi:
            return label, color
    return "Unknown", "#94a3b8"


def score_color(s):
    if s <= 6:  return "#22c55e"
    if s <= 8:  return "#f59e0b"
    return "#ef4444"


def status_dot(s):
    c = score_color(s)
    return f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{c};margin-right:6px"></span>'


def signal_row(key, v):
    sc = v.get("score", 5.0)
    label = v.get("label", SIGNAL_LABELS.get(key, key))
    detail = v.get("detail", "")
    wt = WEIGHTS.get(key, 0)
    bar_pct = min(100, int(sc / 10 * 100))
    return f"""
    <tr>
      <td style="width:30%;padding:8px 6px;border-bottom:1px solid #2a2d3e">
        {status_dot(sc)}<strong>{label}</strong>
        <span style="font-size:0.75rem;color:#94a3b8;margin-left:4px">({wt}%)</span>
      </td>
      <td style="padding:8px 6px;border-bottom:1px solid #2a2d3e;width:10%;font-weight:700;color:{score_color(sc)}">{sc:.1f}</td>
      <td style="padding:8px 6px;border-bottom:1px solid #2a2d3e">
        <div style="height:4px;background:#2a2d3e;border-radius:2px">
          <div style="height:4px;width:{bar_pct}%;background:{score_color(sc)};border-radius:2px"></div>
        </div>
        <div style="font-size:0.78rem;color:#94a3b8;margin-top:3px">{detail}</div>
      </td>
    </tr>"""


def sub_table(sig_key, sub_dict):
    if not sub_dict:
        return ""
    labels = SUB_LABELS.get(sig_key, {})
    rows = ""
    for k, v in sub_dict.items():
        sc = v.get("score", 5.0)
        st = v.get("status", "green" if sc < 5 else "yellow" if sc < 7 else "red")
        note = v.get("note", v.get("detail", ""))
        lbl = labels.get(k, k)
        rows += f"""
        <tr>
          <td style="padding:6px 8px;border-bottom:1px solid #2a2d3e;font-size:0.82rem">{lbl}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #2a2d3e;font-size:0.82rem;color:{score_color(sc)};font-weight:700">{sc:.1f}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #2a2d3e;font-size:0.78rem;color:#94a3b8">{note}</td>
        </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:8px">
      <thead><tr style="color:#94a3b8;font-size:0.75rem">
        <td style="padding:4px 8px;width:28%">Sub-metric</td>
        <td style="padding:4px 8px;width:10%">分數</td>
        <td style="padding:4px 8px">備註</td>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def event_rows(events, today_str):
    if not events:
        return "<p style='color:#94a3b8;font-size:0.85rem'>無排定事件</p>"
    html = ""
    for ev in events:
        days = (date.fromisoformat(ev["date"]) - date.fromisoformat(today_str)).days
        days_text = f"{abs(days)}天前" if days < 0 else ("今天" if days == 0 else f"{days}天後")
        lock = ev.get("lock_before_h", 24)
        is_lock = 0 <= days <= lock / 24 + 1
        lock_note = f"&nbsp;<strong style='color:#f59e0b'>🔒 鎖倉期</strong>" if is_lock else ""
        html += f"""
        <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #2a2d3e;align-items:flex-start">
          <div style="background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);color:#6366f1;
                      border-radius:6px;padding:4px 8px;font-size:0.75rem;font-weight:600;
                      min-width:90px;text-align:center;white-space:nowrap">
            {ev["date"][5:]}<br>{days_text}
          </div>
          <div>
            <div style="font-size:0.88rem;font-weight:500">{ev["event"]}{lock_note}</div>
            <div style="font-size:0.76rem;color:#94a3b8;margin-top:2px">{ev.get("note","")}</div>
          </div>
        </div>"""
    return html


def recent_trend(score_entries, n=7):
    if len(score_entries) < 2:
        return "資料不足"
    recent = score_entries[-n:]
    first, last = recent[0]["score"], recent[-1]["score"]
    delta = last - first
    direction = "↑ 上升" if delta > 0.2 else "↓ 下降" if delta < -0.2 else "→ 持平"
    return f"近 {len(recent)} 日：{first:.1f} → {last:.1f}（{direction} {delta:+.2f}）"


def build_html(signals, score_history, today_str):
    cycle_score = signals.get("cycle_score", 5.0)
    zone_label, zone_color = get_zone(int(cycle_score))
    status_text = signals.get("status_text", "")
    updated = signals.get("updated", today_str)
    alerts = signals.get("alerts", [])
    events = signals.get("events", [])
    signal_dict = signals.get("signals", {})
    trend = recent_trend(score_history.get("entries", []))

    alert_html = ""
    for a in alerts:
        bg = "rgba(245,158,11,0.1)" if a["level"] == "yellow" else "rgba(239,68,68,0.1)"
        bd = "rgba(245,158,11,0.3)" if a["level"] == "yellow" else "rgba(239,68,68,0.3)"
        fc = "#f59e0b" if a["level"] == "yellow" else "#ef4444"
        alert_html += f'<div style="background:{bg};border:1px solid {bd};color:{fc};padding:8px 12px;border-radius:6px;margin-bottom:6px;font-size:0.85rem">⚠ {a["msg"]}</div>'

    signal_rows_html = "".join(signal_row(k, v) for k, v in signal_dict.items())

    sub_sections = ""
    for key in ["s4", "s6", "s8"]:
        if key in signal_dict and "sub" in signal_dict[key]:
            sub_sections += f"""
            <div style="margin-top:20px">
              <h3 style="font-size:0.85rem;font-weight:600;color:#94a3b8;text-transform:uppercase;
                         letter-spacing:0.05em;margin-bottom:4px">{SIGNAL_LABELS[key]} — 子訊號拆解</h3>
              {sub_table(key, signal_dict[key]["sub"])}
            </div>"""

    decision = ""
    if cycle_score <= 3:
        decision = "目前在 <strong>Early Cycle</strong>。完全綠燈，可持有/加碼。重大事件前 24 小時鎖倉。"
    elif cycle_score <= 6:
        decision = "目前在 <strong>Mid Cycle</strong>。持有為主，不主動減碼。密切監控 Signal 8（中國擴產）與 Signal 6b（Micron 財報）。重大事件前 24 小時鎖倉。"
    elif cycle_score <= 7:
        decision = "進入 <strong>Late Cycle</strong>。停止加碼，設移動停利（最高點 -10%）。"
    elif cycle_score <= 8:
        decision = "進入 <strong>Late Cycle 後段</strong>。主動減 1/3 部位，剩餘設緊 trailing stop（最高點 -7%）。"
    else:
        decision = "進入 <strong>Peak Zone</strong>。分批出清，8 週內逐步降至 25% 部位，不在單日全部出清。"

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Memory Cycle Report — {today_str}</title>
<style>
  body {{ font-family: "Microsoft JhengHei", -apple-system, sans-serif; background:#0f1117; color:#e2e8f0; padding:32px; max-width:860px; margin:0 auto; line-height:1.6; }}
  .card {{ background:#1a1d27; border:1px solid #2a2d3e; border-radius:10px; padding:20px; margin-bottom:20px; }}
  h1 {{ font-size:1.4rem; color:#e2e8f0; margin:0 0 4px; }}
  h2 {{ font-size:1rem; font-weight:600; color:#94a3b8; text-transform:uppercase; letter-spacing:0.05em; margin:0 0 12px; }}
  h3 {{ font-size:0.85rem; }}
  table {{ width:100%; border-collapse:collapse; }}
</style>
</head>
<body>

<h1>Memory Cycle Dashboard — 分析報告</h1>
<p style="color:#94a3b8;font-size:0.82rem;margin-bottom:24px">
  報告日期：{today_str}　｜　資料更新：{updated[:10]}　｜　評分方法：V3
</p>

{alert_html if alert_html else ""}

<div class="card">
  <h2>執行摘要</h2>
  <div style="display:flex;align-items:flex-end;gap:20px;flex-wrap:wrap">
    <div>
      <div style="font-size:3.5rem;font-weight:800;color:{zone_color};line-height:1">{cycle_score:.1f}</div>
      <div style="color:#94a3b8;font-size:0.85rem">/ 10</div>
    </div>
    <div>
      <div style="background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);
                  color:{zone_color};border-radius:20px;padding:4px 14px;font-size:0.85rem;
                  font-weight:600;display:inline-block">{zone_label}</div>
      <div style="margin-top:8px;font-size:0.9rem">{status_text}</div>
    </div>
  </div>
  <div style="margin-top:16px;padding:12px 14px;background:rgba(99,102,241,0.08);
              border:1px solid rgba(99,102,241,0.2);border-radius:8px;font-size:0.85rem">
    <strong>近期趨勢</strong>：{trend}
  </div>
  <div style="margin-top:12px;padding:12px 14px;background:rgba(34,197,94,0.06);
              border:1px solid rgba(34,197,94,0.2);border-radius:8px;font-size:0.85rem">
    <strong>部位建議</strong>：{decision}
  </div>
</div>

<div class="card">
  <h2>9 個訊號當前狀態</h2>
  <table><tbody>{signal_rows_html}</tbody></table>
</div>

<div class="card">
  <h2>關鍵子訊號拆解</h2>
  {sub_sections}
</div>

<div class="card">
  <h2>重大事件日曆</h2>
  {event_rows(events, today_str)}
</div>

<div class="card">
  <h2>分數區間對照</h2>
  <table>
    <tr>
      <td style="padding:6px 8px;color:#22c55e;font-weight:700">0 – 3</td>
      <td style="padding:6px 8px;color:#22c55e">Early Cycle</td>
      <td style="padding:6px 8px;color:#94a3b8;font-size:0.82rem">基本面強勁，多數訊號仍在上行，可持有或加碼</td>
    </tr>
    <tr>
      <td style="padding:6px 8px;color:#4ade80;font-weight:700">4 – 6</td>
      <td style="padding:6px 8px;color:#4ade80">Mid Cycle</td>
      <td style="padding:6px 8px;color:#94a3b8;font-size:0.82rem">部分訊號放緩，持有為主，密切監控觸發點</td>
    </tr>
    <tr>
      <td style="padding:6px 8px;color:#f59e0b;font-weight:700">7 – 8</td>
      <td style="padding:6px 8px;color:#f59e0b">Late Cycle</td>
      <td style="padding:6px 8px;color:#94a3b8;font-size:0.82rem">訊號明顯惡化，停止加碼，設停利，準備出脫</td>
    </tr>
    <tr>
      <td style="padding:6px 8px;color:#ef4444;font-weight:700">9 – 10</td>
      <td style="padding:6px 8px;color:#ef4444">Peak</td>
      <td style="padding:6px 8px;color:#94a3b8;font-size:0.82rem">週期高點確立，8 週內逐步降至 25% 部位</td>
    </tr>
  </table>
</div>

<p style="color:#94a3b8;font-size:0.75rem;text-align:center;margin-top:24px">
  Memory Cycle Dashboard V3 — 自動產生報告 {today_str}
</p>

</body>
</html>"""


def main():
    today_str = date.today().isoformat()

    # Parse optional --output argument
    out_stem = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--output" and i < len(sys.argv):
            out_stem = sys.argv[i + 1]
            break

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    signals = load(DATA_DIR / "signals.json")
    score_history = load(DATA_DIR / "score_history.json", {"entries": []})

    if not signals:
        print("ERROR: signals.json not found. Run calc_score.py first.", file=sys.stderr)
        sys.exit(1)

    html_content = build_html(signals, score_history, today_str)

    # HTML output
    if out_stem:
        html_path = Path(out_stem).with_suffix(".html")
    else:
        html_path = REPORT_DIR / f"memory_cycle_report_{today_str}.html"

    html_path.write_text(html_content, encoding="utf-8")
    print(f"HTML 報告：{html_path}")

    # PDF output via Playwright (already in project venv)
    pdf_path = html_path.with_suffix(".pdf")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html_content, wait_until="domcontentloaded")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "20mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
            )
            browser.close()
        print(f"PDF 報告：{pdf_path}")
    except Exception as e:
        print(f"PDF 產生失敗：{e}")


if __name__ == "__main__":
    main()
