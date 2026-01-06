# FMP API Endpoints Reference

> Base URL: `https://financialmodelingprep.com/stable`
>
> Generated: 2025-11-16
>
> All endpoints are HTTP GET. Append `?apikey=YOUR_API_KEY` and your query parameters as needed.

## Company Search

| Endpoint | Description |
|----------|-------------|
| `search-symbol` | Search by symbol |
| `search-name` | Search by company name |
| `search-cik` | Search by CIK |
| `search-cusip` | Search by CUSIP |
| `search-isin` | Search by ISIN |
| `company-screener` | Company screener |
| `search-exchange-variants` | Search exchange variants |

## Stock Directory

| Endpoint | Description |
|----------|-------------|
| `stock-list` | Full stock list |
| `financial-statement-symbol-list` | Symbols with financial statements |
| `cik-list` | CIK list |
| `symbol-change` | Symbol changes |
| `etf-list` | ETF list |
| `actively-trading-list` | Actively trading stocks |
| `earnings-transcript-list` | Earnings transcript list |
| `available-exchanges` | Available exchanges |
| `available-sectors` | Available sectors |
| `available-industries` | Available industries |
| `available-countries` | Available countries |

## Company Information

| Endpoint | Description |
|----------|-------------|
| `profile` | Company profile |
| `profile-cik` | Profile by CIK |
| `company-notes` | Company notes |
| `stock-peers` | Stock peers |
| `delisted-companies` | Delisted companies |
| `employee-count` | Employee count |
| `historical-employee-count` | Historical employee count |
| `market-capitalization` | Market cap |
| `market-capitalization-batch` | Batch market cap |
| `historical-market-capitalization` | Historical market cap |
| `shares-float` | Shares float |
| `shares-float-all` | All shares float |
| `mergers-acquisitions-latest` | Latest M&A |
| `mergers-acquisitions-search` | M&A search |
| `key-executives` | Key executives |
| `governance-executive-compensation` | Executive compensation |
| `executive-compensation-benchmark` | Compensation benchmark |

## Quotes

| Endpoint | Description |
|----------|-------------|
| `quote` | Real-time quote |
| `quote-short` | Short quote |
| `aftermarket-trade` | After-market trade |
| `aftermarket-quote` | After-market quote |
| `stock-price-change` | Stock price change |
| `batch-quote` | Batch quotes |
| `batch-quote-short` | Batch short quotes |
| `batch-aftermarket-trade` | Batch after-market trades |
| `batch-aftermarket-quote` | Batch after-market quotes |
| `batch-exchange-quote` | Batch exchange quotes |
| `batch-mutualfund-quotes` | Batch mutual fund quotes |
| `batch-etf-quotes` | Batch ETF quotes |
| `batch-commodity-quotes` | Batch commodity quotes |
| `batch-crypto-quotes` | Batch crypto quotes |
| `batch-forex-quotes` | Batch forex quotes |
| `batch-index-quotes` | Batch index quotes |

## Financial Statements

| Endpoint | Description |
|----------|-------------|
| `income-statement` | Income statement |
| `balance-sheet-statement` | Balance sheet |
| `cash-flow-statement` | Cash flow statement |
| `latest-financial-statements` | Latest financials |
| `income-statement-ttm` | Income statement TTM |
| `balance-sheet-statement-ttm` | Balance sheet TTM |
| `cash-flow-statement-ttm` | Cash flow TTM |
| `key-metrics` | Key metrics |
| `ratios` | Financial ratios |
| `key-metrics-ttm` | Key metrics TTM |
| `ratios-ttm` | Ratios TTM |
| `financial-scores` | Financial scores |
| `owner-earnings` | Owner earnings |
| `enterprise-values` | Enterprise values |
| `income-statement-growth` | Income statement growth |
| `balance-sheet-statement-growth` | Balance sheet growth |
| `cash-flow-statement-growth` | Cash flow growth |
| `financial-growth` | Financial growth |
| `financial-reports-dates` | Financial report dates |
| `financial-reports-json` | Financial reports (JSON) |
| `financial-reports-xlsx` | Financial reports (XLSX) |
| `revenue-product-segmentation` | Revenue by product |
| `revenue-geographic-segmentation` | Revenue by geography |
| `income-statement-as-reported` | Income statement as reported |
| `balance-sheet-statement-as-reported` | Balance sheet as reported |
| `cash-flow-statement-as-reported` | Cash flow as reported |
| `financial-statement-full-as-reported` | Full financials as reported |

## Charts (Historical Price)

| Endpoint | Description |
|----------|-------------|
| `historical-price-eod/light` | EOD light |
| `historical-price-eod/full` | EOD full |
| `historical-price-eod/non-split-adjusted` | EOD non-split adjusted |
| `historical-price-eod/dividend-adjusted` | EOD dividend adjusted |
| `historical-chart/1min` | 1-minute chart |
| `historical-chart/5min` | 5-minute chart |
| `historical-chart/15min` | 15-minute chart |
| `historical-chart/30min` | 30-minute chart |
| `historical-chart/1hour` | 1-hour chart |
| `historical-chart/4hour` | 4-hour chart |

