# 記憶體 Cycle Signal Dashboard V3

**版本**：V3（完整重寫）
**更新日期**：2026-05-24
**前版**：V2（2026-05-12 建立、含 7 個 top-level signal + Hyperscaler 內 5 個 sub-metric）
**設計目的**：在 NVIDIA Q1 FY27、長鑫科技 (CXMT) IPO 進程、美光 (Micron) DDR4 擴產等多重訊號出現後，更新整套監控架構讓記憶體 cycle 追蹤更完善
**實作平台**：Jason 將於另一個專案中以 FinMind + Colab + GitHub Actions 三件組實作

---

## V3 vs V2 的關鍵變動摘要

| 變動類型 | V2 → V3 |
|---------|---------|
| Top-level signal 數量 | 7 個 → **9 個**（新增 Signal 8 中國對手擴產、Signal 9 Cycle ending 時間軸校準）|
| Sub-metric 新增 | Signal 4 加 4f「NVDA supply commitments」、Signal 1 加 1c「DDR5 vs DDR4 分化追蹤」、Signal 6 加 6b「Micron Q3 FY26 outcome 追蹤」|
| 權重重新分配 | 9 個 signal 加總 100%、Hyperscaler 從 25% 降到 20%（demand floor 已確認、邊際資訊價值下降）|
| 既有部位決策樹 | 新增「重大事件前 24 小時鎖倉」原則 |
| MVP 順序 | 中國擴產追蹤從 phase 3 提升到 phase 2（因 CXMT IPO 將在 5/27 上會）|
| 觸發閾值校準 | 基於 5/12-5/24 新資訊修正（特別是 DDR4 軟化已是事實、不再是預警）|

**設計哲學沿用 V2**：可實作優於完美、用機制執行不靠自律、每個 signal 都有明確的 yellow/red 觸發條件。

---

## Layer 1｜Signal 清單（9 個 top-level，含複合 signal）

| # | 訊號 | 領先程度 | 更新頻率 | 權重 | V3 變動 |
|---|------|---------|---------|------|---------|
| 1 | Daily 記憶體現貨報價（含 DDR5/DDR4 分化追蹤） | 最領先 | 每日 | 15% | +sub-metric |
| 2 | DRAM/NAND 月合約價 QoQ | 領先 6-9M | 月 | 15% | 不變 |
| 3 | Spot ÷ Contract ratio | 領先 3-6M | 週 | 12% | -3pp |
| 4 | **Hyperscaler Demand Floor（複合）** | 領先 3-6M | 季 + 月 | **20%** | -5pp |
| 5 | Samsung HBM4 良率進度 | 結構性 | 月 | 10% | 不變 |
| 6 | Micron 毛利率 trajectory + 財報 outcome | 領先 1Q | 季 | 10% | +sub-metric |
| 7 | Samsung / SK Hynix 庫存週數 | 同期 | 月 | 8% | -2pp |
| 8 | **中國對手擴產進度（新增）** | 結構性 | 月 | 7% | NEW |
| 9 | **Cycle ending 時間軸校準（新增）** | 元指標 | 季 | 3% | NEW |

**權重設計邏輯（V3 修正）**：
- Hyperscaler 從 25% → 20%：NVDA Q1 FY27 確認 $725B capex（雙倍化）後，demand floor 邊際資訊價值已下降
- Spot/Contract ratio 從 15% → 12%：DDR4 軟化已是事實、不再是先行指標
- 庫存週數 8%：仍是滯後指標、權重低
- 新增中國擴產 7%：CXMT IPO 是真實催化劑
- 新增 Cycle ending 校準 3%：低權重、但對 long-term timing 至關重要

---

## Layer 2｜各 Signal 內部拆解

### Signal 1：Daily 記憶體現貨報價（含分化追蹤）

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 | 內部權重 |
|-----------|---------|------------|----------|---------|
| 1a. DDR5 spot 5MA | 每日 | 5MA 反轉向下 | 連續 7 天跌幅 > 1% | 50% |
| 1b. DDR5 spot 跌破 contract | 每日 | spot < contract × 0.95 | spot < contract × 0.90 | 30% |
| 1c. **DDR5/DDR4 分化追蹤（新增）** | 每日 | DDR4 持續軟、DDR5 動能放緩 | **DDR5 也開始 spot 弱化** | 20% |

