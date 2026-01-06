# Quality Assurance Gates

## Overview

All posts must pass these quality gates before production publishing. Gates are enforced automatically by the pipeline and manually reviewable via `make qa-check`.

## Gate Summary

| Gate | Name | Severity | Auto-Block |
|------|------|----------|------------|
| G1 | Data Completeness | Critical | Yes |
| G2 | Numeric Integrity | Critical | Yes |
| G3 | Attribution Blocking | Critical | Yes |
| G4 | Consistency Check | High | Yes |
| G5 | Bilingual Verification | Medium | Warn |
| G6 | Render Smoke Test | High | Yes |

---

## G1: Data Completeness

**Purpose**: Ensure every referenced ticker has complete data.

### Requirements

For each ticker mentioned in the post:
- [ ] Price is present and numeric
- [ ] Change percentage is present
- [ ] Timestamp/date is present
- [ ] Source is identified (FMP, SEC, etc.)

### Implementation

```python
def check_data_completeness(post_json, research_pack):
    """
    Verify all tickers have required data fields.
    """
    required_fields = ['price', 'change_pct', 'timestamp']
    violations = []

    for ticker in extract_tickers(post_json):
        data = find_ticker_data(research_pack, ticker)
        if not data:
            violations.append(f"{ticker}: No data found")
            continue
        for field in required_fields:
            if field not in data or data[field] is None:
                violations.append(f"{ticker}: Missing {field}")

    return len(violations) == 0, violations
```

### Pass Criteria
- Zero violations

---

## G2: Numeric Integrity

**Purpose**: Every number in the output must trace to the input data.

### Allowed Number Sources

1. **Direct from research_pack**: Prices, percentages, dates
2. **Calculated with shown math**: P/E medians, target prices
3. **CSS/formatting**: Width percentages (33%, 100%)
4. **Small integers**: List numbers (1, 2, 3)

### Blocked Numbers

Numbers that appear in output but NOT in:
- `research_pack.json`
- Explicit calculation in post
- Standard formatting values

### Implementation

```python
def check_numeric_integrity(research_pack, draft_html, output_html):
    """
    Extract all numbers from output and verify against allowlist.
    """
    # Extract numbers from research pack
    allowed = extract_numbers(json.dumps(research_pack))

    # Add calculation-derived numbers (must be in post JSON)
    # Add safe formatting numbers
    allowed.update({'33%', '34%', '100%', '50%'})
    allowed.update({str(i) for i in range(1, 20)})

    # Extract numbers from output
    output_numbers = extract_numbers(output_html)

    # Find violations
    new_numbers = output_numbers - allowed

    return len(new_numbers) == 0, list(new_numbers)
```

### Pass Criteria
- Zero new numbers not in allowlist

---

## G3: Attribution Blocking

**Purpose**: Prevent unsourced sell-side institution citations.

### Blocked Institutions

```python
BLOCKED_ATTRIBUTIONS = [
    # US Investment Banks
    "Morgan Stanley", "Goldman Sachs", "Goldman",
    "JPMorgan", "JP Morgan", "Citi", "Citigroup",
    "Bank of America", "BofA", "Merrill Lynch",

    # European Banks
    "Barclays", "UBS", "Credit Suisse", "Deutsche Bank",
    "HSBC", "BNP Paribas", "Societe Generale",

    # Other Brokerages
    "Wells Fargo", "Jefferies", "Bernstein",
    "Evercore", "Cowen", "Piper Sandler",
    "Raymond James", "Wedbush", "Oppenheimer",
    "Stifel", "RBC Capital", "KeyBanc",

    # Asian Banks
    "Mizuho", "Nomura", "Macquarie", "CLSA",
    "Daiwa", "Samsung Securities",
]
```

### Allowed Attribution

- SEC filings: "根據 10-K 揭露..."
- Company statements: "管理層表示..."
- Market consensus: "市場共識預期..."
- Data providers: "FMP 數據顯示..."

### Implementation

```python
def check_attribution_blocking(text):
    """
    Scan for blocked institution names.
    """
    violations = []
    for institution in BLOCKED_ATTRIBUTIONS:
        pattern = rf'\b{re.escape(institution)}\b'
        if re.search(pattern, text, re.IGNORECASE):
            violations.append(institution)

    return len(violations) == 0, violations
```

### Pass Criteria
- Zero blocked institutions found

---

## G4: Consistency Check

**Purpose**: Same data point appears consistently throughout post.

### Checks

1. **Price consistency**: Same ticker shows same price everywhere
2. **Change consistency**: Same ticker shows same % change everywhere
3. **Date consistency**: Dates match throughout

### Implementation

