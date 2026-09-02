"""新鮮度守門的故障注入測試（2026-09-02）。

存在理由：這道守門在 2026-09-02 之前是「半殘」——會偵測、但偵測不到該偵測的東西，
偵測到了也不影響結論。修完之後如果沒有測試，下次改壞一樣沒人知道（記憶索引那邊
踩過一模一樣的坑：表頭門檻收緊了、稽核工具常數沒跟著改，於是 69 條超長被判「乾淨」）。

跑法：venv\\Scripts\\python.exe scripts\\test_freshness_gate.py
全綠才算守門還活著。任何一條紅的，先修再說，不要繞過。
"""

import sys
from pathlib import Path

if __name__ != "__main__":
    raise ImportError(
        "test_freshness_gate.py 是測試入口腳本，不可 import（會整支重跑）。"
    )

sys.path.insert(0, str(Path(__file__).parent))

from calc_score import (  # noqa: E402
    RELIABILITY_DEGRADED,
    RELIABILITY_OK,
    STALE_WARN_DAYS,
    build_freshness,
    iter_manual_leaves,
)

TODAY = "2026-09-02"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))


def base_manual(**over):
    """一份健康的樣本：全部今天更新、沒有 next_due。"""
    m = {
        "_last_updated": TODAY,
        "s1_sub": {"1c": {"score": 5.0, "updated": TODAY}},
        "s2": {"score": 4.0, "updated": TODAY},
        "s3": {"score": 5.0, "updated": TODAY},
        "s4": {k: {"score": 3.0, "updated": TODAY} for k in "abcdef"},
        "s5": {"score": 5.5, "updated": TODAY},
        "s6_sub": {"6b": {"score": 2.0, "updated": TODAY}},
        "s7": {"score": 3.0, "updated": TODAY},
        "s8": {"8a": {"score": 7.5, "updated": TODAY}},
        "s9": {"score": 5.5, "updated": TODAY},
        "events": [{"date": TODAY, "event": "不該被當成評分項"}],
    }
    m["s4"] = {f"4{k}": v for k, v in m["s4"].items()}
    m.update(over)
    return m


print("── 1. 葉節點展開：新增子項自動納管，events 不誤收 ──")
leaves = dict((k, p) for k, p, _ in iter_manual_leaves(base_manual()))
check("s2 被收為 s2/父 s2", leaves.get("s2") == "s2")
check("s1_sub.1c 被收為 s1c/父 s1", leaves.get("s1c") == "s1")
check("s4 六個子項全收", sum(1 for k in leaves if k.startswith("s4")) == 6)
check("events 不被當成評分項", "events" not in leaves)
check("底線開頭的 meta 欄不被收", not any(k.startswith("_") for k in leaves))

m = base_manual()
m["s8"]["8z"] = {"score": 9.0, "updated": TODAY}  # 模擬未來新增子項
leaves2 = dict((k, p) for k, p, _ in iter_manual_leaves(m))
check("未來新增的 8z 自動納管（不必改白名單）", leaves2.get("s8z") == "s8")

print("\n── 2. 無戳記不得繼承 _last_updated（舊版最大的洞）──")
m = base_manual()
del m["s8"]["8a"]["updated"]  # 整支 s8 只有這個子項
f = build_freshness(m, {}, TODAY, [])
check("無戳記子項被點名", "s8a" in f["unstamped_items"], f["unstamped_items"])
check("整支 s8 判 unstamped 不判 fresh", f["by_signal"]["s8"]["bucket"] == "unstamped")
check("unstamped 權重 = s8 的 7%", abs(f["unstamped_weight"] - 0.07) < 1e-9)

m = base_manual()
del m["s4"]["4c"]["updated"]  # 只有一個子項沒戳記，其餘是新的
f = build_freshness(m, {}, TODAY, [])
check(
    "部分子項無戳記 → 整支不得判 fresh",
    f["by_signal"]["s4"]["bucket"] != "fresh",
    f["by_signal"]["s4"]["bucket"],
)

print("\n── 3. 過期偵測與可信度降級 ──")
m = base_manual()
for k in ("s2", "s5", "s7", "s9"):
    m[k]["updated"] = "2026-06-01"  # 93 天前
f = build_freshness(m, {}, TODAY, [])
check("過期項目全數列出", len(f["stale_items"]) == 4, f["stale_items"])
check(
    "可信度降級（fresh 佔比掉到門檻下）",
    f["reliability"] in ("degraded", "unreliable"),
    f"{f['reliability']} @ {f['fresh_share_of_actionable']}",
)
check("降級時 caveat 非空（結論要跟著被標記）", bool(f["caveat"]))

