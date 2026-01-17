# Daily Deep Brief - Project Constitution (v4.3)

## Overview

This project generates **3 daily US stock research publications** targeting Taiwan-based investors interested in US equities. Output is published to Ghost CMS with paywall support.

## Daily Output Schedule

| Post | Name | Trigger | Timing |
|------|------|---------|--------|
| **A** | Market News Impact Brief | Always | 06:00 ET daily |
| **B** | Earnings Reaction & Fair Value | 與 Deep Dive 連動（分析同一 ticker 的最近財報） | 06:00 ET daily |
| **C** | Deep Dive | Always | 06:00 ET daily |

## Edition Coherence (v4.3 - 三篇連貫性)

所有三篇文章共享同一個主題和 ticker：

```
Flash (Post A) → Earnings (Post B) → Deep Dive (Post C)
     ↓                ↓                    ↓
  primary_theme   deep_dive_ticker    deep_dive_ticker
```

- **Post A (Flash)**: 以 `primary_theme` 為主軸，聚焦 `deep_dive_ticker` 相關新聞
- **Post B (Earnings)**: 分析 `deep_dive_ticker` 的**最近已發布財報**（非未來財報）
- **Post C (Deep Dive)**: 對 `deep_dive_ticker` 進行完整投資分析

**Post B 觸發條件**：
1. 必須有 `recent_earnings` 資料
2. 財報日期在 180 天內（可分析上一季財報）
3. `meta.trigger_reason` = `"deep_dive_ticker_recent_earnings"`

## Core Principles

### 1. Data Integrity (CRITICAL)

- **NEVER hallucinate numbers** - all prices, percentages, ratios, dates MUST come from `edition_pack.json`
- **NEVER cite sell-side institutions** without actual source documents (blocked list in `enhance_post.py`)
- **ALWAYS include sources** with links for every factual claim
- Numbers in output must pass `numbers_allowlist` quality gate

### 2. Language Strategy

- **Primary**: Traditional Chinese (zh-TW) for Taiwan audience
- **Secondary**: English Executive Summary (200-300 words) at top of each post
- **Terms**: Use `rocketscreener/i18n/terms.py` for consistent terminology

### 3. Content Positioning

- **NOT** personalized investment advice
- **IS** scenario-based analysis with conditions
- Use phrases like "若...則..." (if...then...) instead of "應該買/賣"
- Always include contrarian view and risk factors

## Theme Universe (12 Sectors)

See `themes.yml` for full configuration. Priority themes:

1. AI Semiconductors (NVDA, AMD, AVGO, TSM, ASML)
2. AI Cloud Infrastructure (MSFT, GOOGL, AMZN, META)
3. AI Networking (MRVL, CRDO, ALAB)
4. AI Security (CRWD, PANW, FTNT, ZS)
5. Power & Grid (CEG, VST, NEE)
6. Nuclear (OKLO, NNE, SMR)
7. Drones & Defense (PLTR, AXON, ASTS)
8. Space (RKLB, LUNR)
9. Quantum (IONQ, RGTI)
10. Crypto (COIN, MSTR, MARA, RIOT)
11. Consumer Tech (AAPL, TSLA)
12. Healthcare AI (emerging)

## Post Structure Requirements

### Public Preview (FREE - visible to all)

- 1-sentence thesis
- "3 Key Numbers" visual box
- TL;DR bullets (5-7 items)
- Impact summary table
- CTA to subscribe

### Paywall Divider

Insert `<!--members-only-->` comment in HTML

### Members-Only Content

- Full analysis, valuation, peer comparisons
- Scenario-based positioning (Base/Bull/Bear)
- Watchlist with verification signals
- Complete source citations

## Slug Naming Convention

```
{base_slug}-{type}

Examples:
nvda-ces-2026-01-05-flash    (Post A)
nvda-ces-2026-01-05-earnings (Post B)
nvda-ces-2026-01-05-deep     (Post C)
```

## Ghost Publishing Rules

### Newsletter Strategy

| Mode | Newsletter | Segment | Use Case |
|------|------------|---------|----------|
| Test | daily-brief-test | label:internal | Internal QA |
| Production | daily-brief | status:free | Free tier |
| Production | daily-brief | status:-free | Paid only |

### Safety Gates

1. **Quality Report Required**: `out/quality_report.json` must exist and pass
2. **Enhanced Gate**: Posts with `meta.enhanced=true` must have `quality_gates_passed=true`
3. **High-Risk Segment**: `all`, `status:free`, `status:-free` require `--confirm-high-risk`
4. **Newsletter Allowlist**: Must be in `GHOST_NEWSLETTER_ALLOWLIST` env var

## File Structure

```
out/
├── edition_pack.json       # Single source of truth (v4.3)
├── post_flash.json/html    # Post A output
├── post_earnings.json/html # Post B output (if triggered)
├── post_deep.json/html     # Post C output
├── quality_report.json     # QA gate results
└── publish_result.json     # Ghost API response

schemas/
├── research_pack.schema.json
├── postA.schema.json
├── postB.schema.json
└── postC.schema.json

prompts/
├── postA.prompt.md
├── postB.prompt.md
└── postC.prompt.md

config/
├── runtime.yaml            # Runtime configuration
└── ghost.yml               # Ghost publishing rules
```

## Quality Gates (Must Pass Before Production Send)

1. **Data Completeness**: Every ticker has price/change/timestamp
2. **Numeric Integrity**: All numbers traceable to edition_pack
3. **Attribution Block**: No sell-side institution citations without source
4. **Consistency**: Same ticker shows same % change throughout post
5. **Bilingual Check**: EN summary doesn't contradict ZH conclusion
6. **Render Test**: Paywall divider renders correctly in Ghost
7. **Edition Coherence (v4.3)**: All three posts analyze the same `deep_dive_ticker`

## Command Reference

```bash
# Generate all posts
make generate-daily

# Test mode (internal only)
make publish-test

# Production (with confirmation)
make publish-prod

# Single post types
make generate-flash
make generate-earnings
make generate-deep
```

## Data Sources

| Source | API | Purpose |
|--------|-----|---------|
| FMP | Premium | Prices, fundamentals, earnings calendar |
| SEC EDGAR | Free | 10-K, 10-Q, 8-K filings |
| Alpha Vantage | Free tier | Technical indicators |
| Google News | Scrape | News headlines |
| Ghost | Admin API | Publishing |
| LiteLLM Proxy | Internal | LLM calls |

## Publish Sequence

發布順序（影響 cross-link 可用性）：

1. **Post B (Earnings)** → 先發布，無 email
2. **Post C (Deep Dive)** → 第二發布，無 email
3. **Post A (Flash)** → 最後發布，**發送 email**（包含 B & C 的連結）

## Forbidden Actions

1. **NEVER** publish to `segment=all` without explicit confirmation
2. **NEVER** include numbers not in edition_pack
3. **NEVER** cite "Morgan Stanley says..." without SEC filing source
4. **NEVER** give personalized advice ("you should buy X")
5. **NEVER** skip quality gates for production sends
6. **NEVER** use same slug for different post types
7. **NEVER** analyze different tickers across Flash/Earnings/Deep in the same edition

## Contact

- Ghost Site: https://rocket-screener.ghost.io
- Admin: Ghost Admin API via JWT
