# rs-source-of-truth-and-factcheck

## Overview
Quality assurance skill that enforces data integrity, numeric provenance, and attribution rules across all posts. This is the **CRITICAL GATE** that prevents hallucinated numbers and unauthorized citations.

## Core Principle
> **NEVER hallucinate numbers** - all prices, percentages, ratios, dates MUST come from `edition_pack.json`

## When to Invoke
- After post generation, before publishing
- As the final quality gate before Ghost publish
- Mandatory for all MODE=prod publishes

## Input Requirements
- `edition_pack.json` - The single source of truth
- `post_*.json` - Generated post to validate
- `post_*.html` - HTML to validate

## Checks Performed

### 1. Numbers Allowlist (CRITICAL)
Every number in the post must be traceable to `edition_pack.json`.

#### Extractable Number Types
- Prices: `$188.85`, `188.85`
- Percentages: `4.2%`, `+40%`, `-15%`
- Ratios: `52.3x`, `2.5x`
- Market caps: `$4.6T`, `$230B`, `$870B`
- Dates: `1/6`, `1/8`, `2026-01-05`
- Counts: `83%`, `12%`, `3%` (revenue breakdown)

#### Validation Process
```python
def check_numbers_allowlist(post, edition_pack):
    extracted = extract_numbers(post.html)
    allowed = flatten_numbers(edition_pack)
    violations = []

    for num in extracted:
        if num.value not in allowed:
            violations.append({
                "number": num.value,
                "context": num.surrounding_text,
                "location": num.element_path
            })

    return {
        "passed": len(violations) == 0,
        "violations": violations
    }
```

#### Allowed Computed Numbers
Some numbers are derived but acceptable:
- Peer median P/E: Computed from peer list
- Target prices: EPS × Multiple
- Premium percentage: (Subject P/E - Peer Median) / Peer Median

Document computation in `computation_log[]`:
```json
{
  "computed_value": "41.95x",
  "formula": "median([48.7, 35.2, 18.5])",
  "inputs": ["AMD P/E", "AVGO P/E", "QCOM P/E"],
  "input_sources": ["edition_pack.peers"]
}
```

### 2. Attribution Blocking (CRITICAL)
NEVER cite sell-side institutions without actual SEC filing or primary source.

#### Blocked Institutions
```python
BLOCKED_INSTITUTIONS = [
    "Morgan Stanley",
    "Goldman Sachs",
    "JPMorgan",
    "JP Morgan",
    "Citi",
    "Citigroup",
    "Bank of America",
    "BofA",
    "UBS",
    "Deutsche Bank",
    "Credit Suisse",
    "Barclays",
    "HSBC",
    "Wells Fargo",
    "RBC",
    "Jefferies",
    "Piper Sandler",
    "Raymond James",
    "Wedbush",
    "Needham",
    "Bernstein",
    "Cowen",
    "Oppenheimer",
    "KeyBanc",
    "Stifel"
]
```

#### Violation Examples
❌ "Morgan Stanley expects NVDA to reach $300"
❌ "According to Goldman Sachs analysts..."
❌ "Citi maintains buy rating with $250 target"

#### Acceptable Attributions
✅ "According to NVDA's Q3 10-Q filing..."
✅ "CEO Jensen Huang stated in CES keynote..."
✅ "AWS announced in their blog post..."
✅ "Per FMP API data as of 2026-01-05..."

### 3. Ticker Consistency Check
Same ticker must show same data throughout the post.

```python
def check_ticker_consistency(post):
    ticker_mentions = extract_ticker_mentions(post)
    inconsistencies = []

    for ticker, mentions in ticker_mentions.items():
        prices = set(m.price for m in mentions if m.price)
        changes = set(m.change for m in mentions if m.change)

        if len(prices) > 1:
            inconsistencies.append({
                "ticker": ticker,
                "field": "price",
                "values_found": list(prices)
            })

    return inconsistencies
```

### 4. Timezone Consistency
All times must be in Eastern Time (America/New_York).

#### Validation
- Market data: "as of YYYY-MM-DD US market close"
- Event dates: Use ET timezone
- Pre-market/After-hours: Label explicitly

### 5. Date Freshness
- `edition_pack.json` must be from today or yesterday
- All market data timestamps must be within 24 hours
- Stale data = quality gate failure

### 6. Source Completeness
Every post must have:
- At least 2 data sources
- At least 1 primary source (company announcements, SEC filings)
- Data sources explicitly listed (FMP, Alpha Vantage, etc.)

## Output Format

```json
{
  "quality_gates_passed": boolean,
  "gates": {
    "numbers_allowlist": {
      "passed": boolean,
      "total_numbers": 45,
      "verified": 45,
      "violations": []
    },
    "attribution_blocking": {
      "passed": boolean,
      "violations": []
    },
    "ticker_consistency": {
      "passed": boolean,
      "inconsistencies": []
    },
    "timezone_consistency": {
      "passed": boolean,
      "timezone": "America/New_York"
    },
    "data_freshness": {
      "passed": boolean,
      "pack_date": "2026-01-05",
      "check_date": "2026-01-06"
    },
    "source_completeness": {
      "passed": boolean,
      "sources_count": 3,
      "has_primary": true
    }
  },
  "can_publish": boolean,
  "can_send_newsletter": boolean,
  "recommended_action": "publish" | "draft" | "block",
  "blocking_issues": []
}
```

## Action Matrix

| Gate Result | can_publish | can_send_newsletter | Recommended Action |
|-------------|-------------|---------------------|-------------------|
| All passed | true | true | publish |
| Minor violations (< 3) | true | false | publish (no email) |
| Major violations | false | false | draft only |
| Critical violations | false | false | block |

## Critical Violations (Block Publish)
- Any number not in allowlist AND not computable
- Any blocked institution citation
- Ticker shows conflicting prices
- Data older than 48 hours

## Integration
- Runs AFTER: All post generation skills, `rs-bilingual-editor`
- Runs BEFORE: `rs-ghost-publisher`
- If fails: Block `publish-send`, allow `draft` only

## Files

### Rules Configuration
`config/quality_rules.yaml`:
```yaml
numbers:
  require_source: true
  allow_computed: true
  computation_log_required: true

attribution:
  blocked_institutions: [...] # See list above
  require_primary_source: true

freshness:
  max_age_hours: 48
  timezone: "America/New_York"
```

### Implementation
- `src/quality/quality_gate.py` - Main gate logic
- `scripts/enhance_post.py` - Number extraction