**現況（2026-05-24）**：
- 1a：DDR5 仍強（branded inquiries 增加）→ Green
- 1b：spot 仍高於 contract → Green
- 1c：DDR4 軟、DDR5 仍強 → Yellow（分化是進行中、但對 thesis 中性）

**Signal 1 整體 = Green/Yellow**

**Sub-metric 1c 的詳細設計**：
- 監控指標：DDR5 16Gb spot vs DDR4 16Gb spot 的價格比值
- 當前比值：~2.2x（DDR5 是 DDR4 兩倍多）
- 健康區間：1.8-2.5x
- 警示區間：DDR5/DDR4 比值縮窄到 1.5x 以下（代表 DDR5 軟化追上 DDR4）

---

### Signal 2：DRAM/NAND 月合約價 QoQ

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 |
|-----------|---------|------------|----------|
| 2a. DRAM QoQ | 月 | < +30%（從 +58-63% 顯著放緩） | < +10% |
| 2b. NAND QoQ | 月 | < +30% | < +5% |
| 2c. ASP momentum 第二階導數 | 月 | 連續 2 月放緩 | 連續 3 月放緩 |

**現況**：Q2 2026 DRAM +58-63%、NAND +70-75%，10 年最大漲幅 → Green

**閾值校準（V3）**：V2 設定的「QoQ 從 +60% 收斂到 +20%」太遲。V3 將 yellow 提早到 +30%、給出更早的反應時間。

---

### Signal 3：Spot ÷ Contract ratio

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 |
|-----------|---------|------------|----------|
| 3a. DDR5 spot/contract | 週 | ratio 連續 4 週收斂 | ratio < 1.0（spot 低於 contract）|
| 3b. NAND spot/contract | 週 | ratio 連續 4 週收斂 | ratio < 1.0 |

**現況**：DDR5 spot 仍高於 contract → Green

---

### Signal 4：Hyperscaler Demand Floor（複合，6 個 sub-metric）

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 | 內部權重 |
|-----------|---------|------------|----------|---------|
| 4a. 任一家 capex revision | 季 | 任一家持平或下修 | 連兩家下修 | 25% |
| 4b. Cloud 營收成長率 | 季 | 前季 -5pp | -10pp | 18% |
| 4c. Backlog vs capex 成長率 | 季 | Backlog < capex 成長 | 連兩季背離 | 18% |
| 4d. Capex 公告後股價反應 | 季 | 連三家 -5%+ | Mag 4 累計 -10%+ | 12% |
| 4e. 2027 capex guidance 進度 | 季 | 持平 2026 | 低於 2026 | 12% |
| 4f. **NVDA $119B supply commitments 動向（新增）** | 季 | 維持當前水平 | 縮減 > 10% | 15% |

**現況（2026-05-24，NVDA Q1 FY27 後 update）**：
- 4a：全部上修 → Green
- 4b：Google Cloud +63% 加速、AWS +28% 加速、Azure +40% 持穩 → Green
- 4c：Google backlog QoQ 翻倍 vs capex 約 +4-8% → Green
- 4d：Meta -6%、MSFT -2.5% → Yellow（單一公司、未到觸發條件）
- 4e：Alphabet CFO 已表態 2027 顯著增加、街上預估破 $1T → Green
- 4f：**NVDA 揭露 $119B supply commitments、鎖定產能到明年 → Green**

**Signal 4 整體 = Green**

**Sub-metric 4f 的詳細設計**：
- 資料來源：NVDA 10-Q、季財報法說會 transcript
- 監控重點：$119B 是否每季持平或上升
- 為什麼這是 leading：supply commitments 鎖定的是未來 4-8 季的產能、比 capex 本身更前瞻

---

### Signal 5：Samsung HBM4 良率進度

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 |
|-----------|---------|------------|----------|
| 5a. Samsung HBM4 12-high 量產良率 | 月 | 突破 50% | 突破 70%（搶下 SK Hynix 市佔）|
| 5b. SK Hynix HBM4 出貨進度 | 月 | 進度延後 | 進度大幅延後 |
| 5c. NVDA Vera Rubin 平台 HBM 供應商揭露 | 季 | Samsung 加入名單 | Samsung 取代 Micron |

