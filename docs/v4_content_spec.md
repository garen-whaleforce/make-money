# Daily Deep Brief v4 Content Specification

> 本文件定義 v4 版本三篇文章（Flash/Earnings/Deep Dive）的內容規格，包含免費區與會員專屬區的結構、字數範圍、JSON schema 欄位，以及 Ghost 設定。

---

## 核心升級原則

### 1. 會員專屬價值提升

| 項目 | v3 現況 | v4 目標 |
|------|---------|---------|
| 財務數據 | 部分 null | 完整填充（FMP + SEC） |
| 估值方法 | 僅 P/E 推演 | 三角定位（P/E + EV/Sales + P/FCF） |
| 決策工具 | If/Then 概念 | 觸發→行動→驗證 三段式 |
| 來源追溯 | 列出 3 個 | 5-8 個可核對來源 |

### 2. Flash 新聞覆蓋提升

| 項目 | v3 現況 | v4 目標 |
|------|---------|---------|
| 新聞條目 | 2 條 | 7-8 條 |
| 結構 | 全部深拆 | 1 深拆 + 3 短拆 + 4 提醒 |
| 多樣性 | 單一主題 | 4 類別覆蓋 |

---

## Post A: Flash（每日快報）

### 定位
每日 06:00 ET 推送的「市場入口」，讓讀者 3 分鐘掌握今日重點。

### Ghost 設定
- **Post access**: `members`（免費會員即可解鎖全文）
- **Paywall position**: 在「產業影響地圖」後
- **Newsletter**: `daily-en`，segment: `all`

### 免費區（Public Preview）~ 800-1000 字

```
1. Badge 列（Daily Brief / Flash / 主題 / 時段）
2. 資料時間戳記
3. Today's Package（三件套導覽）
4. 中文摘要（150 字）
5. English Executive Summary（150 字）
6. 一句話結論（Thesis）
7. Market Snapshot（5 個數字）
   - SPY / QQQ / 10Y / DXY / VIX
8. 三個必記數字
9. TL;DR（5-7 bullets）
10. Top 1 主線深拆（What/Why/Who wins/Who loses/Watch）
11. Top 2-4 次主線（每條 2-3 行）
12. Top 5-8 補充（每條 1 行）
13. 重新定價儀表板（4 變數）
14. 產業影響地圖（一階 + 二階）
```

### 會員專屬區 ~ 600-800 字

```
15. Ticker Playbook 升級版
    - 表格：Ticker | 價格 | 漲跌 | Setup | Catalyst | Risk | Valuation Anchor
    - 每個 ticker 的 If/Then 兩週劇本
16. 二階受惠清單（含觸發條件）
    - Ticker | Why sensitive | What to watch | Trigger | Invalidation
17. 情境策略表（Bull/Base/Bear）
    - 條件 | 市場反應 | 下一個驗證點
18. 明日觀察（Tomorrow's Calendar）
    - 經濟數據 / 財報 / Fed speak / 重大事件
19. 反方論點 + 失效條件
20. 資料來源（5-8 個）
21. 免責聲明
```

### JSON Schema 新增欄位

```json
{
  "market_snapshot": {
    "spy_change": "+0.8%",
    "qqq_change": "+1.2%",
    "us10y": "4.25%",
    "dxy": "103.5",
    "vix": "14.2"
  },
  "news_items": [
    {
      "rank": 1,
      "type": "deep",  // deep | short | mention
      "headline": "...",
      "headline_zh": "...",
      "source": "...",
      "impact_score": 95,
      "direction": "positive",  // positive | negative | mixed
      "affected_sectors": ["AI Semiconductors"],
      "affected_tickers": ["NVDA", "AMD"],
      "what_happened": "...",
      "why_matters": "...",
      "who_wins": ["NVDA"],
      "who_loses": [],
      "what_to_watch": ["..."]
    }
    // ... 7-8 items total
  ],
  "news_diversity": {
    "macro_policy": 1,
    "mega_cap": 2,
    "sector_cycle": 3,
    "single_name": 2
  },
  "second_order_plays": [
    {
      "ticker": "MRVL",
      "why_sensitive": "AI 網通需求",
      "what_to_watch": "雲端訂單",
      "trigger": "NVDA 交付確認",
      "invalidation": "雲端 Capex 下修"
    }
  ],
  "tomorrow_calendar": [
    {
      "time": "08:30",
      "event": "非農就業",
      "importance": "high",
      "affected_tickers": ["SPY", "TLT"]
    }
  ]
}
```

