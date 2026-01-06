# rs-daily-news-impact (Post A: Flash)

## Overview
Generate the daily **Market News Impact Brief** (Post A / Flash) - a quick-read analysis of the most impactful market events from the past 24 hours, with sector/ticker implications and a 2-week watchlist.

## Trigger
- **Always runs** daily at 06:00 ET
- Slug format: `{topic}-{YYYY-MM-DD}-flash`
- Example: `ai-chips-ces-2026-01-05-flash`

## Input Requirements
- `edition_pack.json` containing:
  - `news_items[]` with headline, source, impact_score, affected_tickers
  - `market_data{}` with prices, changes, volumes for key tickers
  - `earnings_calendar[]` for upcoming catalysts
  - `theme_context{}` from themes.yml

## Output Structure

### JSON Schema (postA.schema.json)
```json
{
  "title": "string (zh-TW)",
  "title_en": "string",
  "newsletter_subject": "string (zh-TW, max 60 chars)",
  "slug": "string (-flash suffix required)",
  "tags": ["us-stocks", "daily-brief", "theme-*", "t-*", "#autogen", "#edition-postclose", "#format-flash"],
  "excerpt": "string (150-200 chars, zh-TW)",
  "meta": {
    "post_type": "flash",
    "edition": "postclose",
    "date": "YYYY-MM-DD",
    "quality_gates_passed": boolean
  },
  "executive_summary": { "en": "string (200-300 words)" },
  "thesis": "string (1-2 sentences, zh-TW)",
  "key_numbers": [{ "value", "label", "source" }],
  "tldr": ["string (5-7 bullets)"],
  "news_items": [{ "headline", "headline_zh", "source", "impact_score", ... }],
  "repricing_dashboard": [{ "variable", "why_important", "leading_signal", "direct_impact" }],
  "industry_impact": { "first_order": {}, "second_order": {} },
  "key_stocks": [{ "ticker", "price", "change_pct", "setup", "catalyst", "risk" }],
  "timeline": [{ "date", "event", "ticker", "importance" }],
  "contrarian_view": { "bear_case", "trigger_indicators" },
  "sources": [{ "name", "type" }],
  "headline_variants": { "zh": [], "en": [], "newsletter_subject": [] }
}
```

### HTML Structure (Public + Paywall)

#### PUBLIC (Free Preview)
1. **Tag Pills** - Daily Brief, Flash, Theme, Ticker
2. **Data Stamp** - "Data as of {date} US market close"
3. **TODAY'S PACKAGE** - Links to all 3 daily posts
4. **Chinese Executive Summary** (中文摘要) - 2-3 paragraphs
5. **English Executive Summary** - 200-300 words
6. **一句話結論** (Thesis)
7. **三個必記數字** (Key Numbers Box)
8. **TL;DR** - 5-7 bullets
9. **Repricing Dashboard** - Table of key variables
10. **CTA Block** - Dark box with member benefits + signup link

#### `<!--members-only-->`

#### MEMBERS-ONLY
11. **Industry Impact Map** - First-order/Second-order effects
12. **Key Stocks Analysis** - 3-8 tickers with setup/catalyst/risk
13. **Scenario Playbook** - Bull/Base/Bear conditions table
14. **Timeline** - Next 2 weeks catalysts
15. **Contrarian View** - Bear case + trigger indicators
16. **Sources**
17. **Disclaimer**

## Content Rules

### Language
- Primary: Traditional Chinese (zh-TW)
- English: Executive Summary only
- Use glossary from `rocketscreener/i18n/terms.py`

### Data Integrity (CRITICAL)
- ALL numbers must come from `edition_pack.json`
- No invented percentages, prices, or dates
- Every ticker must have verified price/change data

### Attribution
- NEVER cite sell-side institutions without SEC filing source
- Blocked list: Morgan Stanley, Goldman Sachs, JPMorgan, Citi, BofA, UBS, etc.
- Always link to primary sources

### Tone
- Scenario-based: Use "若...則..." (if...then...)
- NOT personalized advice: Never "你應該買/賣"
- Include contrarian view in every post

## Quality Gates (Must Pass)
1. `numbers_allowlist` - All numbers traceable
2. `attribution_blocking` - No unauthorized citations
3. `slug_format` - Ends with `-flash`
4. `bilingual_consistency` - EN/ZH conclusions match
5. `paywall_divider` - `<!--members-only-->` present

## Example Output
See: `out/post_flash_v2.json` and `out/post_flash_v2.html`

## Cross-Post Navigation
Post A links to:
- Post B (Earnings): `/nvda-earnings-preview-2026-01-05-earnings/`
- Post C (Deep Dive): `/nvda-deep-dive-2026-01-05-deep/`