f_ok = build_freshness(base_manual(), {}, TODAY, [])
check("全新資料時可信度 = ok", f_ok["reliability"] == "ok")
check("ok 時不掛 caveat", f_ok["caveat"] == "")

print("\n── 4. next_due：等外部事件不喊過期，但過期日一到就是紅燈 ──")
m = base_manual()
m["s6_sub"]["6b"] = {
    "score": 2.0,
    "updated": "2026-06-01",
    "next_due": "2026-10-01",
    "due_reason": "Micron FQ4",
}
f = build_freshness(m, {}, TODAY, [])
check(
    "等待中的項目不進過期清單", not any(s["signal"] == "s6b" for s in f["stale_items"])
)
check(
    "等待中的項目有被列出來（不是消失）",
    any(a["signal"] == "s6b" for a in f["awaiting_items"]),
)
check("等待中的權重從可更新分母扣掉", f["actionable_weight"] < f["effective_weight"])

m["s6_sub"]["6b"]["next_due"] = "2026-08-20"  # 已過期，且 updated 還停在到期前
f = build_freshness(m, {}, TODAY, [])
check(
    "過了 next_due 未補 → overdue",
    any(o["signal"] == "s6b" for o in f["overdue_items"]),
)
check("overdue 直接壓過可信度", f["reliability"] == "overdue", f["reliability"])
check("overdue 沒有 30 天寬限", f["overdue_items"][0]["days_overdue"] == 13)

m["s6_sub"]["6b"]["updated"] = "2026-08-25"  # 到期後有補
f = build_freshness(m, {}, TODAY, [])
check("到期後補了就不再算 overdue", not f["overdue_items"])

print("\n── 5. 停用訊號不參與過期，但也不該從輸出消失 ──")
f = build_freshness(base_manual(), {}, TODAY, ["s3"])
check("排除訊號不進 by_signal", "s3" not in f["by_signal"])
check("有效權重扣掉被排除的 12%", abs(f["effective_weight"] - 0.88) < 1e-9)
m = base_manual()
del m["s3"]["updated"]
f = build_freshness(m, {}, TODAY, ["s3"])
check("排除訊號的無戳記不製造噪音", "s3" not in f["unstamped_items"])

print("\n── 5b. 停用中的子項不參與新鮮度（2026-09-02 s1c 起適用）──")
m = base_manual()
m["s1_sub"]["1c"] = {
    "score": None,
    "scored": False,
    "disabled_since": "2026-08-05",
    "updated": "2026-06-01",  # 很舊，若沒排除會把 s1 拖成過期
}
f = build_freshness(
    m, {"s1": [("s1a(auto)", __import__("datetime").date(2026, 9, 2))]}, TODAY, []
)
check(
    "停用子項不拖累父訊號的新鮮度",
    f["by_signal"]["s1"]["bucket"] == "fresh",
    f["by_signal"]["s1"],
)
check("停用子項不進過期清單", not any(s["signal"] == "s1c" for s in f["stale_items"]))
m["s1_sub"]["1c"].pop("updated")
f = build_freshness(
    m, {"s1": [("s1a(auto)", __import__("datetime").date(2026, 9, 2))]}, TODAY, []
)
check("停用子項沒戳記也不算無戳記噪音", "s1c" not in f["unstamped_items"])

print("\n── 6. 自動源比照辦理 ──")
from datetime import date  # noqa: E402

f = build_freshness(
    base_manual(), {"s6": [("s6a(auto)", date(2026, 6, 25))]}, TODAY, []
)
check("自動源過期會叫", any(s["signal"] == "s6a(auto)" for s in f["stale_items"]))
f = build_freshness(
    base_manual(),
    {"s6": [("s6a(auto)", date(2026, 6, 25), "2026-10-01", "Micron FQ4")]},
    TODAY,
    [],
)
check(
    "自動源也能宣告 next_due",
    any(a["signal"] == "s6a(auto)" for a in f["awaiting_items"]),
)
check("自動源的等待原因有帶出來", f["awaiting_items"][0]["waiting_for"] == "Micron FQ4")
f = build_freshness(base_manual(), {"s6": [("s6a(auto)", None)]}, TODAY, [])
check("自動源抓不到資料 = 無戳記，不靜默", "s6a(auto)" in f["unstamped_items"])

print("\n── 7. 門檻常數存在且方向正確 ──")
check("STALE_WARN_DAYS 為正", STALE_WARN_DAYS > 0)
check("OK 門檻高於 DEGRADED 門檻", RELIABILITY_OK > RELIABILITY_DEGRADED)

print(f"\n{'=' * 46}")
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    print("失敗項目：")
    for n in FAIL:
        print(f"  - {n}")
    sys.exit(1)
print("守門完整，全綠。")