---

## Post B: Earnings（財報/法說前瞻）

### 定位
法說會前 24-48 小時發佈，提供「估值壓力測試 + 預期差拆解 + 會後劇本」。

### Ghost 設定
- **Post access**: `members`
- **Paywall position**: 在「市場在聽什麼」後
- **Newsletter**: 不單獨發送（隨 Flash 導流）

### 免費區（Public Preview）~ 600-800 字

```
1. Badge 列
2. Today's Package
3. 中文摘要（200 字）
4. English Executive Summary（150 字）
5. 一句話結論
6. 估值壓力測試表
   - Bear / Peer Median / Base / Bull
   - P/E 假設 | 錨定來源 | 目標價 | 解讀
7. 市場在聽什麼（3-4 個變數）
```

### 會員專屬區 ~ 800-1000 字

```
8. 預期差堆疊表（Expectation Stack）
   - 項目 | 市場共識 | 關鍵閾值 | 正/負反應區間
   - 含：指引、毛利率、交付、Capex
9. 同業比較升級版
   - 表格：Ticker | 價格 | P/E | EV/Sales | 毛利率 | 估值框架
   - 估值框架差異說明（平台溢價 vs 商品化）
10. 法說會提問清單（5-8 個）
11. 會後三情境劇本
    - Beat+強指引 | In-line | Miss/轉弱
    - 你會聽到什麼 | 市場反應 | T+1/T+3/T+10 追蹤
12. 同業 re-rate 地圖
    - 若 NVDA 溢價守住 → 誰跟漲
    - 若 NVDA 溢價收斂 → 誰補跌
13. 資料來源 + 免責
```

### JSON Schema 新增欄位

```json
{
  "expectation_stack": [
    {
      "item": "Q1 Revenue Guidance",
      "consensus": "$38.5B",
      "critical_threshold": "$37B / $40B",
      "positive_reaction": "> $39B + 上修語氣",
      "negative_reaction": "< $37B 或下修語氣"
    }
  ],
  "peer_comparison_extended": [
    {
      "ticker": "NVDA",
      "price": 188.85,
      "pe_ttm": 52.3,
      "pe_forward": 45.2,
      "ev_sales": 28.5,
      "gross_margin": 70.1,
      "valuation_framework": "平台型溢價（軟硬整合）"
    }
  ],
  "post_call_tracking": {
    "t_plus_1": ["隔日價格反應", "期權隱含波動"],
    "t_plus_3": ["分析師調評", "資金流向"],
    "t_plus_10": ["同業跟進", "訂單驗證"]
  },
  "peer_rerate_map": {
    "if_nvda_holds_premium": ["AMD +", "AVGO +", "TSM +"],
    "if_nvda_premium_compresses": ["AMD -", "QCOM flat"]
  }
}
```

---

## Post C: Deep Dive（深度研究）

### 定位
每日或每週發佈的「投資備忘錄」，提供完整的商業模式、估值、風險分析。

### Ghost 設定
- **Post access**: `members`（或 `paid` 如果要區分付費）
- **Paywall position**: 在「多空對決」後
- **Newsletter**: 不單獨發送

### 免費區（Public Preview）~ 1000-1200 字

```
1. Badge 列
2. Today's Package
3. 閱讀指南（3 分鐘 / 15 分鐘 / 完整）
4. 中文摘要（200 字）
5. English Executive Summary（250 字）
6. 五個必記數字
7. 多空對決（Bull vs Bear 論點）
8. 商業模式概覽（1 段）
```

### 會員專屬區 ~ 2500-3500 字

