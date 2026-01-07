# Daily Deep Brief

每日自動產出美股深度研究筆記的自動化系統。

## 功能特色

- **標題瞬間吸睛**：多候選標題，支援 A/B 測試
- **內容有深度**：事件 → 產業影響 → 關鍵個股 → 估值分析 → 觀察清單
- **自動化流程**：API 拉資料 → 分析 → AI 寫稿 → 發佈 Ghost → 寄 Newsletter

## 系統架構

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Collector  │───▶│   Enricher  │───▶│   Analyzer  │
│ (Google RSS)│    │ (FMP/Alpha) │    │ (Scoring)   │
└─────────────┘    └─────────────┘    └─────────────┘
                                            │
                                            ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Publisher  │◀───│   Quality   │◀───│   Writer    │
│   (Ghost)   │    │   Gates     │    │  (Codex)    │
└─────────────┘    └─────────────┘    └─────────────┘
```

## 快速開始

### 1. 安裝依賴

```bash
# 使用 pip
pip install -e .

# 或使用 pip + requirements
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 填入實際的 API keys
```

### 3. 初始化專案

```bash
python -m src.app init
```

### 4. 執行流程

```bash
# 完整流程 (draft 模式)
python -m src.app run --edition postclose --mode draft

# 僅收集新聞
python -m src.app collect --limit 20

# 補充財務數據
python -m src.app enrich NVDA TSLA PLTR

# 查看狀態
python -m src.app status
```

## 環境變數

| 變數名稱 | 必要性 | 說明 |
|---------|--------|------|
| `FMP_API_KEY` | 必要 | Financial Modeling Prep API Key |
| `ALPHAVANTAGE_API_KEY` | 選填 | Alpha Vantage API Key |
| `GHOST_API_URL` | 選填 | Ghost CMS API URL |
| `GHOST_ADMIN_API_KEY` | 選填 | Ghost Admin API Key |
| `CODEX_MODEL` | 選填 | AI 模型名稱 (預設: claude-sonnet-4-20250514) |

## 目錄結構

```
project/
├── README.md                 # 本文件
├── pyproject.toml           # Python 專案設定
├── .env.example             # 環境變數範例
│
├── config/
│   ├── universe.yaml        # 追蹤主題與標的設定
│   └── runtime.yaml         # 執行時期設定
│
├── schemas/
│   ├── research_pack.schema.json  # 研究包 JSON Schema
│   └── post.schema.json           # 文章輸出 JSON Schema
│
├── prompts/
│   └── daily_brief.prompt.txt     # AI 寫稿 prompt
│
├── src/
│   ├── app.py               # CLI 入口
│   ├── collectors/          # 新聞收集模組
│   ├── enrichers/           # 數據補完模組
│   ├── analyzers/           # 分析模組
│   ├── writers/             # 寫稿模組
│   ├── publishers/          # 發佈模組
│   ├── quality/             # 品質控管模組
│   ├── storage/             # 儲存模組
│   └── utils/               # 工具函數
│
├── out/                     # 輸出檔案
│   ├── research_pack.json   # 研究包
│   ├── post.json            # 文章 JSON
│   ├── post.md              # 文章 Markdown
│   └── post.html            # 文章 HTML
│
├── data/                    # 資料與快取
│   ├── cache.db             # SQLite 快取
│   └── cache/               # 檔案快取
│
└── tests/                   # 測試
```

## 輸出檔案

### research_pack.json

研究包包含所有分析所需的原始資料：

- `meta`: 執行資訊 (run_id, 時間, edition)
- `primary_event`: 主要事件
- `primary_theme`: 主題
- `key_stocks`: 關鍵個股 (2-4 檔)
- `companies`: 公司資料 (價量、財務、估計)
- `valuations`: 估值分析
- `peer_table`: 同業比較表
- `sources`: 資料來源

### post.json

文章輸出包含：

- `title`: 選定標題
- `title_candidates`: 5-12 個候選標題
- `tldr`: TL;DR 重點 (3-6 條)
- `markdown`: 完整 Markdown 內容
- `sections`: 各章節內容
- `tags`: 標籤
- `disclosures`: 免責聲明

## 版本規劃

- **v0 (Prototype)**: 本地產出 research_pack + post.md
- **v1 (MVP)**: 自動建 Ghost Draft，人工發布
- **v2 (Beta)**: 端到端自動發布 + Newsletter
- **v3 (Production)**: 可擴展、可觀測、可優化

## 品質控管

系統包含 11 個 Quality Gates，採用 **Fail-Closed** 原則：任何一關失敗就不自動發布。

### Quality Gates 清單

| Gate | 名稱 | 說明 |
|------|------|------|
| 1 | **sources** | 資訊來源數量 ≥ 3，不同出版者 ≥ 2 |
| 2 | **structure** | 結構完整性（key_stocks, tldr, what_to_watch） |
| 3 | **compliance** | 合規檢查（禁止投行引用、禁用詞檢測） |
| 4 | **number_traceability** | 數字可追溯至 research_pack |
| 5 | **valuation** | 估值完整性（Bear/Base/Bull 三情境） |
| 6 | **topic_integrity** | 主題一致性（防止串稿/內容污染） |
| 7 | **data_completeness** | 資料完整性（防止 null 欄位輸出） |
| 8 | **json_html_consistency** | JSON 與 HTML 內容一致性 |
| 9 | **flash_consistency** | Flash 內部一致性（repricing 變數對齊） |
| 10 | **source_urls** | 來源 URL 完整性（關鍵來源必須有 URL） |
| 11 | **publishing** | 發佈參數檢查（newsletter、segment） |

### 執行品質檢查

```bash
# 執行品質檢查
python -m src.quality.quality_gate -p out/post.json -r out/research_pack.json

# 查看報告
cat out/quality_report.json
```

### 關鍵規則

- **數字可追溯**: 所有價格、百分比、日期必須來自 research_pack
- **禁止投行引用**: 不可引用 Morgan Stanley、Goldman Sachs 等投行報告
- **條件式語言**: 使用「若...則...」而非「應該買/賣」
- **來源 URL**: news、sec_filing 類型來源必須有可驗證 URL

## HTML 元件系統

系統提供 8 種標準化 HTML 元件（位於 `src/writers/html_components.py`）：

| 元件 | 用途 |
|------|------|
| `CardBox` | 卡片式資訊框（關鍵數字） |
| `DataTable` | 數據表格（同業比較） |
| `QuoteBlock` | 引用區塊（管理層語錄） |
| `AlertBanner` | 警示橫幅（風險警告） |
| `TickerPill` | 股票標籤（代碼 + 漲跌） |
| `ScenarioMatrix` | 情境矩陣（3x3 EPS × Guidance） |
| `TimelineBlock` | 時間軸（觀察清單） |
| `SourceFooter` | 來源頁尾（資料來源） |

所有元件使用 inline CSS，確保 email 相容性。

## License

MIT