## Economics

| Endpoint | Description |
|----------|-------------|
| `treasury-rates` | Treasury rates |
| `economic-indicators` | Economic indicators |
| `economic-calendar` | Economic calendar |
| `market-risk-premium` | Market risk premium |

## Earnings, Dividends & Splits

| Endpoint | Description |
|----------|-------------|
| `dividends` | Dividends |
| `dividends-calendar` | Dividends calendar |
| `earnings` | Earnings |
| `earnings-calendar` | Earnings calendar |
| `ipos-calendar` | IPO calendar |
| `ipos-disclosure` | IPO disclosure |
| `ipos-prospectus` | IPO prospectus |
| `splits` | Stock splits |
| `splits-calendar` | Splits calendar |

## Earnings Transcripts

| Endpoint | Description |
|----------|-------------|
| `earning-call-transcript-latest` | Latest earnings transcript |
| `earning-call-transcript` | Earnings call transcript |
| `earning-call-transcript-dates` | Transcript dates |
| `earnings-transcript-list` | Transcript list |

## News

| Endpoint | Description |
|----------|-------------|
| `fmp-articles` | FMP articles |
| `news/general-latest` | Latest general news |
| `news/press-releases-latest` | Latest press releases |
| `news/stock-latest` | Latest stock news |
| `news/crypto-latest` | Latest crypto news |
| `news/forex-latest` | Latest forex news |
| `news/press-releases` | Press releases |
| `news/stock` | Stock news |
| `news/crypto` | Crypto news |
| `news/forex` | Forex news |

## Form 13F (Institutional Ownership)

| Endpoint | Description |
|----------|-------------|
| `institutional-ownership/latest` | Latest 13F filings |
| `institutional-ownership/extract` | Extract 13F data |
| `institutional-ownership/dates` | 13F filing dates |
| `institutional-ownership/extract-analytics/holder` | Holder analytics |
| `institutional-ownership/holder-performance-summary` | Holder performance |
| `institutional-ownership/holder-industry-breakdown` | Holder industry breakdown |
| `institutional-ownership/symbol-positions-summary` | Symbol positions summary |
| `institutional-ownership/industry-summary` | Industry summary |

## Analyst

| Endpoint | Description |
|----------|-------------|
| `analyst-estimates` | Analyst estimates |
| `ratings-snapshot` | Ratings snapshot |
| `ratings-historical` | Historical ratings |
| `price-target-summary` | Price target summary |
| `price-target-consensus` | Price target consensus |
| `price-target-news` | Price target news |
| `price-target-latest-news` | Latest price target news |
| `grades` | Analyst grades |
| `grades-historical` | Historical grades |
| `grades-consensus` | Grades consensus |
| `grades-news` | Grades news |
| `grades-latest-news` | Latest grades news |

## Market Performance

| Endpoint | Description |
|----------|-------------|
| `sector-performance-snapshot` | Sector performance |
| `industry-performance-snapshot` | Industry performance |
| `historical-sector-performance` | Historical sector performance |
| `historical-industry-performance` | Historical industry performance |
| `sector-pe-snapshot` | Sector P/E |
| `industry-pe-snapshot` | Industry P/E |
| `historical-sector-pe` | Historical sector P/E |
| `historical-industry-pe` | Historical industry P/E |
| `biggest-gainers` | Biggest gainers |
| `biggest-losers` | Biggest losers |
| `most-actives` | Most active stocks |

## Technical Indicators

| Endpoint | Description |
|----------|-------------|
| `technical-indicators/sma` | Simple Moving Average |
| `technical-indicators/ema` | Exponential Moving Average |
| `technical-indicators/wma` | Weighted Moving Average |
| `technical-indicators/dema` | Double EMA |
| `technical-indicators/tema` | Triple EMA |
| `technical-indicators/rsi` | Relative Strength Index |
| `technical-indicators/standarddeviation` | Standard Deviation |
| `technical-indicators/williams` | Williams %R |
| `technical-indicators/adx` | Average Directional Index |

## ETF and Funds

| Endpoint | Description |
|----------|-------------|
| `etf/holdings` | ETF holdings |
| `etf/info` | ETF info |
| `etf/country-weightings` | ETF country weightings |
| `etf/asset-exposure` | ETF asset exposure |
| `etf/sector-weightings` | ETF sector weightings |
| `funds/disclosure-holders-latest` | Latest fund holders |
| `funds/disclosure` | Fund disclosure |
| `funds/disclosure-holders-search` | Search fund holders |
| `funds/disclosure-dates` | Fund disclosure dates |

## SEC Filings

| Endpoint | Description |
|----------|-------------|
| `sec-filings-8k` | 8-K filings |
| `sec-filings-financials` | Financial filings |
| `sec-filings-search/form-type` | Search by form type |
| `sec-filings-search/symbol` | Search by symbol |
| `sec-filings-search/cik` | Search by CIK |
| `sec-filings-company-search/name` | Search company by name |
| `sec-filings-company-search/symbol` | Search company by symbol |
| `sec-profile` | SEC profile |
| `standard-industrial-classification-list` | SIC list |
| `industry-classification-search` | Industry classification search |
| `all-industry-classification` | All industry classifications |

