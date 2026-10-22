"""SEC XBRL companyfacts 的純函式（fetch_sec_fundamentals / fetch_micron_gross / 測試共用，2026-10-22）。

為什麼要自己拆單季：
  現金流量表（capex）在 10-Q 只給「年初至今」累計，Q2/Q3 沒有單季數；10-K 只給全年，
  第四季永遠沒有單季數。舊的 fetch_micron_gross 只收 65~100 天的期間，所以 Micron 每年
  8 月底那季（FQ4）從來抓不到——2026-10-01 就是這樣停在 FQ3 84.6%、實際 FQ4 已是 86.8%。
  這裡的規則：同一個起始日的累計值依序相減（3M、6M、9M、12M → 四個單季），
  有直接單季數就優先用直接值（兩者不一致時記下差異，不默默挑一個）。

日期口徑：
  available＝這個數字第一次出現在哪份申報的申報日（不是期末日、也不是最後一次被重述的日子）。
  新鮮度問的是「什麼時候能知道」，用最後一次重述的申報日會把兩年前的季度當成今天的新資料。
"""

from datetime import date, timedelta

FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")
QUARTER_DAYS = (80, 105)  # 13 週＝91 天、14 週＝98 天（Micron 53 週年的第四季）


def _d(s):
    return date.fromisoformat(s)


def _days(start, end):
    return (_d(end) - _d(start)).days


def _dedupe(entries, key):
    """同一期間被多份申報重複揭露：值取最後一次申報（含重述），available 取第一次申報。"""
    best = {}
    for e in entries:
        if e.get("form") not in FORMS or e.get("val") is None or not e.get("filed"):
            continue
        k = key(e)
        cur = best.get(k)
        if cur is None:
            best[k] = {
                "val": e["val"],
                "filed": e["filed"],
                "first_filed": e["filed"],
                "form": e["form"],
            }
            continue
        if e["filed"] > cur["filed"]:
            cur.update(val=e["val"], filed=e["filed"], form=e["form"])
        if e["filed"] < cur["first_filed"]:
            cur["first_filed"] = e["filed"]
    return best


def quarterly(entries):
    """duration 事實 → {期末日: {start, end, days, val, available, method, fq}}。

    fq＝會計年度內第幾季（1~4，只有從累計值推得出來時才有；直接單季數沒有就是 None）。
    """
    facts = _dedupe(
        [e for e in entries if e.get("start")], lambda e: (e["start"], e["end"])
    )
    q, mismatch = {}, []
    for (s, e), v in facts.items():
        d = _days(s, e) + 1  # 含首尾的天數：13 週＝91、14 週＝98
        if QUARTER_DAYS[0] <= d <= QUARTER_DAYS[1]:
            q[e] = {
                "start": s,
                "end": e,
                "days": d,
                "val": v["val"],
                "available": v["first_filed"],
                "method": "direct",
                "fq": None,
            }

    by_start = {}
    for (s, e), v in facts.items():
        d = _days(s, e) + 1
        n = round(d / 91.3)
        # 累計 n 季的天數要落在合理範圍，排除 TTM、兩年期之類的期間
        if 1 <= n <= 4 and abs(d - n * 91.3) <= 12:
            by_start.setdefault(s, []).append((e, n, v))
    for s, rows in by_start.items():
        rows.sort()
        # 只取從 1 季起連續的累計鏈（3M→6M→9M→12M）。累計鏈斷了（例如只有 12M 沒有 9M）
        # 就停在斷點——少了中間那段，相減出來的不是單季。
        chain = []
        for e, n, v in rows:
            if n != len(chain) + 1:
                break
            chain.append((e, n, v))
        # ★鏈長 1 不是累計鏈：MSFT 每季都給直接單季數、AMZN 的單季起始日又剛好是 TTM 的起始日，
        #   拿它推「第幾季」會把每一季都標成 fq=1，下一份是不是 10-K 就判錯
        if len(chain) < 2:
            continue
        prev_end, prev_val = None, 0.0
        for e, n, v in chain:
            q_start = (
                s
                if prev_end is None
                else (_d(prev_end) + timedelta(days=1)).isoformat()
            )
            q_days = _days(q_start, e) + 1
            val = v["val"] - prev_val
            rec = q.get(e)
            if rec is None:
                if QUARTER_DAYS[0] <= q_days <= QUARTER_DAYS[1]:
                    q[e] = {
                        "start": q_start,
                        "end": e,
                        "days": q_days,
                        "val": val,
                        "available": v["first_filed"],
                        "method": "derived" if n > 1 else "direct",
                        "fq": n,
                    }
            else:
                rec["fq"] = n
                if rec["val"] and abs(rec["val"] - val) / abs(rec["val"]) > 0.01:
                    mismatch.append({"end": e, "direct": rec["val"], "derived": val})
            prev_end, prev_val = e, v["val"]
    return q, mismatch


def instants(entries):
    """instant 事實（存貨、RPO）→ {期末日: {end, val, available}}。"""
    facts = _dedupe([e for e in entries if not e.get("start")], lambda e: e["end"])
    return {
        e: {"end": e, "val": v["val"], "available": v["first_filed"]}
        for e, v in facts.items()
    }


def pick_concept(gaap, names, kind="duration"):
    """候選標籤裡取「最新期末日最晚」的那一個（AMZN 的 capex 2017 年起換了標籤）。
    不跨標籤拼接：兩個標籤的定義可能不同，拼起來的 YoY 會是定義變更不是業務變化。"""
    best, best_end = None, ""
    for n in names:
        units = (gaap.get(n) or {}).get("units", {}).get("USD") or []
        ends = [
            u["end"]
            for u in units
            if u.get("form") in FORMS and (bool(u.get("start")) == (kind == "duration"))
        ]
        if ends and max(ends) > best_end:
            best, best_end = n, max(ends)
    return best


def next_filing_due(last_end, fy_end_months, calendar_quarters, fq=None):
    """下一份季報／年報的法定申報期限（大型加速申報人：10-Q 期末後 40 天、10-K 60 天）。

    這是外部事件日（法規期限），符合 next_due 的規則一；實際多半更早申報，所以這條線只會偏寬、
    不會誤報逾期。fq 已知時直接判下一季是不是第四季；不知道時看下一個期末落在哪個月。
    """
    end = _d(last_end)
    if calendar_quarters:
        y, m = end.year, end.month + 3
        if m > 12:
            y, m = y + 1, m - 12
        nxt = date(y, m, 28)
        while (nxt + timedelta(days=1)).month == m:
            nxt += timedelta(days=1)
    else:
        nxt = end + timedelta(days=91)
    if fq is not None:
        is_10k = fq % 4 + 1 == 4
    else:
        is_10k = nxt.month in fy_end_months
    form = "10-K" if is_10k else "10-Q"
    return {
        "next_period_end_est": nxt.isoformat(),
        "next_form": form,
        "due": (nxt + timedelta(days=60 if is_10k else 40)).isoformat(),
    }
