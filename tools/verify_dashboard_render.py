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
