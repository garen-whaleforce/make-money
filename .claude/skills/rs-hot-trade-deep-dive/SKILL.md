# rs-hot-trade-deep-dive (Post C: Deep Dive)

## Overview
Generate a comprehensive **Deep Dive / Investment Memo** (Post C) - a full-stack analysis of a single ticker covering business model, moat, valuation, risks, and decision framework.

## Trigger
- **Always runs** daily at 06:00 ET
- **Stock Selection Logic**:
  1. Pool 1: Highest-impact ticker from Post A (news-driven)
  2. Pool 2: Trending ticker (volume surge, options flow, social mentions)
  3. Priority weighting by theme: AI Chips > Cloud > Networking > Security > Power > Nuclear > Defense > Space > Quantum > Crypto > Consumer > Healthcare
- Slug format: `{ticker}-deep-dive-{YYYY-MM-DD}-deep`
- Example: `nvda-deep-dive-2026-01-05-deep`

## Input Requirements
- `edition_pack.json` containing:
  - `primary_ticker` - Selected ticker for deep dive
  - `selection_reason` - Why this ticker was chosen
  - `company_profile{}` - Sector, industry, market cap
  - `financial_data{}` - Margins, revenue breakdown, cash flow
  - `valuation_data{}` - Current multiples, historical range
  - `peer_data[]` - Competitive comparison
  - `catalyst_calendar[]` - Upcoming events
  - `risk_factors[]` - Key risks with severity

## Output Structure

### JSON Schema (postC.schema.json)
```json
{
  "title": "string (zh-TW)",
  "title_en": "string",
  "slug": "string (-deep suffix required)",
  "tags": ["us-stocks", "deep-dive", "theme-*", "t-*", "#format-deep"],
  "meta": {
    "post_type": "deep",
    "primary_ticker": "TICKER",
    "selection_reason": "string",
    "theme": "string"
  },
  "executive_summary": { "en": "string (300-400 words)" },
  "ticker_profile": {
    "ticker", "name", "sector", "industry", "market_cap", "price", "change_1d"
  },
  "thesis": {
    "statement": "string (zh-TW)",
    "key_points": ["string"],
    "why_now": "string"
  },
  "anti_thesis": {
    "statement": "string",
    "key_points": ["string"]
  },
  "key_debate": {
    "bull_case": ["string"],
    "bear_case": ["string"],
    "resolution_signals": ["string"]
  },
  "key_numbers": [{
    "value", "label", "context", "source"
  }],
  "business_model": {
    "overview": "string",
    "revenue_streams": [{ "segment", "revenue_pct", "margin_profile" }],
    "moat": { "type": [], "description", "durability" },
    "competitive_position": "string",
    "key_customers": ["string"],
    "key_suppliers": ["string"]
  },
  "financial_drivers": {
    "revenue": { "growth_drivers": [] },
    "profitability": { "gross_margin", "gross_margin_trend" },
    "cash_flow": { "capital_allocation" },
    "balance_sheet": { "key_highlights": [] }
  },
  "valuation": {
    "methodology": "string",
    "current_valuation": { "pe_ttm", "gross_margin" },
    "fair_value_range": {
      "bear": { "price", "multiple", "rationale" },
      "base": { "price", "multiple", "rationale" },
      "bull": { "price", "multiple", "rationale" }
    },
    "sensitivity": [{ "multiple", "anchor", "implied_price", "interpretation" }]
  },
  "catalysts": {
    "near_term": [{ "event", "date", "potential_impact", "magnitude" }],
    "medium_term": [{ "event", "timeframe", "potential_impact" }],
    "long_term": [{ "theme", "thesis" }]
  },
  "risks": [{
    "risk", "category", "severity", "probability", "monitorable", "monitoring_signal"
  }],
  "peer_comparison": {
    "peers": [{ "ticker", "market_cap", "gross_margin", "pe_forward" }],
    "takeaways": ["string"],
    "premium_discount_explanation": "string"
  },
  "if_then_playbook": [{
    "if_signal": "string",
    "then_interpretation": "string",
    "next_verification": "string",
    "direct_impact": "string"
  }],
  "positioning": {
    "conditions": [{
      "scenario", "condition", "suggested_stance", "rationale"
    }],
    "disclaimer": "This is scenario-based analysis, not personalized investment advice."
  },
  "management_questions": ["string"],
  "sources": [{ "name", "type" }]
}
```

### HTML Structure

#### PUBLIC
1. **Tag Pills** - Deep Dive, Ticker, Theme
2. **Data Stamp**
3. **TODAY'S PACKAGE** - Links to Flash/Earnings
4. **Chinese Executive Summary** (中文摘要) - 3 paragraphs
5. **English Executive Summary** - 300-400 words
6. **Company Profile Card** - Ticker, Price, Change, Market Cap, P/E, Gross Margin
7. **怎麼讀這份 Deep Dive** (How to Read)
   - 3 minutes: Key Numbers + Valuation + If/Then
   - 15 minutes: Add Bull/Bear Debate + Risk List
   - Full read: Add Business Model + Management Questions
8. **投資命題** (Investment Thesis) - Blockquote + Why Now + Key Points
9. **反命題** (Anti-Thesis) - Bear case blockquote + Key Points
10. **CTA Block**

#### `<!--members-only-->`

#### MEMBERS-ONLY
11. **多空對決表** (Key Debate) - 2-column Bull/Bear table
12. **五個必記數字** (Key Numbers) - Formatted table
13. **商業模式** (Business Model)
    - Revenue structure table
    - Moat analysis box
14. **估值框架** (Valuation Framework)
    - Bear/Peer/Base/Bull scenario table
15. **If/Then 決策樹** - Formatted IF/THEN/NEXT table
16. **風險清單** (Risk List) - Severity + Monitoring indicators
17. **管理層提問清單** (Management Questions)
18. **Sources**
19. **Disclaimer**

## Moat Types (for `business_model.moat.type`)
- `network_effects` - Platform value increases with users
- `switching_costs` - High cost to change providers
- `intangible_assets` - Brand, patents, ecosystem
- `cost_advantages` - Scale or structural cost edge
- `efficient_scale` - Natural monopoly dynamics

## Risk Categories
- `business` - Operational, execution risks
- `competitive` - Market share, pricing pressure
- `macro` - Economic, regulatory, geopolitical
- `financial` - Balance sheet, liquidity
- `technology` - Disruption, obsolescence

## Content Rules
- Investment Memo format: Thesis/Anti-Thesis/Debate structure
- 5 Key Numbers: Each must have source and context
- If/Then Playbook: At least 4 condition-action pairs
- Risk monitoring: Each risk must have a monitorable signal
- Scenario-based positioning: Add/Hold/Reduce per scenario

## Quality Gates
1. `thesis_antithesis` - Both sides presented
2. `key_numbers_sourced` - All 5 numbers have sources
3. `if_then_complete` - At least 4 playbook entries
4. `risks_monitorable` - Each risk has monitoring signal
5. `slug_format` - Ends with `-deep`

## Example Output
See: `out/post_deep_v2.json` and `out/post_deep_v2.html`