**現況**：Samsung HBM4 良率仍待觀察、SK Hynix 領先、Micron Q1 2026 已量產 HBM4 12-high 給 NVDA Vera Rubin → Green

---

### Signal 6：Micron 毛利率 trajectory + 財報 outcome（新增 sub-metric）

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 | 內部權重 |
|-----------|---------|------------|----------|---------|
| 6a. Micron 毛利率 QoQ | 季 | 從 75% 連續 1 季下滑 | 連續 2 季下滑 | 50% |
| 6b. **Micron Q3 FY26 outcome（單一事件追蹤）（新增）** | 6/24-25 | 營收 in line 但 Q4 guide 不再升 | 營收 miss + guide 下修 + 管理層用「moderation」字眼 | 30% |
| 6c. **HBM revenue 揭露** | 季 | 持平或微減 | YoY 衰退 | 20% |

**現況**：
- 6a：Q3 FY26 guide 81%（破紀錄）→ Green
- 6b：將於 6/24-25 公佈 → 待定
- 6c：HBM 預期 $2B+/月 → Green

**Signal 6 的特殊重要性**：6/24-25 Micron Q3 FY26 財報是近期最重要的單一事件。Sub-metric 6b 在事件公佈當天會主導整個 Signal 6 評分。

**Q3 FY26 三情境機率（事前預估）**：
- 🟢 超預期且大幅上修：35% → Signal 6 維持 Green、加強
- 🔵 達標但無 surprise：50% → Signal 6 維持 Green
- 🔴 guidance miss：15% → Signal 6 立刻翻 Red、整體 Cycle Score 跳升 1.5+

---

### Signal 7：Samsung / SK Hynix 庫存週數

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 |
|-----------|---------|------------|----------|
| 7a. Samsung DRAM 庫存週數 | 月 | 從 6 週回升到 8+ 週 | > 12 週 |
| 7b. SK Hynix DRAM 庫存週數 | 月 | 從 2-3 週回升到 5+ 週 | > 8 週 |
| 7c. SK Hynix NAND 庫存週數 | 月 | 從 3-4 週回升到 6+ 週 | > 10 週 |

**現況**：全部歷史低點 → Green

---

### Signal 8：中國對手擴產進度（V3 新增）

| Sub-metric | 監控頻率 | Yellow 觸發 | Red 觸發 | 內部權重 |
|-----------|---------|------------|----------|---------|
| 8a. 長鑫科技 (CXMT) IPO 進度 | 月 | 過會 + 高估值 | 過會 + 募資 > $5B + 明確擴產用途 | 30% |
| 8b. 長鑫科技 (CXMT) 客戶名單擴大 | 月 | Tier 2 品牌加入（如 Corsair） | Tier 1 品牌加入（Dell、HP）| 25% |
| 8c. 長江存儲 (YMTC) IPO 進度 | 月 | 啟動輔導備案 → 申請受理 | 過會 + 大規模募資 | 20% |
| 8d. 中國 HBM 進度 | 月 | 良率突破 30% | 量產 HBM3 並出貨 | 15% |
| 8e. CXMT/YMTC 月產能 ramp | 月 | 月增 > 5% | 月增 > 10% | 10% |

**現況（2026-05-24）**：
- 8a：5/27 上會審核 → Yellow（待定）
- 8b：Corsair DDR5 用 CXMT 晶片 → Yellow（剛擴大、需觀察持續性）
- 8c：5/19 已啟動 IPO 輔導備案 → Yellow（剛啟動）
- 8d：仍落後 SK Hynix 4 年 → Green
- 8e：CXMT DDR4 產能反而從 2 萬片/月降到 1 萬片/月 → Green

**Signal 8 整體 = Yellow**（多個 sub-metric 在 yellow 但未到 red、需要密切觀察 5/27 結果）

**為什麼新增 Signal 8**：
1. V2 完全沒有這個維度、是個明顯漏洞
2. CXMT IPO 是真實的潛在催化劑（不是看衰文章捏造）
3. 中國擴產是「結構性風險」、跟 cyclical 的 ASP 動能是不同性質
4. 長江存儲 (YMTC) 後續會跟上、需要兩個 IPO 一起追蹤

---

### Signal 9：Cycle ending 時間軸校準（V3 新增）