## Insider Trades

| Endpoint | Description |
|----------|-------------|
| `insider-trading/latest` | Latest insider trades |
| `insider-trading/search` | Insider trading search |
| `insider-trading/reporting-name` | Search by reporting name |
| `insider-trading-transaction-type` | Transaction types |
| `insider-trading/statistics` | Insider trading statistics |
| `acquisition-of-beneficial-ownership` | Beneficial ownership |

## Indexes

| Endpoint | Description |
|----------|-------------|
| `index-list` | Index list |
| `sp500-constituent` | S&P 500 constituents |
| `nasdaq-constituent` | NASDAQ constituents |
| `dowjones-constituent` | Dow Jones constituents |
| `historical-sp500-constituent` | Historical S&P 500 |
| `historical-nasdaq-constituent` | Historical NASDAQ |
| `historical-dowjones-constituent` | Historical Dow Jones |

## Market Hours

| Endpoint | Description |
|----------|-------------|
| `exchange-market-hours` | Exchange market hours |
| `holidays-by-exchange` | Holidays by exchange |
| `all-exchange-market-hours` | All exchange hours |

## Commodities

| Endpoint | Description |
|----------|-------------|
| `commodities-list` | Commodities list |

## DCF (Discounted Cash Flow)

| Endpoint | Description |
|----------|-------------|
| `discounted-cash-flow` | Discounted cash flow |
| `levered-discounted-cash-flow` | Levered DCF |
| `custom-discounted-cash-flow` | Custom DCF |
| `custom-levered-discounted-cash-flow` | Custom levered DCF |

## Forex

| Endpoint | Description |
|----------|-------------|
| `forex-list` | Forex list |

## Crypto

| Endpoint | Description |
|----------|-------------|
| `cryptocurrency-list` | Cryptocurrency list |

## Congress Disclosures

| Endpoint | Description |
|----------|-------------|
| `senate-latest` | Latest Senate trades |
| `house-latest` | Latest House trades |
| `senate-trades` | Senate trades |
| `senate-trades-by-name` | Senate trades by name |
| `house-trades` | House trades |
| `house-trades-by-name` | House trades by name |

## ESG

| Endpoint | Description |
|----------|-------------|
| `esg-disclosures` | ESG disclosures |
| `esg-ratings` | ESG ratings |
| `esg-benchmark` | ESG benchmark |

## COT (Commitment of Traders)

| Endpoint | Description |
|----------|-------------|
| `commitment-of-traders-report` | COT report |
| `commitment-of-traders-analysis` | COT analysis |
| `commitment-of-traders-list` | COT list |

## Fundraisers

| Endpoint | Description |
|----------|-------------|
| `crowdfunding-offerings-latest` | Latest crowdfunding |
| `crowdfunding-offerings-search` | Crowdfunding search |
| `crowdfunding-offerings` | Crowdfunding offerings |
| `fundraising-latest` | Latest fundraising |
| `fundraising-search` | Fundraising search |
| `fundraising` | Fundraising |

## Bulk Endpoints

| Endpoint | Description |
|----------|-------------|
| `profile-bulk` | Bulk profiles |
| `rating-bulk` | Bulk ratings |
| `dcf-bulk` | Bulk DCF |
| `scores-bulk` | Bulk scores |
| `price-target-summary-bulk` | Bulk price targets |
| `etf-holder-bulk` | Bulk ETF holders |
| `upgrades-downgrades-consensus-bulk` | Bulk upgrades/downgrades |
| `key-metrics-ttm-bulk` | Bulk key metrics TTM |
| `ratios-ttm-bulk` | Bulk ratios TTM |
| `peers-bulk` | Bulk peers |
| `earnings-surprises-bulk` | Bulk earnings surprises |
| `income-statement-bulk` | Bulk income statements |
| `income-statement-growth-bulk` | Bulk income growth |
| `balance-sheet-statement-bulk` | Bulk balance sheets |
| `balance-sheet-statement-growth-bulk` | Bulk balance sheet growth |
| `cash-flow-statement-bulk` | Bulk cash flow |
| `cash-flow-statement-growth-bulk` | Bulk cash flow growth |
| `eod-bulk` | Bulk EOD prices |

---

## Usage Example

```python
import requests

API_KEY = "your_api_key"
BASE_URL = "https://financialmodelingprep.com/stable"

# Get company profile
response = requests.get(f"{BASE_URL}/profile?symbol=AAPL&apikey={API_KEY}")
profile = response.json()

# Get real-time quote
response = requests.get(f"{BASE_URL}/quote?symbol=AAPL&apikey={API_KEY}")
quote = response.json()

# Get financial ratios TTM
response = requests.get(f"{BASE_URL}/ratios-ttm?symbol=AAPL&apikey={API_KEY}")
ratios = response.json()
```
