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

- 來源數量 ≥ 5
- 數字可追溯至 research_pack
- 無禁用詞 (保證獲利、穩賺等)
- 必含免責聲明

## License

MIT