| Sub-metric | 監控頻率 | 內容 |
|-----------|---------|------|
| 9a. 業內資深人士警告時間軸 | 季 | 整理券商分析師、退休 / 在任高管對 cycle ending 的具體時間預測 |
| 9b. Dashboard 隱含時間軸 vs 共識時間軸 | 季 | 比較我們 dashboard 推斷的時間 vs 街上共識的時間 |
| 9c. 股票 vs 基本面領先指標 | 季 | 確認「股票領先基本面 6-9 個月」的假設仍成立 |

**現況**：
- 9a：慶桂顯（前三星）警告 2027 H2 反轉、BofA 中性、Goldman 預期 undersupply 至 2027 → 共識在 2027 H2 ± 一季
- 9b：Dashboard 推斷高峰落 2026 下半 ~ 2027 上半、股票領先 → 2026 Q4 ~ 2027 Q1 為觀察點 → 與共識一致
- 9c：歷史 cycle 領先 6-9 個月、目前仍適用

**為什麼新增 Signal 9**：
- V2 沒有 meta-level 的時間軸校準
- 慶桂顯警告促發這個 sub-signal 的必要性 — 不是因為他說對了、而是他提供了校準的錨點
- 未來再有類似業內警告、需要系統化記錄 + 校準、不是看完就忘

**這是元指標（meta-signal）**：不直接影響 Cycle Position 分數、但影響「整體 dashboard 是否需要校準閾值」

---

## Layer 3｜資料源 mapping（V3 update）

| Signal | 主來源 | 取得方式 | V3 變動 |
|--------|-------|---------|---------|
| 1. Daily spot（含分化） | DRAMeXchange、PCPartPicker、Aida64 spot table | 每日爬蟲 | + DDR5/DDR4 比值計算 |
| 2. 月合約價 | TrendForce 月報、DRAMeXchange | 月度抓取 | 不變 |
| 3. Spot/Contract ratio | 上述兩者組合 | 計算 | 不變 |
| 4a. Capex revision | MSFT/AMZN/GOOG/META 10-Q + transcript | LLM parse | 不變 |
| 4b. Cloud 營收 | 各家 10-Q：Azure、AWS、Google Cloud 分部 | 季度抓取 | 不變 |
| 4c. Backlog | Alphabet RPO、MSFT Commercial RPO、AMZN Backlog | 10-Q 抓取 | 不變 |
| 4d. 股價反應 | Yahoo Finance / Polygon API | 自動 | 不變 |
| 4e. 2027 guidance | Earnings call transcript | LLM 語意分析 | 不變 |
| **4f. NVDA supply commitments** | **NVDA 10-Q（Note disclosure）** | **季度抓取** | **NEW** |
| 5. HBM 良率 | TheElec、Korea Economic Daily、Reuters Tech | RSS + keyword filter | 不變 |
| 6a. Micron 毛利率 | SEC EDGAR 10-Q | 季度抓 | 不變 |
| **6b. Q3 FY26 outcome** | **Micron 法說會（6/24-25 盤後）** | **即時 + 隔日 follow-up** | **NEW** |
| 6c. HBM revenue | Micron 法說會 prepared remarks + Q&A | 季度抓 | 不變 |
| 7. 庫存週數 | TrendForce 供需 report、Counterpoint | 月度抓取 | 不變 |
| **8a. CXMT IPO** | **上交所公告、招股書、財經媒體** | **每月** | **NEW** |
| **8b. 客戶名單** | **新聞檢索、PCMag teardown reports** | **每月** | **NEW** |
| **8c. YMTC IPO** | **證監會公告、財經媒體** | **每月** | **NEW** |
| **8d. 中國 HBM** | **TechInsights、SemiAnalysis、TheElec** | **每月** | **NEW** |
| **8e. 月產能** | **TrendForce 月度供需 report** | **每月** | **NEW** |
| **9. Cycle ending 校準** | **券商分析師報告、業內人士訪談** | **季度** | **NEW** |

---

## Layer 4｜自動化架構（沿用 V2 + 新增）

**GitHub Actions cron**：