```
9. 三段式財務引擎（Revenue / Margin / FCF）
   A. 營收引擎
      - 收入結構（Data Center / Gaming / ProViz / Auto）
      - 每段 KPI（出貨、ASP、市佔、Backlog）
   B. 毛利引擎
      - 價格 × 成本 × 供需 拆解
      - 什麼情境會壓縮毛利
   C. 現金流引擎
      - FCF 趨勢（4-8 季）
      - 風險來源（庫存、應收、Capex）

10. 競爭地圖矩陣
    - 列：NVDA / AMD / AVGO / Hyperscaler 自研
    - 欄：Perf/W | 軟體生態 | 供給 | TCO | 導入門檻 | 毛利結構
    - 框架切換點說明

11. 護城河評估
    - 硬體護城河 vs 軟體護城河
    - 持續性評估

12. 估值四錨點 + 敏感度矩陣
    - P/E / EV/Sales / EV/EBITDA / P/FCF
    - 市場隱含成長反推
    - 敏感度表（EPS × P/E → Price）

13. 核心假設表（Base / Bull / Bear）
    - 收入成長、毛利率、OpEx、稅率、股本假設
    - 每個情境的觸發條件

14. What Would Change My Mind
    - 推翻 Bull case 的條件
    - 推翻 Bear case 的條件
    - 可觀測指標

15. 監控儀表板
    - KPI 監控（毛利率、DC 成長、Backlog）
    - 事件監控（法說、競品、雲端 Capex）
    - 市場訊號（SMH 流向、同向交易風險）

16. 90 天催化劑行事曆
    - 日期 | 事件 | 影響 KPI | Bullish 訊號 | Bearish 訊號

17. If/Then 決策樹
    - 條件式的加碼/減碼框架

18. 管理層提問清單

19. 資料附錄（Appendix）
    - 財務數據表
    - 來源引用（5-8 個 SEC/FMP/公司發表）

20. 免責聲明
```

### JSON Schema 新增欄位

```json
{
  "financial_engine": {
    "revenue": {
      "segments": [
        {
          "name": "Data Center",
          "revenue_pct": 78,
          "growth_yoy": 122,
          "kpis": ["GPU 出貨量", "ASP 趨勢", "Backlog"]
        }
      ]
    },
    "margin": {
      "gross_margin_ttm": 70.1,
      "gross_margin_trend": [68.5, 69.2, 70.1, 70.5],
      "drivers": ["定價權", "產品組合", "供需"],
      "compression_scenarios": ["競爭加劇", "產能過剩"]
    },
    "fcf": {
      "fcf_ttm": 28500000000,
      "fcf_margin": 45.2,
      "fcf_trend": [22.1, 25.3, 28.5, 30.2],
      "risk_factors": ["庫存堆積", "Capex 增加", "應收帳款"]
    }
  },
  "competition_matrix": {
    "players": ["NVDA", "AMD", "AVGO", "Custom ASIC"],
    "dimensions": ["perf_per_watt", "software_ecosystem", "supply", "tco", "adoption_barrier", "margin_structure"],
    "nvda_scores": [95, 95, 70, 60, 30, 90],
    "switching_trigger": "若推理 TCO 成為主要考量，ASIC 競爭力上升"
  },
  "valuation_triangulation": {
    "pe_ttm": {"value": 52.3, "anchor": "AMD 48.7x"},
    "pe_forward": {"value": 45.2, "anchor": "歷史中位數"},
    "ev_sales": {"value": 28.5, "anchor": "AVGO 15x"},
    "p_fcf": {"value": 42.1, "anchor": "成長股框架"}
  },
  "sensitivity_matrix": {
    "eps_range": [3.0, 3.5, 4.0, 4.5],
    "pe_range": [35, 45, 55, 65],
    "price_matrix": [
      [105, 135, 165, 195],
      [122.5, 157.5, 192.5, 227.5],
      [140, 180, 220, 260],
      [157.5, 202.5, 247.5, 292.5]
    ]
  },
  "core_assumptions": {
    "base": {
      "revenue_cagr": 35,
      "gross_margin": 70,
      "opex_growth": 20,
      "tax_rate": 12,
      "share_dilution": 1.5
    },
    "bull": {
      "revenue_cagr": 50,
      "trigger": "雲端 Capex 前置 + 推理規模化"
    },
    "bear": {
      "revenue_cagr": 20,
      "trigger": "競爭加劇 + 供給過剩"
    }
  },
  "change_my_mind": {
    "invalidate_bull": [
      "毛利率指引 < 65%",
      "主要客戶轉單 ASIC",
      "交付延遲 > 2 季"
    ],
    "invalidate_bear": [
      "推理 TCO 大幅下降",
      "新產品週期啟動",
      "供給瓶頸持續"
    ]
  },
  "monitoring_dashboard": {
    "kpis": [
      {"name": "Gross Margin", "current": 70.1, "alert_below": 65, "alert_above": 75},
      {"name": "DC Revenue Growth", "current": 122, "alert_below": 50}
    ],
    "events": [
      {"date": "2026-01-08", "event": "NVDA 法說會", "impact": "high"}
    ],
    "market_signals": [
      {"name": "SMH 資金流", "status": "net_inflow", "trend": "accelerating"}
    ]
  },
  "catalyst_calendar": [
    {
      "date": "2026-01-06",
      "event": "AMD CES",
      "affected_kpi": "競爭定價",
      "bullish_signal": "MI400 延遲",
      "bearish_signal": "MI400 提前量產"
    }
  ]
}
```

