# -*- coding: utf-8 -*-
"""把 High 口徑的舊序列歸檔，並清空成均價口徑重新累積。

2026-08-05 Jason 裁決：歸檔不刪除、score_history 一併重置。

為什麼歸檔而不是刪除：那 61 筆是「過去做判斷時螢幕上顯示什麼」的唯一紀錄。
Decision OS 在做決策校準時，需要知道當時看到的是什麼，即使那是錯的。
歸檔檔案不被任何計分程式讀取，只供事後稽核。

只跑一次；重複執行會偵測到已歸檔並中止，不會覆蓋歸檔內容。
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
STAMP = "20260805_high_deprecated"

TARGETS = {
    "spot_history.json": "現貨序列（price 欄實為 Daily/Weekly High，非代表性報價）",
    "contract_history.json": "合約序列（實為現貨同一份頁面，比值恆為 1.00）",
    "score_history.json": "週期分數（以上述兩者算出，且含 6/04–7/30 卡在 3.2 的僵化期）",
}

REASON = {
    "archived_at": datetime.now().isoformat(),
    "reason": (
        "price 欄取的是 TrendForce 表格的 High 欄而非 Session Average；"
        "實測 High/均價比值當日介於 1.29~1.76 不固定，且 High 推導的漲跌幅與官方 "
        "Session Change 四項全部對不上（含憑空產生與視而不見兩種方向），"
        "偏差不會在 MA 交叉／MoM 等相對量裡抵消。"
        "contract 檔另因來源頁面合併，與現貨完全同值。"
    ),
    "successor": "同名檔案自 2026-08-05 起改記 Session Average，序列重新累積",
    "do_not_use_for": "任何計分、回測或趨勢判讀",
    "may_use_for": "決策校準的事後稽核（回答『當時螢幕上顯示什麼』）",
}


def main():
    archive_dir = DATA / "_archive"
    archive_dir.mkdir(exist_ok=True)

    moved = []
    for name, desc in TARGETS.items():
        src = DATA / name
        dst = archive_dir / f"{src.stem}_{STAMP}.json"
        if dst.exists():
            print(f"[中止] 歸檔已存在，不覆蓋：{dst.name}", file=sys.stderr)
            return 1
        if not src.exists():
            print(f"[略過] 找不到 {name}")
            continue
        shutil.copy2(src, dst)
        moved.append((name, dst.name, desc))

    if not moved:
        print("沒有可歸檔的檔案")
        return 1

    (archive_dir / f"README_{STAMP}.json").write_text(
        json.dumps(
            {**REASON, "files": {n: d for n, _, d in moved}},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 清空成新口徑的空殼（保留結構，讓下游 load_json 不用特判）
    for name in ("spot_history.json", "contract_history.json"):
        p = DATA / name
        if p.exists():
            p.write_text(
                json.dumps(
                    {
                        "updated": "",
                        "series": {},
                        "price_basis": "session_average",
                        "restarted_at": "2026-08-05",
                        "predecessor": f"_archive/{p.stem}_{STAMP}.json",
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    sh = DATA / "score_history.json"
    if sh.exists():
        sh.write_text(
            json.dumps(
                {
                    "entries": [],
                    "v3_start": "2026-08-05",
                    "restarted_at": "2026-08-05",
                    "predecessor": f"_archive/score_history_{STAMP}.json",
                    "note": "價格口徑改為 Session Average 後重新累積；舊分數不可比",
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    print(f"已歸檔 {len(moved)} 個檔案至 {archive_dir}：")
    for name, dstname, desc in moved:
        print(f"  {name} → {dstname}")
        print(f"      {desc}")
    print("\n現貨／合約／分數三個檔已清空，等今晚重新累積（均價口徑）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