```
每日 06:00 UTC：
  - 抓 spot price → 計算 5MA / 20MA → 存 DB → 比對 trigger（Signal 1a）
  - 計算 Spot/Contract ratio（Signal 3）
  - 計算 DDR5/DDR4 比值（Signal 1c，新增）

每週一 08:00：
  - 彙整所有 signal 當前狀態 → 產 weekly digest

每月 5 號：
  - 抓 TrendForce 月度合約價（Signal 2）
  - 抓 Counterpoint 庫存週數（Signal 7）
  - 掃 HBM 良率新聞（Signal 5）
  - 掃中國對手擴產新聞（Signal 8，新增）

財報日前後（MSFT/AMZN/GOOG/META/NVDA 動態排程）：
  - T+0：抓股價反應（4d）
  - T+1：抓 transcript → LLM parse capex/backlog/cloud rev（4a/4b/4c/4e）
  - T+2：產出 Hyperscaler Signal 4 更新報告
  - T+1：抓 NVDA 10-Q 中 supply commitments（4f，新增）

季度（Micron 財報後）：
  - 抓 Micron 毛利率（Signal 6a）
  - 抓 Micron 財報 outcome 評分（Signal 6b，新增）
  - 抓 HBM revenue 揭露（Signal 6c）

特別事件（CXMT 上會 / 掛牌、YMTC 進度）：
  - 即時推播 + 隔日 follow-up 報告
```

**Colab notebook（手動 deep dive）**：
- 每月跑 Cycle Position 計算
- 每季校準 Signal 9（Cycle ending 時間軸）

**Storage**：SQLite + GitHub repo 存 raw data

---

## Layer 5｜Output 設計

### A. Cycle Position 分數計算公式（V3）

```
Cycle Score =
  0.15 × Signal_1_score (Daily spot + DDR5/DDR4 分化)
+ 0.15 × Signal_2_score (Monthly contract)
+ 0.12 × Signal_3_score (Spot/Contract ratio)
+ 0.20 × Signal_4_composite
+ 0.10 × Signal_5_score (HBM yield)
+ 0.10 × Signal_6_score (Micron GM + Q3 outcome)
+ 0.08 × Signal_7_score (Inventory)
+ 0.07 × Signal_8_score (China expansion)
+ 0.03 × Signal_9_score (Cycle ending calibration)

Signal_1_composite = 0.50 × Sub_1a + 0.30 × Sub_1b + 0.20 × Sub_1c

Signal_4_composite =
  0.25 × Sub_4a + 0.18 × Sub_4b + 0.18 × Sub_4c + 0.12 × Sub_4d
+ 0.12 × Sub_4e + 0.15 × Sub_4f

Signal_6_composite = 0.50 × Sub_6a + 0.30 × Sub_6b + 0.20 × Sub_6c

Signal_8_composite =
  0.30 × Sub_8a + 0.25 × Sub_8b + 0.20 × Sub_8c + 0.15 × Sub_8d + 0.10 × Sub_8e
```

**位置區間**：
- 0-3：Early cycle（加碼區）
- 4-6：Mid cycle（持有區、目前位置在 5-6）
- 7-8：Late cycle（停加碼 + 設停利）
- 9-10：Peak（分批出清）

### B. Alert 觸發（V3 update）

```
Yellow Alert（推播通知）：
  - 任一 signal 進 Yellow zone
  - 連續 3 天 Daily spot 跌破 5MA
  - 中國對手 IPO 過會（Signal 8a Yellow）
  - DDR5/DDR4 比值跌破 1.8x（Signal 1c Yellow）

Red Alert（強制 review）：
  - 任 2 個 top-level signal 進 Red
  - Signal 4 任一 sub-metric 進 Red
  - Signal 6b Micron Q3 FY26 miss
  - Cycle Score 連續 2 週爬升 ≥ 1 分
  - 中國對手 IPO 募資後明確擴產用途公告
```

### C. 持倉建議燈號

| Cycle Score | 燈號 | 建議 |
|-----------|------|------|
| 0-3 | 🟢 Green | Hold / 可加碼 |
| 4-6 | 🟢 Green | Hold（目前位置）|
| 7 | 🟡 Yellow-low | 停止加碼 |
| 8 | 🟡 Yellow-high | 設移動停利、減 1/3 部位 |
| 9 | 🔴 Red | 減半部位 |
| 10 | 🔴 Red-peak | 出清主要部位 |