---

## 通用規範

### 數字來源規則

1. **價格/漲跌**: 必須來自 FMP API（收盤價）
2. **估值倍數**: FMP 或手動計算（需標註）
3. **財務數據**: FMP（優先）或 SEC 10-Q/10-K
4. **成長率**: 需標註 TTM / QoQ / YoY
5. **新聞事件**: 需標註原始來源

### 引用密度規則

| 文章類型 | 最低引用數 | 必須包含 |
|----------|-----------|----------|
| Flash | 5 | 價格來源、主線新聞來源 |
| Earnings | 6 | SEC filing、分析師共識來源 |
| Deep Dive | 8 | SEC filing、FMP、公司發表 |

### 品質檢查 Checklist

- [ ] 所有價格與昨日收盤一致
- [ ] 漲跌幅全文一致（同 ticker 同數字）
- [ ] 倍數推算可驗證（價格 ÷ 倍數 = EPS）
- [ ] 三篇互相連結存在
- [ ] Paywall 上方內容自成完整段落
- [ ] 會員專屬有「決策工具」而非只是「更多文字」

---

## Ghost 發佈設定

### Post Access 對照表

| 文章 | visibility | 理由 |
|------|------------|------|
| Flash | `members` | 免費會員即可解鎖，用於獲客 |
| Earnings | `members` | 同上 |
| Deep Dive | `members` 或 `paid` | 可考慮付費限定 |

### Newsletter 發送策略

| 文章 | 是否發 Newsletter | Segment |
|------|------------------|---------|
| Flash | Yes | `all` |
| Earnings | No | - |
| Deep Dive | No | - |

### Paywall 位置規範

Paywall 必須放在「章節結束」位置，確保：
1. 免費區有完整價值（能回答「發生什麼事」）
2. 會員區有進階價值（能回答「該怎麼做」）
3. 分隔處不在段落中間

---

## 實作優先順序

### Phase 1: 資料補齊（1-2 天）
- [ ] 補齊 FMP 財務數據 API
- [ ] 補齊 Market Snapshot 數據
- [ ] 新增 news_items 多元化邏輯

### Phase 2: Schema 升級（2-3 天）
- [ ] 更新 Flash schema
- [ ] 更新 Earnings schema
- [ ] 更新 Deep Dive schema
- [ ] 對應 prompt 更新

### Phase 3: HTML 模板升級（1-2 天）
- [ ] Flash v4 模板
- [ ] Earnings v4 模板
- [ ] Deep Dive v4 模板

### Phase 4: 測試與調校（1-2 天）
- [ ] 端對端測試
- [ ] 會員牆測試（無痕 vs 登入）
- [ ] Newsletter 渲染測試
