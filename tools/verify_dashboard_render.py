"""開真的瀏覽器渲染儀表板，確認關鍵讀數有出現在畫面上（不是只存在 JSON 裡）。

存在理由：2026-09-02 發現 freshness 從 8/17 起就在算，但前端從來沒有渲染它——
資料算對了、看板上看不到，等於沒做。這支腳本擋的就是這種「後端有、前端無」。

跑法：venv\\Scripts\\python.exe tools\\verify_dashboard_render.py
會在 docs/ 起一個臨時 http server、截圖存到 tools/_render_check.png。
"""

import json
import socket
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    sig = json.loads((DOCS / "data" / "signals.json").read_text(encoding="utf-8"))
    port = free_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(DOCS))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    from playwright.sync_api import sync_playwright

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1600})
        page.on("pageerror", lambda e: errors.append(f"JS error: {e}"))
        page.on(
            "console",
            lambda m: (
                errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error"
                else None
            ),
        )
        page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="networkidle")
        page.wait_for_selector("#app", state="visible", timeout=15000)
        body = page.inner_text("body")
        page.screenshot(path=str(ROOT / "tools" / "_render_check.png"), full_page=True)
        browser.close()
    httpd.shutdown()

    checks = []

    def want(name, cond, hint=""):
        checks.append((name, cond, hint))

    score_pct = f"{sig['cycle_score'] * 10:.1f}%"
    want("分數有顯示", score_pct in body, score_pct)
    want("狀態文字有顯示", sig["status_text"][:10] in body)

    f = sig.get("freshness", {})
    rel_labels = {
        "ok": "資料新鮮",
        "degraded": "可信度降級",
        "unreliable": "分數不可用於決策",
        "overdue": "已到期未補",
    }
    want(
        "可信度標籤有顯示（分數旁邊看得到資料多新）",
        rel_labels.get(f.get("reliability"), "###") in body,
        f.get("reliability"),
    )
    if f.get("caveat"):
        want("降級說明有顯示", f["caveat"][:16] in body)
    if f.get("awaiting_items"):
        want("等外部事件的項目有顯示", f["awaiting_items"][0]["signal"] in body)
    for d in sig.get("disabled_signals", []):
        want(f"停用中的 {d['signal']} 有顯示（不是靜靜消失）", "停用中" in body)
    for k, v in (sig.get("signals") or {}).items():
        if v.get("subs_note"):
            want(
                f"{k} 的子項運作比例有顯示（少了子項要看得出來）",
                v["subs_note"][:12] in body,
            )

    # 觀測層：不評分不代表不用看見。這三塊都是 2026-09-02 新增的，
    # 全部只存在 JSON 而不渲染的話，等於又回到「算了但看不到」。
    sv = (sig.get("contract_watch") or {}).get("spot_vs_contract") or {}
    if sv.get("spot_chg_20d_pct") is not None:
        want("s3 替代觀察有顯示（現貨 vs 合約並排）", "s3 替代觀察" in body)
        want("替代觀察的狀態有顯示", (sv.get("state") or "###")[:6] in body)
    rw = sig.get("ratio_watch") or {}
    if rw.get("rows"):
        want("DDR5/DDR4 比值觀測有顯示", f"{rw['rows'][0]['ratio']:.3f}" in body)
        want("比值觀測的解除條件有顯示", rw["release_condition"][:12] in body)
    sx = (sig.get("supply_expansion") or {}).get("items") or []
    if sx:
        want("供給側擴產有顯示", "供給側擴產" in body)
        want(
            "擴產的實際產出時間有顯示（不是只有宣布金額）",
            sx[0]["first_output_est"][:6] in body,
        )

    for a in sig.get("alerts", []):
        want(f"告警有顯示：{a['msg'][:14]}…", a["msg"][:14] in body)
    want("沒有 JS 錯誤", not errors, "; ".join(errors[:3]))

    print(f"渲染驗證 — {DOCS / 'index.html'}")
    bad = 0
    for name, cond, hint in checks:
        print(
            f"  [{'PASS' if cond else 'FAIL'}] {name}"
            + (f" — {hint}" if not cond and hint else "")
        )
        bad += 0 if cond else 1
    print(f"\n截圖：{ROOT / 'tools' / '_render_check.png'}")
    print(f"PASS {len(checks) - bad} / FAIL {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