### D. 既有部位決策樹（V3 新增「事件鎖倉」原則）

**鎖倉原則（V3 新增）**：

```
重大事件前 24 小時：
  - Micron 財報前 24 小時 → 鎖倉、不動部位
  - NVDA 財報前 24 小時 → 不採取行動
  - CXMT 上會審核前 24 小時 → 不採取行動
  - Hyperscaler 季財報前 24 小時 → 不採取行動

事件後 1 個交易日：
  - 觀察市場反應、但不立即行動
  - 區分 sentiment（短期股價情緒）vs thesis（長期基本面）
  - 不在事件當晚或盤前作減碼決定
```

**為什麼新增鎖倉原則**：
- Jason 在 NVDA 財報前的「該不該減碼」焦慮、是典型的 event-anxiety
- 大多數投資人在事件前後做的決策都比平時差
- 鎖倉原則用機制化的方式避免這個 bias

**完整決策樹（V3）**：

```
如果 Cycle Score < 4：
  → 完全 Green Zone，可加碼

如果 Cycle Score 4-6（目前位置）：
  → Hold，密切監控
  → 不主動減碼
  → 重大事件前 24 小時鎖倉

如果 Cycle Score 7：
  → 停止加碼
  → 設 trailing stop（最高點 -10%）
  → 開始準備分批出脫計畫

如果 Cycle Score 8：
  → 主動減 1/3 部位
  → 剩餘 2/3 設更緊 trailing stop（最高點 -7%）

如果 Cycle Score 9-10：
  → 分批出清
  → 8 週內逐步降到 25% 部位
  → 不在單日全部出清（避免擇時失誤）

絕對紅燈（不論 Cycle Score）：
  → ASP momentum QoQ 翻負
  → Micron 毛利率連兩季下滑
  → 任兩家 Mag 4 hyperscaler 同時下修 capex
  → 中國對手 HBM 量產出貨給 Tier 1 客戶
  → 出現任何一個 → 不論價位，分批出清主要部位
```

---

## Layer 6｜MVP 實作優先順序（V3 重新排序）

**Phase 1（必做、2-3 週內上線）**：

1. **Daily spot + 5MA + DDR5/DDR4 分化**（Signal 1）— 技術門檻最低、Jason 已關注此 metric
2. **Hyperscaler capex revision 監控**（Signal 4a + 4f）— 影響最大
3. **Micron Q3 FY26 outcome 追蹤**（Signal 6b）— 6/24-25 即將發生

**Phase 2（4-6 週內、CXMT IPO 前必須完成）**：

4. **中國對手擴產追蹤（Signal 8 全部）** — 從 V2 phase 3 提前到 phase 2，因為 5/27 上會審核已迫在眉睫
5. **Cloud 營收成長 trajectory**（4b）— SEC EDGAR API 自動抓
6. **Micron 毛利率 + HBM revenue**（6a + 6c）— 季度抓
7. **股價反應監控**（4d）— 技術簡單

**Phase 3（其他）**：

8. 剩下的 signal（Signal 5、7、9 + sub-metric 完整化）
9. Signal 9 元指標（Cycle ending 校準）— 季度更新即可

**V2 vs V3 MVP 順序變動原因**：
- 中國擴產從 phase 3 提前到 phase 2：因為 CXMT IPO 是已知日期的真實催化劑
- Micron Q3 FY26 outcome 從未列入到 phase 1：因為 6/24-25 即將發生、必須當天就能追蹤

---

## Layer 7｜重要 caveat（V3 update）

**V2 已列**：
1. Spot price 來源容易斷：至少抓 2-3 個來源 cross-check
2. LLM parse transcript 容易失準：4a/4e 一定要人工 verify
3. Counterpoint 庫存週數可能要付費：免費替代 TrendForce
4. 時區處理：cron 設亞洲時區避免錯過 T+0 股價反應

**V3 新增**：

5. **中國對手資料的可信度**：
   - 中國公司財報透明度低於美股
   - CXMT 招股書是 IPO 衝刺期公告、可能有戰略性披露
   - 建議交叉驗證 SemiAnalysis、TechInsights、TheElec 三個來源
   
6. **Signal 6b 的事件性**：
   - Micron Q3 FY26 outcome 是單一事件、不是 continuous signal
   - 評分要在 6/24-25 當天設定、然後在下次財報前維持
   - 不要每天重新計算這個 sub-metric
   
