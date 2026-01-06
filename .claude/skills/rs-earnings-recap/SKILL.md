# rs-earnings-recap (Post B: Earnings)

## Overview
Generate the **Earnings Reaction & Fair Value** analysis (Post B) - a valuation stress test and peer comparison framework for companies with upcoming or recent earnings.

## Trigger
- **Conditional**: Only runs when ANY of these conditions are met:
  1. A company in theme universe reported earnings yesterday
  2. Market cap > $10B AND price change > 5%
  3. Core holding (NVDA, AMD, AVGO, TSM, MSFT, GOOGL, AMZN, META) has upcoming earnings within 3 days
- Slug format: `{ticker}-earnings-{context}-{YYYY-MM-DD}-earnings`
- Example: `nvda-earnings-preview-2026-01-05-earnings`

## Input Requirements
- `edition_pack.json` containing:
  - `earnings_data{}` - EPS actual/estimate, revenue, guidance
  - `market_data{}` - Current price, P/E, gross margin
  - `peer_data[]` - Comparison tickers with same metrics
  - `valuation_anchors{}` - Historical multiples, peer medians

## Output Structure

### JSON Schema (postB.schema.json)
```json
{
  "title": "string (zh-TW)",
  "title_en": "string",
  "newsletter_subject": "string",
  "slug": "string (-earnings suffix required)",
  "tags": ["us-stocks", "earnings", "theme-*", "t-*", "#format-earnings"],
  "excerpt": "string",
  "meta": {
    "post_type": "earnings",
    "earnings_companies": ["TICKER"],
    "trigger_reason": "string"
  },
  "executive_summary": { "en": "string" },
  "earnings_scoreboard": [{
    "ticker", "quarter", "eps_actual", "eps_estimate",
    "revenue_actual", "revenue_estimate", "guidance_direction"
  }],
  "verdict": { "summary", "market_interpretation" },
  "market_reaction": {
    "what_market_heard", "surprise_elements", "concern_elements"
  },
  "guidance": {
    "next_quarter": { "revenue_consensus", "gross_margin_guidance" },
    "credibility_assessment", "management_tone"
  },
  "valuation": {
    "methodology": "同業 P/E 比較法 + 敏感度分析",
    "current_metrics": { "price", "pe_ttm", "gross_margin" },
    "scenarios": {
      "bear": { "target_price", "multiple", "rationale" },
      "base": { "target_price", "multiple", "rationale" },
      "bull": { "target_price", "multiple", "rationale" }
    },
    "fair_value_range": { "low", "mid", "high" }
  },
  "peer_comparison": {
    "peers": [{ "ticker", "name", "gross_margin", "pe_forward" }],
    "takeaways": ["string"],
    "premium_discount_rationale": "string"
  },
  "sources": [{ "name", "type" }]
}
```

### HTML Structure

#### PUBLIC
1. **Tag Pills** - Earnings, Ticker, Pre-call/Post-call
2. **Data Stamp**
3. **TODAY'S PACKAGE** - Links to Flash/Deep
4. **Chinese Executive Summary** (中文摘要)
5. **English Executive Summary**
6. **一句話結論**
7. **估值壓力測試表** (Valuation Stress Test Table)
   - Bear/Peer Median/Base/Bull scenarios
   - P/E, anchor source, target price, interpretation
8. **市場在聽什麼** (What Market Heard)
9. **CTA Block**

#### `<!--members-only-->`

#### MEMBERS-ONLY
10. **同業比較表** (Peer Snapshot)
    - Ticker, Price, P/E, Gross Margin, vs NVDA
11. **Takeaways**
12. **法說會觀察重點** (Earnings Call Watch Points)
13. **會後三情境解讀** (Post-call Playbook)
    - Beat + Strong Guide: What you'll hear, market reaction, next verification
    - In-line: ...
    - Miss or Weak Guide: ...
14. **Sources**
15. **Disclaimer**

## Valuation Calculation Rules

### TTM EPS Derivation
```
TTM EPS = Current Price / P/E TTM
Example: $188.85 / 52.3 = $3.61
```

### Scenario Target Prices
```
Target Price = TTM EPS × Scenario Multiple
Bear:  $3.61 × 35.2x = $127
Base:  $3.61 × 52.3x = $189
Bull:  $3.61 × 72.8x = $263
```

### Peer Median Calculation
```
Peer Median P/E = median([AMD 48.7x, AVGO 35.2x, QCOM 18.5x, ...])
Premium/Discount = (NVDA P/E - Peer Median) / Peer Median
```

## Post-call Playbook Template

| Scenario | What You'll Hear | Market Reaction | Next Steps (T+1 to T+14) |
|----------|------------------|-----------------|--------------------------|
| Beat + Strong | Delivery visibility extended, margin holds | Premium expansion, flows to 2nd order | Watch cloud capex, supply chain |
| In-line | Numbers meet, but tone conservative | Initial pop then fade | Watch order refill, competitor signals |
| Miss/Weak | Delivery delays, pricing pressure | Multiple compression | Watch if one-time; supply chain follow |

## Content Rules
- Same as Post A (data integrity, attribution, bilingual)
- Valuation scenarios MUST be mathematically consistent
- Peer comparison must include at least 3 competitors

## Quality Gates
1. `valuation_math` - Target prices = EPS × Multiple
2. `peer_consistency` - All peers have same metrics
3. `scenario_coverage` - Bear/Base/Bull all defined
4. `slug_format` - Ends with `-earnings`

## Example Output
See: `out/post_earnings_v2.json` and `out/post_earnings_v2.html`
