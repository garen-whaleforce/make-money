# Quality Enforcement Rules (F1)

以下品質規則必須嚴格遵守。違反任何一條規則將導致輸出被拒絕。

## 數據完整性規則

### Rule 1: 數字可追溯性 (Number Traceability)
- ✅ 允許: 所有數字必須來自 `research_pack` 中的資料
- ❌ 禁止: 杜撰任何價格、百分比、日期、財務數據
- 範例:
  - 正確: "NVDA 收盤價 $142.50 (+2.3%)" ← 必須與 research_pack 中的數據完全一致
  - 錯誤: "NVDA 預計將在未來 12 個月上漲 30%" ← 未提供來源的預測

### Rule 2: 來源可驗證性 (Source Verifiability)
- ✅ 允許: 引用 SEC 文件、公司財報、官方新聞稿
- ❌ 禁止: 引用投行報告（除非有 SEC 文件佐證）
- 黑名單機構: Morgan Stanley, Goldman Sachs, JPMorgan, Citi, Bank of America, UBS, Credit Suisse, Deutsche Bank, Barclays, Wells Fargo

### Rule 3: 欄位完整性 (Field Completeness)
- earnings_scoreboard 的 eps_estimate, revenue_estimate 不可為 null
- key_numbers 必須恰好有 3 個項目
- repricing_dashboard 至少要有 3 個變數
- sources 的關鍵類型 (news, sec_filing) 必須有 URL

## 內容一致性規則

### Rule 4: 主題一致性 (Topic Integrity)
- Deep Dive 只能討論目標公司及其直接競爭對手
- 禁止混入無關公司（串稿檢測）
- NVDA 文章禁止出現: Grab, MongoDB, Zscaler, Bitcoin mining

### Rule 5: 自我一致性 (Self-Consistency)
- 如果提供估值表，不可同時聲明「資料不足」
- 同一 ticker 在文章中的漲跌幅必須一致
- repricing_dashboard 提到的 ticker 必須出現在 key_stocks 或 news_items 中

### Rule 6: 語言使用規則 (Language Rules)
- 主體內容使用繁體中文 (zh-TW)
- Executive Summary 使用英文 (200-300 字)
- 避免使用「建議」、「應該買/賣」等投資建議用語
- 使用條件式語言: 「若...則...」、「在 Y 情境下...」

## 結構規則

### Rule 7: Paywall 結構
- 必須在適當位置插入 `<!--members-only-->` 標記
- 免費區域: 摘要、關鍵數字、TL;DR (約 30 秒閱讀)
- 會員區域: 完整分析、估值、觀察清單 (5-7 分鐘閱讀)

### Rule 8: 輸出格式
- JSON 輸出必須符合對應的 schema
- slug 必須符合命名規則 (postA: -flash, postB: -earnings, postC: -deep)
- tags 必須包含必要標籤 (daily-brief, earnings 等)

## 品質 Checklist

在輸出前，請自我檢查以下項目：

```
□ 所有數字都可追溯到 research_pack
□ 沒有引用投行報告
□ 關鍵欄位沒有 null 值
□ 沒有內容污染（串稿）
□ 沒有自我矛盾
□ 使用條件式語言而非投資建議
□ Paywall 標記位置正確
□ JSON 格式符合 schema
```

如果任何項目未通過，請修正後再輸出。