```python
def check_consistency(post_html):
    """
    Find inconsistent data points for same ticker.
    """
    violations = []

    # Extract all price mentions per ticker
    prices_by_ticker = extract_prices_by_ticker(post_html)

    for ticker, prices in prices_by_ticker.items():
        unique_prices = set(prices)
        if len(unique_prices) > 1:
            violations.append(f"{ticker}: Multiple prices {unique_prices}")

    # Similar for percentages
    changes_by_ticker = extract_changes_by_ticker(post_html)
    for ticker, changes in changes_by_ticker.items():
        unique_changes = set(changes)
        if len(unique_changes) > 1:
            violations.append(f"{ticker}: Multiple changes {unique_changes}")

    return len(violations) == 0, violations
```

### Pass Criteria
- Zero inconsistencies

---

## G5: Bilingual Verification

**Purpose**: English summary doesn't contradict Chinese conclusion.

### Checks

1. **Direction alignment**: If ZH says "利多", EN shouldn't say "bearish"
2. **Number alignment**: Key numbers match in both languages
3. **Ticker alignment**: Same tickers mentioned as key

### Implementation

```python
def check_bilingual_consistency(post_json):
    """
    Verify EN summary aligns with ZH content.
    """
    en_summary = post_json.get('executive_summary', {}).get('en', '')
    zh_thesis = post_json.get('thesis', '')

    # Check sentiment alignment
    en_sentiment = analyze_sentiment(en_summary)
    zh_sentiment = analyze_sentiment(zh_thesis)

    if en_sentiment * zh_sentiment < 0:  # Opposite signs
        return False, ["Sentiment mismatch between EN and ZH"]

    # Check key tickers mentioned
    en_tickers = extract_tickers(en_summary)
    zh_tickers = extract_tickers(zh_thesis)

    if not en_tickers.intersection(zh_tickers):
        return False, ["No common tickers between EN and ZH"]

    return True, []
```

### Pass Criteria
- No sentiment contradiction
- At least one common ticker

---

## G6: Render Smoke Test

**Purpose**: Verify post renders correctly in Ghost.

### Checks

1. **Paywall divider**: `<!--members-only-->` present and in correct position
2. **Table rendering**: All tables have proper inline styles
3. **Link validity**: URLs are well-formed
4. **Image references**: No broken image links

### Implementation

```python
def check_render(post_html, post_slug):
    """
    Verify HTML will render correctly in Ghost.
    """
    violations = []

    # Check paywall divider
    if '<!--members-only-->' not in post_html:
        violations.append("Missing paywall divider")

    # Check tables have styles
    tables = re.findall(r'<table[^>]*>', post_html)
    for table in tables:
        if 'style=' not in table:
            violations.append("Table missing inline styles")

    # Check URLs
    urls = re.findall(r'href="([^"]+)"', post_html)
    for url in urls:
        if url.startswith('http') and not is_valid_url(url):
            violations.append(f"Invalid URL: {url}")

    return len(violations) == 0, violations
```

### Pass Criteria
- Paywall divider present
- All tables styled
- All URLs valid

---

## Pipeline Integration

### Pre-Publish Check

```python
def run_all_gates(research_pack, post_json, post_html):
    """
    Run all quality gates and return report.
    """
    report = {
        'overall_passed': True,
        'can_send_newsletter': True,
        'gates': {}
    }

    gates = [
        ('data_completeness', check_data_completeness),
        ('numeric_integrity', check_numeric_integrity),
        ('attribution_blocking', check_attribution_blocking),
        ('consistency', check_consistency),
        ('bilingual', check_bilingual_consistency),
        ('render', check_render),
    ]

    for gate_name, gate_func in gates:
        passed, violations = gate_func(...)
        report['gates'][gate_name] = {
            'passed': passed,
            'violations': violations
        }
        if not passed:
            report['overall_passed'] = False
            if gate_name in ['data_completeness', 'numeric_integrity', 'attribution_blocking']:
                report['can_send_newsletter'] = False

    return report
```

### Gate Override

For testing purposes ONLY:

```bash
# Skip gates (NOT for production)
python publish.py --skip-quality-gates

# Skip specific gate
python publish.py --skip-gate attribution_blocking
```

**WARNING**: Using `--skip-quality-gates` in production is prohibited.

---

## Manual Review Checklist

Before production send, human reviewer should verify:

- [ ] Thesis makes sense and is actionable
- [ ] Numbers look reasonable (no obvious errors)
- [ ] No awkward phrasing in Chinese
- [ ] English summary is professional
- [ ] Tables render well on mobile preview
- [ ] Paywall content is valuable enough for paid tier

---

## Metrics Tracking

Track gate performance over time:

```python
# Log to metrics
metrics.track('quality_gate_result', {
    'date': date,
    'post_type': post_type,
    'gate': gate_name,
    'passed': passed,
    'violation_count': len(violations)
})
```

Dashboard should show:
- Pass rate by gate
- Most common violations
- Trend over time
