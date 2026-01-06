# rs-bilingual-editor

## Overview
Quality control skill for ensuring bilingual consistency between Traditional Chinese (zh-TW) and English content across all three post types.

## When to Invoke
- After any post generation (A, B, or C)
- Before quality gates
- As part of the enhancement pipeline

## Input
- Draft post JSON with both `title`, `title_en`, `executive_summary.en`, and Chinese body content

## Checks Performed

### 1. Language Detection
- Verify primary content is zh-TW (not zh-CN)
- Use Traditional Chinese characters: 資料、軟體、網路 (NOT 数据、软件、网络)

### 2. Terminology Consistency
All terms must follow the glossary in `rocketscreener/i18n/terms.py`:

| English | Traditional Chinese | Notes |
|---------|---------------------|-------|
| Inference | 推理 | NOT 推斷 |
| Valuation | 估值 | NOT 評價 |
| Gross Margin | 毛利率 | |
| Premium | 溢價 | |
| Discount | 折價 | |
| Guidance | 指引 | NOT 引導 |
| Catalyst | 催化劑 | |
| Moat | 護城河 | |
| Bear Case | 空頭情境/悲觀情境 | |
| Bull Case | 多頭情境/樂觀情境 | |
| Earnings Call | 法說會 | NOT 財報電話會 |
| Quarterly Report | 季報 | |
| Revenue | 營收 | NOT 收入 |
| Data Center | 資料中心 | NOT 數據中心 |
| Paywall | 付費牆/會員牆 | |
| Executive Summary | 執行摘要 | |

### 3. Ticker Format Rules
- Always UPPERCASE: NVDA, AMD, AVGO
- In Chinese text: keep English ticker, e.g., "NVDA 上漲 4.2%"
- Never translate ticker names

### 4. Number Format
- English: Use comma separators (1,000,000)
- Chinese: Can use 萬/億 (4.6 兆, 230 億)
- Percentages: Same in both (4.2%, +40%)
- Currency: $188.85 (keep USD symbol)

### 5. Semantic Consistency Check
**CRITICAL**: English and Chinese conclusions must align

❌ Bad:
- EN: "We see upside potential to $263"
- ZH: "我們認為估值偏高，可能回落"

✅ Good:
- EN: "Bull case requires 73x P/E to reach $263"
- ZH: "樂觀情境需要 73x P/E 才能支撐 $263 目標"

### 6. Section Mapping
| English Section | Chinese Section |
|-----------------|-----------------|
| Executive Summary | 英文執行摘要 |
| Chinese Summary | 中文摘要 |
| Investment Thesis | 投資命題 |
| Anti-Thesis | 反命題 |
| Key Debate | 多空對決 |
| Valuation | 估值框架 |
| Risk List | 風險清單 |
| If/Then Playbook | If/Then 決策樹 |
| Sources | 資料來源 |

## Output
- `bilingual_check_passed: boolean`
- `terminology_violations: []` - Terms not matching glossary
- `semantic_inconsistencies: []` - EN/ZH conclusion mismatches
- `suggested_fixes: []` - Recommended corrections

## Glossary File Location
Primary glossary: `rocketscreener/i18n/terms.py`

### Adding New Terms
When encountering a new financial term:
1. Check if it exists in glossary
2. If not, propose addition with:
   - English term
   - Traditional Chinese translation
   - Context/usage notes
3. Flag for human review before adding

## Integration with Other Skills
- Runs AFTER: `rs-daily-news-impact`, `rs-earnings-recap`, `rs-hot-trade-deep-dive`
- Runs BEFORE: `rs-source-of-truth-and-factcheck`
- Output feeds into quality gates

## Example Violations

### Terminology Violation
```json
{
  "type": "terminology",
  "found": "數據中心",
  "expected": "資料中心",
  "location": "business_model.overview",
  "severity": "medium"
}
```

### Semantic Inconsistency
```json
{
  "type": "semantic",
  "en_conclusion": "bullish outlook with $263 target",
  "zh_conclusion": "建議觀望，等待更多確認",
  "severity": "high",
  "fix_required": true
}
```