7. **Signal 9 的元性質**：
   - 不是 quantitative signal、是 qualitative calibration
   - 季度更新即可、不需要 daily / weekly
   - 主要用途是「確認 dashboard 整體閾值是否需要校準」、不是直接影響部位決策

---

## Layer 8｜當前 Cycle Position 評估（2026-05-24）

基於 V3 框架的當前評分：

| Signal | 評分 (0-10) | 加權 | 加權分 |
|--------|------------|------|--------|
| 1. Daily spot + 分化 | 4.5（Yellow because of 1c） | 15% | 0.675 |
| 2. 月合約價 QoQ | 3（仍強）| 15% | 0.45 |
| 3. Spot/Contract ratio | 3 | 12% | 0.36 |
| 4. Hyperscaler（複合） | 3.5（4d Yellow but rest Green）| 20% | 0.70 |
| 5. HBM 良率 | 3 | 10% | 0.30 |
| 6. Micron 毛利率 + Q3 outcome | 3 | 10% | 0.30 |
| 7. 庫存週數 | 3 | 8% | 0.24 |
| 8. 中國對手擴產 | 6（Yellow 多） | 7% | 0.42 |
| 9. Cycle ending 校準 | 5（共識 2027 H2）| 3% | 0.15 |
| **Cycle Score** | | | **3.60 / 10** |

**位置判斷**：3.60 屬於 Early-Mid 過渡區（V2 設計區間 0-3 Early、4-6 Mid）。實際位置在 **3-4 之間、尚未進入 Mid cycle 後段**。

**對比 V2（2026-05-12）的 Cycle Score 估算**：當時粗估在 5.5-6（依 Bjorn 的 50-60%）。V3 評分相對較低、主要原因：
- V3 加入更多細緻的 sub-metric、評分整體偏向資料導向（不靠 gut feel）
- 中國擴產（Signal 8）目前 yellow 但低權重、不顯著影響整體
- Daily spot 仍綠燈、月合約價 momentum 仍強

**結論**：dashboard 評分顯示仍在 hold zone、不該主動減碼。但需密切監控 6/24-25 Micron 財報、5/27 CXMT 上會、以及 DDR5/DDR4 分化是否進一步擴大。

---

## Layer 9｜下次更新觸發條件

**強制更新 dashboard V4 的條件**：

1. **Cycle Score 跳升 ≥ 2 分**（任一週內）
2. **任 2 個 top-level signal 進 Red**
3. **Micron Q3 FY26 outcome 落入 Red 情境**（6/24-25 之後）
4. **CXMT IPO 結果出現極端情境**（過會 + 募資後立刻宣布大規模擴產 / 退件）
5. **Hyperscaler 任一家正式下修 capex**
6. **NVDA Q2 FY27 結果跟預期重大背離**

**例行性更新（不一定觸發 V4、但需要 review）**：
- 每月月初：複查所有 signal 評分
- 每季財報季結束後：校準 Signal 9 cycle ending 時間軸

---

## 結語

V3 相對 V2 的最大改進不是「多了 2 個 signal」、是「**用機制化的方式回應今天討論中出現的所有真實催化劑**」。

V2 漏掉的東西：
- 完全沒有中國對手擴產的 dimension
- 沒有 cycle ending 時間軸校準的 meta-signal
- Hyperscaler 子訊號沒包含 NVDA supply commitments

V3 補上這些後、整套 dashboard 從「7 個 signal 的監控架構」演化成「**9 個 signal + 跨層級校準機制 + 事件鎖倉原則**」的完整 cycle 追蹤系統。

設計哲學沒變：
- 可實作優於完美
- 用機制執行不靠自律
- 每個 signal 都有明確閾值
- 看訊號變動、不看單日股價

**最重要的一句話**：dashboard 不是用來預測 cycle peak 在哪一天、是用來在 peak 來臨前 6-9 個月給出系統化警示。如果 V3 能在 2026 Q4 真的觸發 Red Alert、且 Jason 因此提前分批出脫、那這份架構的所有設計成本都值得。

下次 dashboard 更新時、回來讀這份 V3 設計文件。所有閾值跟權重的理由都在裡面。
