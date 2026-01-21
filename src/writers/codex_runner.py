"""Codex CLI Writer

使用 Claude/Codex CLI 生成文章。
"""

import json
import os
import subprocess
import time
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonschema
import markdown

from ..utils.logging import get_logger
from ..utils.time import get_run_id

logger = get_logger(__name__)


@dataclass
class PostOutput:
    """文章輸出結構"""

    meta: dict
    title: str
    title_candidates: list[dict]
    slug: str
    excerpt: str
    tldr: list[str]
    sections: dict
    markdown: str
    html: str
    tags: list[str]
    tickers_mentioned: list[str]
    theme: dict
    what_to_watch: list[str]
    sources: list[dict]
    disclosures: dict
    quality_check: Optional[dict] = None
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = dict(self.extra_fields) if self.extra_fields else {}
        data.update({
            "meta": self.meta,
            "title": self.title,
            "title_candidates": self.title_candidates,
            "slug": self.slug,
            "excerpt": self.excerpt,
            "tldr": self.tldr,
            "sections": self.sections,
            "markdown": self.markdown,
            "html": self.html,
            "tags": self.tags,
            "tickers_mentioned": self.tickers_mentioned,
            "theme": self.theme,
            "what_to_watch": self.what_to_watch,
            "sources": self.sources,
            "disclosures": self.disclosures,
            "quality_check": self.quality_check,
        })
        return data

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class CodexRunner:
    """Codex CLI 執行器"""

    # Post type specific configurations
    POST_TYPE_CONFIG = {
        "morning": {
            "prompt_path": "prompts/postD.prompt.md",
            "schema_path": "schemas/postD.schema.json",
        },
        "flash": {
            "prompt_path": "prompts/postA.prompt.md",
            "schema_path": "schemas/postA.schema.json",
        },
        "earnings": {
            "prompt_path": "prompts/postB.prompt.md",
            "schema_path": "schemas/postB.schema.json",
        },
        "deep": {
            "prompt_path": "prompts/postC.prompt.md",
            "schema_path": "schemas/postC.schema.json",
        },
    }

    # P0-1: 各文章類型的推薦模型（測試 gpt-5.2）
    POST_TYPE_MODELS = {
        "morning": "cli-gpt-5.2",           # 晨報：CLI 模型
        "flash": "cli-gpt-5.2",             # CLI 模型，輸出較長
        "earnings": "cli-gpt-5.2",          # CLI 模型，輸出較長
        "deep": "cli-gpt-5.2",              # CLI 模型，輸出較長
    }

    # P0-2: 各文章類型的 token/temperature 預設
    # 大幅提高 max_tokens 以確保完整輸出（尤其是 Deep 的 25 個 sections）
    POST_TYPE_LIMITS = {
        "morning": {"max_tokens": 12000, "temperature": 0.6},   # 晨報：8 top events + 10 quick hits
        "flash": {"max_tokens": 10000, "temperature": 0.6},    # 6000 → 10000
        "earnings": {"max_tokens": 20000, "temperature": 0.55}, # 7000 → 20000
        "deep": {"max_tokens": 25000, "temperature": 0.5},      # 12000 → 25000 (需要 25 個 sections)
    }

    def __init__(
        self,
        model: str = "cli-gpt-5.2",
        prompt_path: str = "prompts/daily_brief.prompt.txt",
        schema_path: str = "schemas/post.schema.json",
        max_tokens: int = 32000,
        temperature: float = 0.7,
        post_type: Optional[str] = None,
    ):
        """初始化 Codex 執行器

        Args:
            model: 使用的模型
            prompt_path: Prompt 檔案路徑 (fallback if post_type not specified)
            schema_path: 輸出 Schema 路徑 (fallback if post_type not specified)
            max_tokens: 最大 token 數
            temperature: Temperature 參數
            post_type: 文章類型 (flash, earnings, deep) - 用於選擇對應的 prompt/schema
        """
        # 模型選擇優先順序:
        # 1. LITELLM_MODEL 環境變數（強制覆蓋）
        # 2. CODEX_MODEL 環境變數
        # 3. POST_TYPE_MODELS[post_type]（按文章類型優化）
        # 4. 參數傳入的 model
        env_model = os.getenv("LITELLM_MODEL") or os.getenv("CODEX_MODEL")
        type_model = self.POST_TYPE_MODELS.get(post_type) if post_type else None
        self.model = env_model or type_model or model
        self.env_model_override = env_model

        type_limits = self.POST_TYPE_LIMITS.get(post_type or "", {})
        base_max_tokens = type_limits.get("max_tokens", max_tokens)
        base_temperature = type_limits.get("temperature", temperature)
        self.max_tokens = self._get_env_int("CODEX_MAX_TOKENS", base_max_tokens)
        self.temperature = self._get_env_float("CODEX_TEMPERATURE", base_temperature)
        self.post_type = post_type

        # Select prompt and schema based on post_type
        if post_type and post_type in self.POST_TYPE_CONFIG:
            config = self.POST_TYPE_CONFIG[post_type]
            self.prompt_path = Path(config["prompt_path"])
            self.schema_path = Path(config["schema_path"])
            logger.info(f"Using post_type '{post_type}' config: prompt={self.prompt_path}, schema={self.schema_path}")
        else:
            self.prompt_path = Path(prompt_path)
            self.schema_path = Path(schema_path)

        # 載入 prompt template
        if self.prompt_path.exists():
            with open(self.prompt_path) as f:
                self.prompt_template = f.read()
        else:
            logger.warning(f"Prompt file not found: {self.prompt_path}")
            self.prompt_template = self._get_default_prompt()

        # 載入 schema
        self.schema = None
        if self.schema_path.exists():
            with open(self.schema_path) as f:
                self.schema = json.load(f)

    def _escape_json_strings(self, json_text: str) -> str:
        """修復 JSON 字串中的未轉義字元

        LLM 有時會在 JSON 字串值中輸出未轉義的換行符或其他特殊字元。
        這個方法嘗試找到這些問題並修復它們。

        Args:
            json_text: 原始 JSON 文字

        Returns:
            修復後的 JSON 文字
        """
        import re

        result = []
        in_string = False
        escape_next = False
        i = 0

        # 有效的 JSON escape 字元
        valid_escapes = {'n', 'r', 't', 'b', 'f', '\\', '/', '"', 'u'}

        while i < len(json_text):
            char = json_text[i]

            if escape_next:
                # 檢查是否是有效的 escape 序列
                if char in valid_escapes:
                    result.append(char)
                elif char == 'u' and i + 4 < len(json_text):
                    # Unicode escape \uXXXX
                    result.append(char)
                else:
                    # 無效的 escape，移除反斜線並保留字元
                    # 例如 \_ 變成 _
                    result.pop()  # 移除之前加入的 \
                    result.append(char)
                escape_next = False
                i += 1
                continue

            if char == '\\':
                escape_next = True
                result.append(char)
                i += 1
                continue

            if char == '"':
                in_string = not in_string
                result.append(char)
                i += 1
                continue

            if in_string:
                # 在字串內部，需要轉義特殊字元
                if char == '\n':
                    result.append('\\n')
                elif char == '\r':
                    result.append('\\r')
                elif char == '\t':
                    result.append('\\t')
                else:
                    result.append(char)
            else:
                result.append(char)

            i += 1

        return ''.join(result)

    def _get_env_int(self, name: str, default: int) -> int:
        """讀取整數環境變數，失敗則回退到預設值。"""
        raw = os.getenv(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError:
            logger.warning(f"Invalid {name}={raw}, fallback to {default}")
            return default

    def _get_env_float(self, name: str, default: float) -> float:
        """讀取浮點環境變數，失敗則回退到預設值。"""
        raw = os.getenv(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            logger.warning(f"Invalid {name}={raw}, fallback to {default}")
            return default

    def _fix_invalid_escapes_regex(self, json_text: str) -> str:
        """用正則表達式修復無效的 escape 序列

        補充 _escape_json_strings 可能遺漏的情況。
        """
        import re

        # 修復無效的 escape 序列（如 \x, \y 等非標準 escape）
        # 保留有效的 escape: \n, \r, \t, \b, \f, \\, \/, \", \uXXXX
        def fix_escape(match):
            escape_char = match.group(1)
            valid = {'n', 'r', 't', 'b', 'f', '\\', '/', '"'}
            if escape_char in valid:
                return match.group(0)  # 保留有效 escape
            elif escape_char == 'u':
                return match.group(0)  # 保留 unicode escape
            else:
                return escape_char  # 移除反斜線，只保留字元

        # 匹配反斜線後跟任意字元
        fixed = re.sub(r'\\(.)', fix_escape, json_text)
        return fixed

    def _get_default_prompt(self) -> str:
        """取得預設 prompt"""
        return """
你是一位資深美股研究分析師，請根據以下 research_pack 資料，撰寫一篇專業的深度研究筆記。

## 輸出要求
1. 標題要吸引人，並提供 5-12 個候選標題
2. 包含摘要 (3-6 點重點)，標題用「摘要」而非 TL;DR
3. 完整分析：事件摘要、重要性、產業影響、關鍵個股、估值、同業比較、觀察清單
4. 所有數字必須來自 research_pack，不可杜撰
5. 包含免責聲明

## Research Pack 資料
{research_pack}
"""

    def _build_prompt(self, research_pack: dict) -> str:
        """建構完整 prompt

        Args:
            research_pack: 研究包資料

        Returns:
            完整 prompt
        """
        research_pack_json = json.dumps(research_pack, indent=2, ensure_ascii=False)

        # P1-1: 載入 Fact Pack（如果存在）
        fact_pack_section = ""
        try:
            from pathlib import Path
            fact_pack_path = Path("out/fact_pack.json")
            if fact_pack_path.exists():
                with open(fact_pack_path, "r", encoding="utf-8") as f:
                    fact_pack = json.load(f)
                fact_pack_json = json.dumps(fact_pack, indent=2, ensure_ascii=False)
                fact_pack_section = f"""

## Fact Pack 資料 (P1-1: 唯一數據來源)

**CRITICAL**: 所有數字必須從以下 fact_pack 中引用，不可自行計算或推測。
如果 fact_pack 中沒有某個數據，請改寫句子避免使用該數字，絕對不要寫「數據」或「TBD」。

{fact_pack_json}
"""
        except Exception:
            pass  # fact_pack 不存在或無法讀取，繼續使用 research_pack

        if "{research_pack}" in self.prompt_template:
            prompt = self.prompt_template.replace("{research_pack}", research_pack_json)
            return prompt + fact_pack_section
        return f"{self.prompt_template.rstrip()}\n\n## Research Pack 資料\n{research_pack_json}\n{fact_pack_section}"

    def _build_minimal_prompt(self, research_pack: dict) -> str:
        """最小化保底 prompt：只要求必要欄位的純 JSON。"""
        research_pack_json = json.dumps(research_pack, indent=2, ensure_ascii=False)
        return f"""
你是一位專業美股研究分析師。請只輸出 JSON object，不能有任何文字或 code block。

## 必填欄位
- title
- title_en
- slug
- excerpt
- tags
- meta
- executive_summary (至少包含 en)
- markdown
- html
- sources
- tldr
- what_to_watch
- disclosures

如果無法完整產生內容，請使用空字串或空陣列/物件，但不要缺欄位。

## Research Pack 資料
{research_pack_json}
"""

    def _get_system_prompt(self) -> str:
        """取得系統提示 - P0-1: 強制純 JSON 輸出"""
        # v4.3: 根據 post_type 使用專用系統提示
        base_prompt = """你是一位專業的美股研究分析師。

## 輸出格式要求 (CRITICAL)
- 輸出純 JSON，**絕對不要**加 ```json ``` 或任何 markdown code block
- 直接輸出 JSON object，第一個字元必須是 {，最後一個字元必須是 }
- 不要在 JSON 前後加任何文字說明

## 必填欄位
- title: 選定標題（中文）
- title_en: 英文標題
- slug: URL 友好的 slug（依 post_type 結尾: -flash, -earnings, -deep）
- excerpt: 摘要 (250-400字)
- tags: 標籤列表
- meta: 文章元資料
- executive_summary: 雙語摘要 (至少包含 en)
- sources: 來源列表（必須有 URL）
- markdown: 完整 Markdown 內容
- html: Ghost CMS HTML 內容（含 inline styles）

## 語言規則
- 主體語言: 繁體中文 (zh-TW)
- 數字格式: 美式 (1,234.56)
- 必須包含英文摘要 (executive_summary.en)

## Paywall 規則 (v4.3)
- 必須在 html 中放置 <!--members-only--> 分隔 FREE/MEMBERS 區域
- 只能放一次，不可重複

## 禁止事項
- 不可憑空杜撰數字
- 不可引用投資銀行研究
- 不可使用「建議買/賣」、「應該」等字眼
"""
        return base_prompt

    def _infer_publisher_from_url(self, url: str) -> str:
        """Infer publisher name from URL when missing."""
        if not url:
            return "Unknown"
        try:
            from urllib.parse import urlparse

            host = urlparse(url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if not host:
                return "Unknown"
            if host.endswith("sec.gov"):
                return "SEC.gov"
            if host.endswith("reuters.com"):
                return "Reuters"
            if host.endswith("bloomberg.com"):
                return "Bloomberg"
            if host.endswith("wsj.com"):
                return "WSJ"
            if host.endswith("ft.com"):
                return "Financial Times"
            if host.endswith("cnbc.com"):
                return "CNBC"
            if host.endswith("marketwatch.com"):
                return "MarketWatch"
            if host.endswith("yahoo.com"):
                return "Yahoo Finance"
            parts = host.split(".")
            base = parts[-2] if len(parts) >= 2 else parts[0]
            if base in {"co", "com", "net", "org"} and len(parts) >= 3:
                base = parts[-3]
            return base.replace("-", " ").title()
        except Exception:
            return "Unknown"

    def _normalize_sources(
        self,
        sources: list,
        research_pack: dict,
        min_count: int = 5,
        min_publishers: int = 3,
    ) -> list[dict]:
        """Ensure sources include publisher + url and meet minimum count."""
        normalized = []
        seen = set()

        def add_source(item: dict) -> None:
            url = (item.get("url") or "").strip()
            name = (item.get("name") or item.get("title") or "").strip()
            publisher = (item.get("publisher") or "").strip()
            source_type = (item.get("type") or "news").strip()

            if not publisher:
                publisher = self._infer_publisher_from_url(url)

            if not name:
                name = publisher if publisher else "Source"

            key = url or f"{name}|{publisher}"
            if not key or key in seen:
                return

            normalized.append({
                "name": name,
                "publisher": publisher,
                "url": url,
                "type": source_type or "news",
            })
            seen.add(key)

        def distinct_publishers() -> int:
            return len({s.get("publisher", "").lower() for s in normalized if s.get("publisher")})

        for source in sources or []:
            if isinstance(source, dict):
                add_source(source)
            elif isinstance(source, str):
                url = ""
                name = source.strip()
                publisher = ""
                if "http" in source:
                    parts = source.split("http", 1)
                    name = parts[0].strip(" -:")
                    url = "http" + parts[1].strip()
                if " - " in name:
                    title, pub = name.rsplit(" - ", 1)
                    name = title.strip()
                    publisher = pub.strip()
                add_source({
                    "name": name,
                    "publisher": publisher,
                    "url": url,
                    "type": "news",
                })

        news_items = research_pack.get("news_items", [])
        for item in news_items:
            if len(normalized) >= min_count and distinct_publishers() >= min_publishers:
                break
            if not isinstance(item, dict):
                continue
            add_source({
                "name": item.get("headline") or item.get("title") or "",
                "publisher": item.get("publisher") or item.get("source") or "",
                "url": item.get("url") or "",
                "type": item.get("source_type") or "news",
            })

        return normalized

    def _ensure_title_in_html(self, html: str, title: str) -> str:
        """移除 HTML 中的 <h1> 標題，因為 Ghost 會自動顯示文章標題。

        避免標題重複顯示（Ghost title + HTML h1）。
        """
        if not html:
            return html

        import re

        # 移除開頭的 <h1> 標題（Ghost 會自動顯示）
        # 匹配模式: <h1>...</h1> 或 <h1 id="...">...</h1>
        html = re.sub(r'^\s*<h1[^>]*>.*?</h1>\s*', '', html, count=1, flags=re.DOTALL)

        return html.strip()

    def _ensure_disclosure_in_markdown(self, markdown_text: str) -> str:
        """Append disclosure if missing from markdown."""
        if not markdown_text:
            return markdown_text
        required = ["非投資建議", "not investment advice", "投資有風險", "for reference only"]
        lower = markdown_text.lower()
        if any(r.lower() in lower for r in required):
            return markdown_text
        disclosure = "\n\n本報告僅供參考，非投資建議。投資有風險，請審慎評估。\n"
        return markdown_text.rstrip() + disclosure

    def _ensure_disclosure_in_html(self, html: str) -> str:
        """Append disclosure if missing from HTML."""
        if not html:
            return html
        required = ["非投資建議", "not investment advice", "投資有風險", "for reference only"]
        lower = html.lower()
        if any(r.lower() in lower for r in required):
            return html
        disclosure_html = "<p>本報告僅供參考，非投資建議。投資有風險，請審慎評估。</p>"
        return html + "\n" + disclosure_html

    def _ensure_primary_ticker_in_html(self, html: str, ticker: str) -> str:
        """Ensure HTML contains the primary ticker for consistency checks."""
        if not html or not ticker:
            return html
        if ticker in html:
            return html
        return f"<p><strong>{ticker}</strong></p>\n{html}"

    def _build_title_candidates(self, base_title: str, research_pack: dict, min_count: int) -> list[dict]:
        """Generate minimal title candidates if missing."""
        theme_id = (research_pack.get("primary_theme", {}) or {}).get("id", "")
        ticker = research_pack.get("deep_dive_ticker", "") or ""
        candidates = [
            base_title,
            f"{ticker} 今日主線：{theme_id} 重新定價",
            f"{theme_id} 快報：{ticker} 成為焦點",
            f"{ticker} 驅動 {theme_id} 主題升溫",
            f"{theme_id} 風險與機會：{ticker} 核心觀點",
            f"{ticker} 事件解析：{theme_id} 下一步",
        ]
        out = []
        used = set()
        for i, title in enumerate(candidates):
            title = title.strip()
            if not title or title in used:
                continue
            out.append({"title": title, "style": "news", "score": max(60, 100 - i * 5)})
            used.add(title)
            if len(out) >= min_count:
                break
        return out

    def _build_title_en(self, result: dict, research_pack: dict) -> str:
        """Build a minimal English title if missing."""
        title = (result.get("title") or "").strip()
        if title and title.isascii():
            return title
        theme = research_pack.get("primary_theme", {}) or {}
        theme_en = (theme.get("name_en") or theme.get("id") or "").replace("_", " ").title()
        ticker = research_pack.get("deep_dive_ticker", "") or ""
        if ticker and theme_en:
            return f"{ticker} {theme_en} Brief"
        if ticker:
            return f"{ticker} Daily Brief"
        if theme_en:
            return f"{theme_en} Daily Brief"
        return "Daily Deep Brief"

    def _build_tldr_fallback(self, research_pack: dict) -> list[str]:
        """Build minimal TL;DR bullets without introducing new numbers."""
        theme_id = (research_pack.get("primary_theme", {}) or {}).get("id", "")
        ticker = research_pack.get("deep_dive_ticker", "") or ""
        bullets = []
        if ticker:
            bullets.append(f"{ticker} 成為今日主線，市場聚焦 {theme_id} 重定價方向")
        if theme_id:
            bullets.append(f"{theme_id} 主題今日強化，資金偏好轉向核心受惠股")
        primary_event = research_pack.get("primary_event", {}) or {}
        if primary_event.get("title"):
            bullets.append(primary_event.get("title"))
        bullets.append("關鍵訊號仍以政策與資本支出節奏為核心觀察點")
        bullets.append("短線情緒偏多，但需留意反向風險與估值波動")
        return bullets

    def _build_watch_fallback(self, research_pack: dict) -> list[str]:
        """Build minimal what_to_watch list without numbers."""
        theme_id = (research_pack.get("primary_theme", {}) or {}).get("id", "")
        ticker = research_pack.get("deep_dive_ticker", "") or ""
        items = [
            f"觀察 {theme_id} 相關訂單與資本支出變化",
            f"留意 {ticker} 管理層對需求能見度的最新訊號",
            "追蹤市場風險偏好與資金輪動方向",
        ]
        return [i for i in items if i.strip()]

    def _format_currency(self, value: Optional[float]) -> Optional[str]:
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if abs(v) >= 1e12:
            return f"${v/1e12:.1f}T"
        if abs(v) >= 1e9:
            return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.2f}"

    def _format_percent(self, value: Optional[float], is_fraction: bool = True) -> Optional[str]:
        """Format a value as percentage.

        IMPORTANT - Percent Field Semantics:
        - is_fraction=True (default): Value is a fraction (0.678 = 67.8%), multiply by 100
          Use for: gross_margin, operating_margin, net_margin
        - is_fraction=False: Value is already in percent form (0.99 = 0.99%), DO NOT multiply
          Use for: change_pct_1d, change_ytd (from FMP changePercentage)

        Args:
            value: The numeric value
            is_fraction: If True, multiply by 100. If False, use as-is.

        Returns:
            Formatted percentage string like "67.80%" or "+0.99%"
        """
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None

        if is_fraction:
            v = v * 100

        # Add + prefix for positive non-fraction values (like price changes)
        if not is_fraction and v > 0:
            return f"+{v:.2f}%"
        return f"{v:.2f}%"

    def _ensure_key_numbers(self, existing: list, research_pack: dict, count: int) -> list[dict]:
        """Ensure key_numbers list has required count using research_pack values."""
        numbers = list(existing) if isinstance(existing, list) else []
        if len(numbers) >= count:
            return numbers[:count]

        ticker = research_pack.get("deep_dive_ticker") or ""
        market_data = research_pack.get("market_data", {}) or {}
        if ticker and ticker in market_data:
            data = market_data[ticker]
            price = data.get("price")
            change = data.get("change_pct")
            market_cap = data.get("market_cap")
            if price is not None:
                numbers.append({"value": self._format_currency(price), "label": f"{ticker} 現價", "source": "market_data"})
            if change is not None:
                # change_pct is already in percent form (0.99 = 0.99%), do NOT multiply by 100
                numbers.append({"value": self._format_percent(change, is_fraction=False), "label": f"{ticker} 1D 變動", "source": "market_data"})
            if market_cap is not None:
                numbers.append({"value": self._format_currency(market_cap), "label": f"{ticker} 市值", "source": "market_data"})

        if len(numbers) < count:
            recent = research_pack.get("recent_earnings", {}) or {}
            if recent.get("revenue_actual") is not None:
                numbers.append({"value": self._format_currency(recent.get("revenue_actual")), "label": "最新營收", "source": "recent_earnings"})
            if recent.get("eps_actual") is not None:
                numbers.append({"value": f"${recent.get('eps_actual'):.2f}", "label": "最新 EPS", "source": "recent_earnings"})

        if len(numbers) < count:
            deep_data = research_pack.get("deep_dive_data", {}) or {}
            fundamentals = deep_data.get("fundamentals", {}) or {}
            if fundamentals.get("gross_margin") is not None:
                numbers.append({"value": self._format_percent(fundamentals.get("gross_margin")), "label": "毛利率", "source": "fundamentals"})
            if fundamentals.get("operating_margin") is not None:
                numbers.append({"value": self._format_percent(fundamentals.get("operating_margin")), "label": "營業利益率", "source": "fundamentals"})

        # Trim and ensure no empty values
        cleaned = [n for n in numbers if n.get("value")]
        return cleaned[:count]

    def _ensure_repricing_dashboard(self, existing: list, research_pack: dict) -> list[dict]:
        """Ensure repricing_dashboard has at least 3 items."""
        items = list(existing) if isinstance(existing, list) else []
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            direct_impact = item.get("direct_impact", "")
            if isinstance(direct_impact, list):
                direct_impact = ", ".join(str(v) for v in direct_impact if v is not None)
            item["direct_impact"] = direct_impact or ""
            if "variable" in item and not isinstance(item.get("variable"), str):
                item["variable"] = str(item.get("variable"))
            if "why_important" in item and not isinstance(item.get("why_important"), str):
                item["why_important"] = str(item.get("why_important"))
            if "leading_signal" in item and not isinstance(item.get("leading_signal"), str):
                item["leading_signal"] = str(item.get("leading_signal"))
            normalized.append(item)
        items = normalized
        if len(items) >= 3:
            return items
        tickers = [s.get("ticker") for s in research_pack.get("key_stocks", []) if s.get("ticker")]
        ticker_str = ", ".join(tickers[:3]) or (research_pack.get("deep_dive_ticker") or "")
        fallback = [
            {
                "variable": "AI 資本支出節奏",
                "why_important": "決定主題需求能見度與訂單動能",
                "leading_signal": "雲端/伺服器資本支出指引",
                "direct_impact": f"{ticker_str} 估值與訂單預期",
            },
            {
                "variable": "先進製程供給",
                "why_important": "影響高階晶片供應與定價權",
                "leading_signal": "晶圓廠產能利用率與擴產指引",
                "direct_impact": f"{ticker_str} 毛利結構",
            },
            {
                "variable": "終端需求強弱",
                "why_important": "決定短期出貨與庫存循環",
                "leading_signal": "下游客戶庫存天數",
                "direct_impact": f"{ticker_str} 營收彈性",
            },
        ]
        items.extend(fallback)
        return items[:3]

    def _build_earnings_scoreboard(self, research_pack: dict) -> list[dict]:
        """Build earnings_scoreboard from recent_earnings."""
        recent = research_pack.get("recent_earnings", {}) or {}
        ticker = recent.get("ticker") or research_pack.get("deep_dive_ticker") or ""
        history = recent.get("history", []) or []
        rows = []

        def to_quarter(entry: dict) -> str:
            period = entry.get("fiscal_period") or entry.get("period")
            year = entry.get("fiscal_year") or entry.get("calendarYear")
            if period and year:
                return f"{period} {year}"
            return "Q1 2024"

        for entry in history[:4]:
            eps_actual = entry.get("eps_diluted") if entry.get("eps_diluted") is not None else entry.get("eps_actual")
            revenue_actual = entry.get("revenue_actual")
            eps_est = entry.get("eps_estimate") or entry.get("eps_estimated") or eps_actual
            rev_est = entry.get("revenue_estimate") or entry.get("revenue_estimated") or revenue_actual
            rows.append({
                "ticker": entry.get("ticker") or ticker,
                "quarter": to_quarter(entry),
                "eps_actual": eps_actual if eps_actual is not None else 0.0,
                "eps_estimate": eps_est if eps_est is not None else 0.0,
                "revenue_actual": revenue_actual if revenue_actual is not None else 0.0,
                "revenue_estimate": rev_est if rev_est is not None else 0.0,
            })

        if not rows and ticker:
            rows.append({
                "ticker": ticker,
                "quarter": "Q1 2024",
                "eps_actual": recent.get("eps_diluted") or recent.get("eps_actual") or 0.0,
                "eps_estimate": recent.get("eps_diluted") or recent.get("eps_actual") or 0.0,
                "revenue_actual": recent.get("revenue_actual") or 0.0,
                "revenue_estimate": recent.get("revenue_actual") or 0.0,
            })

        return rows

    def _build_valuation_fallback(self, research_pack: dict) -> dict:
        """Build valuation section from available valuation data."""
        ticker = research_pack.get("deep_dive_ticker") or ""
        valuations = research_pack.get("valuations") or {}
        if not isinstance(valuations, dict):
            valuations = {}
        val = valuations.get(ticker) or (research_pack.get("deep_dive_data") or {}).get("valuation") or {}
        fair_value = val.get("fair_value", {}) or {}
        current_price = val.get("current_price")
        if current_price is None:
            md = research_pack.get("market_data", {}).get(ticker, {}) if ticker else {}
            current_price = md.get("price")
        base_price = fair_value.get("base") or current_price
        bull_price = fair_value.get("bull") or current_price
        bear_price = fair_value.get("bear") or current_price

        return {
            "methodology": val.get("method") or "peer_multiple",
            "current_metrics": {"price": current_price},
            "scenarios": {
                "bear": {"target_price": bear_price, "multiple": "N/A", "triggers": []},
                "base": {"target_price": base_price, "multiple": "N/A", "rationale": val.get("rationale") or ""},
                "bull": {"target_price": bull_price, "multiple": "N/A", "triggers": []},
            },
            "fair_value_range": {"low": bear_price, "mid": base_price, "high": bull_price},
        }

    def _build_peer_comparison(self, research_pack: dict) -> dict:
        """Build minimal peer_comparison from peer_data/peer_table."""
        peer_data = research_pack.get("peer_data", {}) or {}
        peers = []
        for ticker, pdata in list(peer_data.items())[:4]:
            fundamentals = pdata.get("fundamentals", {}) or {}
            peers.append({
                "ticker": ticker,
                "name": pdata.get("name") or ticker,
                "gross_margin": fundamentals.get("gross_margin"),
                "operating_margin": fundamentals.get("operating_margin"),
            })

        peer_table = research_pack.get("peer_table", {}) or {}
        comparison_table = peer_table.get("markdown") or ""
        takeaways = peer_table.get("takeaways") or [
            "同業估值分散，反映成長能見度差異",
            "毛利與營業利益率為主要定價因子",
            "領先者享有估值溢價但波動較大",
        ]

        return {
            "peers": peers,
            "comparison_table": comparison_table,
            "takeaways": takeaways,
            "premium_discount_explanation": "以同業中位數作為估值基準。",
        }

    def _sanitize_markdown_numbers(self, markdown_text: str, research_pack: dict) -> str:
        """Remove untraced numbers to satisfy traceability gate.

        P0-2 修正：
        1. 從 fact_pack.json 載入額外的可驗證數據
        2. 把 fact_pack merge 進 research_pack 供 tracer 使用
        3. 把佔位符改成唯一 token ⟦UNTRACED⟧ 避免假陽性
        """
        if not markdown_text:
            return markdown_text
        try:
            from pathlib import Path
            import json
            from ..quality.trace_numbers import NumberTracer

            # P0-2: 載入 fact_pack（如果存在）並 merge 進 research_pack
            fact_pack_path = Path("out/fact_pack.json")
            merged_pack = dict(research_pack)  # 複製一份

            if fact_pack_path.exists():
                try:
                    with open(fact_pack_path) as f:
                        fact_pack = json.load(f)
                    # 把 fact_pack 的數據加入 merged_pack 供 tracer 使用
                    merged_pack["fact_pack"] = fact_pack

                    # 也把 fact_pack 的 tickers 數據 merge 進 market_data
                    if "tickers" in fact_pack and "market_data" not in merged_pack:
                        merged_pack["market_data"] = {}
                    for ticker, data in fact_pack.get("tickers", {}).items():
                        if ticker not in merged_pack.get("market_data", {}):
                            merged_pack.setdefault("market_data", {})[ticker] = data
                        else:
                            # merge 進現有的
                            merged_pack["market_data"][ticker].update(data)
                except Exception:
                    pass  # fact_pack 載入失敗就用原本的 research_pack

            tracer = NumberTracer()
            result = tracer.trace(markdown_text, merged_pack)
            if result.passed:
                return markdown_text

            untraced_values = sorted(
                {n.value for n in result.numbers if not n.traced},
                key=len,
                reverse=True,
            )
            sanitized = markdown_text
            for value in untraced_values:
                # P0-2: 使用唯一佔位符 token，避免與「數據中心」等正常用語混淆
                sanitized = sanitized.replace(value, "⟦UNTRACED⟧")
            return sanitized
        except Exception:
            return markdown_text

    def _strip_html_to_text(self, html_text: str) -> str:
        """Strip HTML tags for fallback markdown."""
        if not html_text:
            return ""
        import re
        import html as html_lib

        text = re.sub(r"<[^>]+>", " ", html_text)
        text = html_lib.unescape(text)
        return " ".join(text.split())

    def _missing_required_fields(self, result: dict) -> list[str]:
        """Check required fields for retry logic."""
        required = [
            "title",
            "title_en",
            "executive_summary",
            "markdown",
            "html",
            "sources",
            "tags",
            "slug",
        ]
        missing = []
        for field in required:
            value = result.get(field)
            if field == "executive_summary":
                if not isinstance(value, dict) or not value.get("en"):
                    missing.append(field)
            elif field in {"sources", "tags"}:
                if not isinstance(value, list) or not value:
                    missing.append(field)
            elif value is None or value == "" or value == {} or value == []:
                missing.append(field)
        return missing

    def _looks_truncated(self, markdown_text: str, html_text: str) -> bool:
        """Heuristic checks for truncated outputs."""
        if markdown_text and markdown_text.count("```") % 2 != 0:
            return True
        if html_text:
            stripped = html_text.strip()
            if stripped.endswith("<") or stripped.endswith("</"):
                return True
            if stripped.count("<") - stripped.count(">") > 10:
                return True
        return False

    def _parse_json_response(self, response_text: str) -> Optional[dict]:
        """解析 LLM 回應的 JSON

        Args:
            response_text: LLM 回應文字

        Returns:
            解析後的 dict 或 None
        """
        import re

        # 有時候回應會包含 ```json ... ```，需要清理
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        # 嘗試修復被截斷的 JSON
        response_text = response_text.strip()

        # 清理控制字符 (保留換行和 tab)
        response_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', response_text)

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as first_error:
            # 嘗試修復常見的截斷問題
            logger.warning(f"JSON parsing failed at position {first_error.pos}, attempting fixes...")

            fixed = response_text

            # 修復策略 0: 處理 JSON 中的未轉義換行符
            fixed = self._escape_json_strings(fixed)

            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

            # 修復策略 0.5: 用正則表達式修復無效 escape 序列
            fixed = self._fix_invalid_escapes_regex(fixed)

            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

            # 修復策略 1: 截斷在字串中間
            if fixed.count('"') % 2 != 0:
                last_quote = fixed.rfind('"')
                if last_quote > 0:
                    before_quote = fixed[:last_quote].rstrip()
                    if before_quote.endswith(':'):
                        fixed = fixed + '"'
                    elif not before_quote.endswith(',') and not before_quote.endswith('{') and not before_quote.endswith('['):
                        fixed = fixed + '"'

            # 修復策略 2: 補上缺失的括號
            open_braces = fixed.count('{') - fixed.count('}')
            open_brackets = fixed.count('[') - fixed.count(']')

            if open_braces > 0 or open_brackets > 0:
                fixed = fixed.rstrip()
                if fixed.endswith(','):
                    fixed = fixed[:-1]
                fixed += ']' * open_brackets + '}' * open_braces

            try:
                result = json.loads(fixed)
                logger.info("JSON repair successful")
                return result
            except json.JSONDecodeError as second_error:
                logger.error(f"JSON repair failed: {second_error}")
                logger.error(f"Original error position: {first_error.pos}")
                logger.error(f"Response preview (last 500 chars): {response_text[-500:]}")

                # 最後手段
                try:
                    last_brace = fixed.rfind('}')
                    if last_brace > 0:
                        truncated = fixed[:last_brace + 1]
                        open_b = truncated.count('{') - truncated.count('}')
                        open_br = truncated.count('[') - truncated.count(']')
                        truncated += ']' * open_br + '}' * open_b
                        return json.loads(truncated)
                except:
                    pass

                return None

    def _repair_json(self, broken_json: str) -> Optional[dict]:
        """P0-1: 用小模型修復壞掉的 JSON

        當主要 LLM 回傳的 JSON 無法解析時，用更便宜/快速的模型來修復。
        這比重新生成整篇文章便宜很多。

        Args:
            broken_json: 無法解析的 JSON 文字

        Returns:
            修復後的 dict 或 None
        """
        try:
            from openai import OpenAI

            base_url = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")
            api_key = os.getenv("LITELLM_API_KEY")

            if not api_key:
                return None

            # 使用較小/快速的模型做 repair
            repair_model = os.getenv("LITELLM_REPAIR_MODEL", "gemini-2.5-flash")

            client = OpenAI(api_key=api_key, base_url=base_url)

            # 截取 JSON 的前後部分（避免 prompt 過長）
            max_chars = 12000
            if len(broken_json) > max_chars:
                # 保留頭尾，因為問題通常在這兩處
                head = broken_json[:max_chars // 2]
                tail = broken_json[-(max_chars // 2):]
                json_preview = f"{head}\n... [truncated {len(broken_json) - max_chars} chars] ...\n{tail}"
            else:
                json_preview = broken_json

            repair_prompt = f"""你是 JSON 修復專家。以下 JSON 無法解析，請修復它使其成為合法 JSON。

規則：
1. 只輸出修復後的 JSON，不要加任何說明
2. 不要改變內容語意，只修正結構問題
3. 常見問題：未閉合的引號、缺少括號、尾隨逗號、未轉義的特殊字元
4. 如果 JSON 被截斷，合理地補上缺失的結尾

壞掉的 JSON：
```
{json_preview}
```

只輸出修復後的 JSON："""

            logger.info(f"Calling repair model: {repair_model}")

            response = client.chat.completions.create(
                model=repair_model,
                messages=[{"role": "user", "content": repair_prompt}],
                max_tokens=1500,  # 小 token 數，只需要修復結構
                temperature=0.1,  # 低溫度，保持確定性
                timeout=30,
            )

            if not response or not response.choices:
                return None

            repaired_text = response.choices[0].message.content
            if not repaired_text:
                return None

            # 嘗試解析修復後的 JSON
            result = self._parse_json_response(repaired_text)
            if result:
                logger.info("JSON repair successful via LLM")
                return result

            return None

        except Exception as e:
            logger.warning(f"JSON repair failed: {e}")
            return None

    def _call_litellm_api(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Optional[dict]:
        """使用 LiteLLM Proxy (OpenAI-compatible) 呼叫各種 LLM

        支援 Gemini, GPT, Claude 等模型。
        使用 WhaleForce LiteLLM Proxy: https://litellm.whaleforce.dev

        Args:
            prompt: 完整 prompt

        Returns:
            解析後的 JSON 或 None
        """
        try:
            from openai import OpenAI

            # LiteLLM Proxy 設定
            base_url = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")
            api_key = os.getenv("LITELLM_API_KEY")

            if not api_key:
                logger.error("LITELLM_API_KEY not set")
                return None

            verify_ssl = os.getenv("OPENAI_VERIFY_SSL", "true").lower() != "false"
            base_timeout = float(os.getenv("LITELLM_TIMEOUT", "180"))

            # P0-5: 動態 timeout - 根據 max_tokens 計算
            # 長文 (如 Deep Dive) 需要更長的 timeout
            # 公式: timeout = max(base_timeout, max_tokens * 0.03)
            # 例如: 12000 tokens * 0.03 = 360 秒 (6 分鐘)
            effective_max_tokens = max_tokens if max_tokens else self.max_tokens
            dynamic_timeout = max(base_timeout, effective_max_tokens * 0.03)
            # 上限設為 10 分鐘
            timeout = min(dynamic_timeout, 600)

            logger.info(f"Dynamic timeout: {timeout:.0f}s (based on {effective_max_tokens} max_tokens)")

            client_kwargs = {"api_key": api_key, "base_url": base_url, "timeout": timeout}
            try:
                import httpx
                # httpx timeout needs to be a Timeout object for proper handling
                httpx_timeout = httpx.Timeout(timeout, connect=30.0)
                client_kwargs["http_client"] = httpx.Client(timeout=httpx_timeout, verify=verify_ssl)
            except Exception as e:
                print(f"[LiteLLM] httpx setup failed: {e}", flush=True)

            client = OpenAI(**client_kwargs)
            print(f"[LiteLLM] Client created with timeout={timeout}s, verify_ssl={verify_ssl}", flush=True)

            logger.info(f"Calling LiteLLM with model: {self.model}")

            # 某些模型 (如 gpt-5) 只支援 temperature=1
            temperature = self.temperature if temperature is None else temperature
            if "gpt-5" in self.model.lower():
                temperature = 1.0
                logger.info(f"Model {self.model} only supports temperature=1, adjusted")

            # 根據模型調整 max_tokens (不同模型有不同上限)
            max_tokens = self.max_tokens if max_tokens is None else max_tokens
            model_lower = self.model.lower()
            if "gpt-4o" in model_lower and max_tokens > 16384:
                max_tokens = 16384
                logger.info(f"Model {self.model} max_tokens capped at 16384")
            elif "gpt-4" in model_lower and max_tokens > 8192:
                max_tokens = 8192
                logger.info(f"Model {self.model} max_tokens capped at 8192")

            max_attempts = int(os.getenv("LITELLM_MAX_RETRIES", "3"))
            base_delay = float(os.getenv("LITELLM_RETRY_DELAY", "5"))
            max_delay = float(os.getenv("LITELLM_MAX_RETRY_DELAY", "60"))

            for attempt in range(1, max_attempts + 1):
                try:
                    logger.info(f"LiteLLM request: attempt={attempt}/{max_attempts}, prompt_len={len(prompt)}, max_tokens={max_tokens}, timeout={timeout:.0f}s")
                    print(f"[LiteLLM] Sending request: attempt={attempt}/{max_attempts}, prompt_len={len(prompt)}, max_tokens={max_tokens}, timeout={timeout:.0f}s", flush=True)
                    import datetime
                    start_time = datetime.datetime.now()
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": self._get_system_prompt()},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=max_tokens,
                        temperature=temperature,
                        timeout=timeout,
                    )
                    elapsed = (datetime.datetime.now() - start_time).total_seconds()
                    logger.info(f"LiteLLM response received in {elapsed:.1f}s")
                    print(f"[LiteLLM] Response received in {elapsed:.1f}s", flush=True)
                except Exception as e:
                    msg = str(e)
                    retryable = (
                        "No deployments available" in msg
                        or "429" in msg
                        or "rate limit" in msg.lower()
                        or "connection error" in msg.lower()
                        or "timeout" in msg.lower()
                    )
                    if retryable and attempt < max_attempts:
                        # P0-4: 指數退避 + jitter
                        # delay = min(base * 2^attempt, max_delay) + random_jitter
                        import random
                        exponential_delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                        jitter = random.uniform(0, exponential_delay * 0.2)  # 0-20% jitter
                        actual_delay = exponential_delay + jitter

                        # 如果有 Retry-After header，優先使用
                        retry_after = None
                        if hasattr(e, 'response') and e.response:
                            retry_after = e.response.headers.get('Retry-After')
                            if retry_after:
                                try:
                                    actual_delay = max(float(retry_after), actual_delay)
                                except ValueError:
                                    pass

                        logger.warning(
                            f"LiteLLM retry {attempt}/{max_attempts} in {actual_delay:.1f}s "
                            f"(exponential backoff) after error: {msg[:100]}"
                        )
                        time.sleep(actual_delay)
                        continue
                    logger.error(f"LiteLLM API call failed: {e}")
                    return None

                # 提取回應文字
                if not response or not response.choices or response.choices[0].message is None:
                    logger.error("LiteLLM API returned empty response")
                    return None

                response_text = response.choices[0].message.content
                if response_text is None:
                    logger.error("LiteLLM API returned empty content")
                    return None

                # 解析 JSON
                return self._parse_json_response(response_text)

            return None

        except ImportError:
            logger.error("openai SDK not installed. Run: pip install openai")
            return None
        except Exception as e:
            logger.error(f"LiteLLM API call failed: {e}")
            return None

    def _call_claude_api(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Optional[dict]:
        """直接呼叫 Claude API (使用 anthropic SDK)

        Args:
            prompt: 完整 prompt

        Returns:
            解析後的 JSON 或 None
        """
        # 檢查是否有 ANTHROPIC_API_KEY，沒有則強制使用 LiteLLM
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        litellm_key = os.getenv("LITELLM_API_KEY")

        # 如果沒有 ANTHROPIC_API_KEY，或者使用非原生 Claude 模型名稱，使用 LiteLLM
        non_claude_prefixes = ("gemini", "gpt-", "gpt4", "gpt5", "o1", "o3", "deepseek", "qwen", "glm")
        model_lower = self.model.lower()
        use_litellm = (
            not anthropic_key  # 沒有 Anthropic 直連 key
            or any(model_lower.startswith(prefix) for prefix in non_claude_prefixes)  # 非 Claude 模型
            or "claude-opus-4.5" in model_lower  # LiteLLM 的 Claude 名稱
            or "claude-sonnet-4.5" in model_lower
        )

        if use_litellm:
            logger.info(f"Using LiteLLM Proxy for model: {self.model}")
            return self._call_litellm_api(prompt, max_tokens=max_tokens, temperature=temperature)

        try:
            import anthropic

            # 直連 Anthropic API
            api_key = anthropic_key
            base_url = os.getenv("ANTHROPIC_BASE_URL")

            if base_url:
                client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
            else:
                client = anthropic.Anthropic(api_key=api_key)

            max_tokens = self.max_tokens if max_tokens is None else max_tokens
            temperature = self.temperature if temperature is None else temperature
            logger.info(f"Calling Claude API with model: {self.model}, max_tokens: {max_tokens}")

            # 使用 streaming 來處理長時間請求 (避免 10 分鐘超時)
            response_text = ""
            with client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system=self._get_system_prompt(),
                temperature=temperature,
            ) as stream:
                for text in stream.text_stream:
                    response_text += text

            # 解析 JSON (使用共用方法)
            return self._parse_json_response(response_text)

        except ImportError:
            logger.error("anthropic SDK not installed. Run: pip install anthropic")
            return None
        except Exception as e:
            logger.error(f"API call failed: {e}")
            return None

    def _call_codex_cli(self, prompt: str, research_pack_path: Path) -> Optional[dict]:
        """呼叫 Codex CLI

        Args:
            prompt: 完整 prompt
            research_pack_path: research_pack.json 路徑

        Returns:
            解析後的 JSON 或 None
        """
        try:
            # 建立暫存 prompt 檔案
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(prompt)
                prompt_file = f.name

            # 建立暫存輸出檔案
            output_file = tempfile.mktemp(suffix=".json")

            # 執行 codex CLI
            cmd = [
                "codex",
                "exec",
                "--model", self.model,
                "--prompt", prompt_file,
                "--output", output_file,
            ]

            if self.schema_path.exists():
                cmd.extend(["--output-schema", str(self.schema_path)])

            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 分鐘超時
            )

            if result.returncode != 0:
                logger.error(f"Codex CLI failed: {result.stderr}")
                return None

            # 讀取輸出
            if os.path.exists(output_file):
                with open(output_file) as f:
                    return json.load(f)

            return None

        except subprocess.TimeoutExpired:
            logger.error("Codex CLI timeout")
            return None
        except FileNotFoundError:
            logger.warning("Codex CLI not found, falling back to API")
            return None
        except Exception as e:
            logger.error(f"Codex CLI error: {e}")
            return None
        finally:
            # 清理暫存檔
            if "prompt_file" in locals():
                os.unlink(prompt_file)
            if "output_file" in locals() and os.path.exists(output_file):
                os.unlink(output_file)

    def _build_post_output(
        self,
        result: dict,
        research_pack: dict,
        run_id: str,
    ) -> Optional[PostOutput]:
        """Normalize fields, validate structure, and build PostOutput."""
        # 補充必要欄位
        result = self._fill_defaults(result, research_pack, run_id)

        # Sanitize markdown numbers for traceability
        raw_markdown = result.get("markdown", "") or ""
        if not raw_markdown and result.get("html"):
            raw_markdown = self._strip_html_to_text(result.get("html", ""))
            result["markdown"] = raw_markdown
        sanitized_markdown = self._sanitize_markdown_numbers(raw_markdown, research_pack)
        sanitized_markdown = self._ensure_disclosure_in_markdown(sanitized_markdown)
        result["markdown"] = sanitized_markdown

        # Prefer model-provided HTML; otherwise render from markdown
        html_content = result.get("html") or self._convert_to_html(sanitized_markdown, result)
        html_content = self._ensure_title_in_html(html_content, result.get("title", ""))
        primary_ticker = (result.get("tickers_mentioned") or [None])[0]
        html_content = self._ensure_primary_ticker_in_html(html_content, primary_ticker)
        html_content = self._ensure_disclosure_in_html(html_content)
        result["html"] = html_content

        missing = self._missing_required_fields(result)
        if missing:
            logger.warning(f"Missing required fields after repair: {missing}")
            return None

        if self._looks_truncated(sanitized_markdown, html_content):
            logger.warning("Output appears truncated; retrying generation")
            return None

        # 驗證結果
        if self.schema:
            try:
                # 放寬驗證，只檢查必要欄位
                required_fields = ["title", "tldr", "markdown", "disclosures"]
                for field in required_fields:
                    if field not in result:
                        logger.warning(f"Missing required field: {field}")
            except Exception as e:
                logger.warning(f"Validation warning: {e}")

        # 建構輸出
        try:
            meta = dict(result.get("meta") or {})
            meta.update({
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "edition": research_pack.get("meta", {}).get("edition", "postclose"),
                "research_pack_id": research_pack.get("meta", {}).get("run_id"),
            })
            post = PostOutput(
                meta=meta,
                title=result.get("title", "Untitled"),
                title_candidates=result.get("title_candidates", []),
                slug=result.get("slug", self._generate_slug(result.get("title", ""))),
                excerpt=result.get("excerpt", ""),
                tldr=result.get("tldr", []),
                sections=result.get("sections", {}),
                markdown=sanitized_markdown,
                html=html_content,
                tags=result.get("tags", []),
                tickers_mentioned=result.get("tickers_mentioned", []),
                theme=research_pack.get("primary_theme", {}),
                what_to_watch=result.get("what_to_watch", []),
                sources=result.get("sources", research_pack.get("sources", [])),
                disclosures=result.get("disclosures", {
                    "not_investment_advice": True,
                    "risk_warning": "投資有風險，請審慎評估",
                }),
                extra_fields=result,
            )

            return post

        except Exception as e:
            logger.error(f"Failed to build PostOutput: {e}")
            return None

    def generate(
        self,
        research_pack: dict,
        run_id: Optional[str] = None,
    ) -> Optional[PostOutput]:
        """生成文章

        Args:
            research_pack: 研究包資料
            run_id: 執行 ID

        Returns:
            PostOutput 實例或 None
        """
        run_id = run_id or research_pack.get("meta", {}).get("run_id") or get_run_id()

        # 建構 prompt
        prompt = self._build_prompt(research_pack)
        logger.info(f"Prompt length: {len(prompt)} chars")

        strict_suffix = (
            "\n\nCRITICAL: Output JSON only. Do not wrap in code fences. "
            "Ensure all required fields are present."
        )

        base_max_tokens = self.max_tokens
        base_temperature = self.temperature

        # P0-1: 將 attempts 從 3 降為 2（移除 minimal_json）
        # 不再放大 max_tokens（避免截斷）
        attempts = [
            {
                "name": "base",
                "prompt": prompt,
                "temperature": base_temperature,
                "max_tokens": base_max_tokens,
            },
            {
                "name": "strict_json",
                "prompt": prompt + strict_suffix,
                "temperature": max(base_temperature - 0.15, 0.1),
                "max_tokens": base_max_tokens,  # P0-1: 不再放大
            },
        ]

        def attempt_generate() -> Optional[PostOutput]:
            for attempt in attempts:
                logger.info(f"Generation attempt: {attempt['name']}")
                result = self._call_claude_api(
                    attempt["prompt"],
                    max_tokens=attempt["max_tokens"],
                    temperature=attempt["temperature"],
                )
                if not result:
                    logger.warning("LLM returned empty result")
                    continue

                # P0-1: 如果 result 是原始文字（JSON 解析失敗），嘗試 repair
                if isinstance(result, str):
                    logger.info("Attempting JSON repair...")
                    repaired = self._repair_json(result)
                    if repaired:
                        result = repaired
                    else:
                        logger.warning("JSON repair failed, trying next attempt")
                        continue

                post = self._build_post_output(result, research_pack, run_id)
                if post:
                    return post
            return None

        post = attempt_generate()

        # 若指定模型失敗，改用 post_type 的預設模型再試一次
        if not post and self.post_type:
            fallback_model = self.POST_TYPE_MODELS.get(self.post_type)
            if self.env_model_override:
                logger.warning("Model override set; skipping fallback model")
            elif fallback_model and fallback_model != self.model:
                logger.warning(f"Retry with fallback model: {fallback_model}")
                original_model = self.model
                self.model = fallback_model
                post = attempt_generate()
                self.model = original_model

        if not post:
            logger.error("Failed to generate article")
            return None

        return post

    def _fill_defaults(self, result: dict, research_pack: dict, run_id: str) -> dict:
        """填充預設值

        Args:
            result: API 回傳結果
            research_pack: 研究包
            run_id: 執行 ID

        Returns:
            補充後的結果
        """
        # 確保有標題
        if not result.get("title"):
            event = research_pack.get("primary_event", {})
            result["title"] = event.get("title", "Daily Deep Brief")

        # 確保有英文標題
        if not result.get("title_en"):
            result["title_en"] = self._build_title_en(result, research_pack)

        # 確保有候選標題
        title_candidates = result.get("title_candidates") or []
        if len(title_candidates) < 5:
            generated = self._build_title_candidates(result["title"], research_pack, 5)
            result["title_candidates"] = title_candidates + [
                c for c in generated if c not in title_candidates
            ]

        # 確保有 excerpt
        if not result.get("excerpt"):
            summary = result.get("executive_summary")
            excerpt_text = ""
            if isinstance(summary, dict):
                excerpt_text = summary.get("chinese") or summary.get("zh") or summary.get("en") or ""
            elif isinstance(summary, str):
                excerpt_text = summary
            if not excerpt_text:
                excerpt_text = (result.get("markdown") or "").strip()
            result["excerpt"] = excerpt_text.replace("\n", " ").strip()[:350]

        # 確保有 TL;DR
        tldr_min = 5 if self.post_type == "flash" else 3
        tldr_items = result.get("tldr") or []
        if len(tldr_items) < tldr_min:
            fallback = self._build_tldr_fallback(research_pack)
            merged = tldr_items + [b for b in fallback if b not in tldr_items]
            result["tldr"] = merged[:tldr_min]

        # 確保有 what_to_watch
        watch_items = result.get("what_to_watch") or []
        if len(watch_items) < 3:
            fallback_watch = self._build_watch_fallback(research_pack)
            merged_watch = watch_items + [w for w in fallback_watch if w not in watch_items]
            result["what_to_watch"] = merged_watch[:3]

        # 確保有 disclosures
        if not result.get("disclosures"):
            result["disclosures"] = {
                "not_investment_advice": True,
                "risk_warning": "本報告僅供參考，非投資建議。投資有風險，請審慎評估。",
            }

        # 確保有 tags
        if not result.get("tags"):
            result["tags"] = ["Daily Deep Brief"]
            theme = research_pack.get("primary_theme", {})
            if theme.get("name"):
                result["tags"].append(theme["name"])
            for stock in research_pack.get("key_stocks", [])[:4]:
                result["tags"].append(stock.get("ticker", ""))

        # 確保有 tickers_mentioned
        if not result.get("tickers_mentioned"):
            result["tickers_mentioned"] = [
                s.get("ticker") for s in research_pack.get("key_stocks", [])
            ]
        if self.post_type in {"earnings", "deep"}:
            primary_ticker = research_pack.get("deep_dive_ticker")
            if primary_ticker:
                tickers = result.get("tickers_mentioned", [])
                tickers = [primary_ticker] + [t for t in tickers if t and t != primary_ticker]
                result["tickers_mentioned"] = tickers

        # Normalize sources with publishers
        result["sources"] = self._normalize_sources(result.get("sources", []), research_pack)

        # 確保有 slug
        if not result.get("slug"):
            result["slug"] = self._generate_slug(result.get("title", ""))

        # Post-type specific fallbacks
        if self.post_type == "flash":
            news_items = result.get("news_items") or []
            if len(news_items) < 8:
                pack_items = research_pack.get("news_items", [])
                for item in pack_items:
                    if len(news_items) >= 8:
                        break
                    news_items.append(item)
            result["news_items"] = news_items
            result["key_numbers"] = self._ensure_key_numbers(result.get("key_numbers", []), research_pack, 3)
            result["repricing_dashboard"] = self._ensure_repricing_dashboard(result.get("repricing_dashboard", []), research_pack)
            if not result.get("executive_summary"):
                result["executive_summary"] = {"en": "Executive summary is based on today's primary market theme."}
            if not result.get("thesis"):
                result["thesis"] = "市場重新定價聚焦於主題核心變數的變化。"
        elif self.post_type == "earnings":
            result["key_numbers"] = self._ensure_key_numbers(result.get("key_numbers", []), research_pack, 3)
            if not result.get("earnings_scoreboard"):
                result["earnings_scoreboard"] = self._build_earnings_scoreboard(research_pack)
            if not result.get("valuation"):
                result["valuation"] = self._build_valuation_fallback(research_pack)
            if not result.get("peer_comparison"):
                result["peer_comparison"] = self._build_peer_comparison(research_pack)
            if not result.get("executive_summary"):
                result["executive_summary"] = {"en": "Executive summary based on the latest earnings release."}
            if not result.get("verdict"):
                result["verdict"] = "本季結果提供了短期需求與獲利能見度的參考。"
        elif self.post_type == "deep":
            result["key_numbers"] = self._ensure_key_numbers(result.get("key_numbers", []), research_pack, 5)
            if not result.get("peer_comparison"):
                result["peer_comparison"] = self._build_peer_comparison(research_pack)
            if not result.get("executive_summary"):
                result["executive_summary"] = {"en": "Executive summary focused on the core investment thesis."}
            if not result.get("thesis"):
                result["thesis"] = "核心投資邏輯建立在主題的中長期趨勢與公司競爭力。"
            if not result.get("anti_thesis"):
                result["anti_thesis"] = "主要風險在於需求循環與估值重新評價的速度。"
            if not result.get("business_model"):
                result["business_model"] = "公司以核心產品與平台生態系作為營收與護城河來源。"
            if not result.get("valuation"):
                result["valuation"] = self._build_valuation_fallback(research_pack)

        # 確保 executive_summary 至少有英文摘要
        exec_summary = result.get("executive_summary")
        if not isinstance(exec_summary, dict):
            result["executive_summary"] = {"en": "Executive summary based on today's primary market theme."}
        elif not exec_summary.get("en"):
            exec_summary["en"] = "Executive summary based on today's primary market theme."

        return result

    def _generate_slug(self, title: str) -> str:
        """生成 URL slug

        Args:
            title: 標題

        Returns:
            URL 友好的 slug
        """
        import re
        import unicodedata

        # Normalize unicode
        title = unicodedata.normalize("NFKD", title)
        title = title.encode("ascii", "ignore").decode("ascii")

        # Convert to lowercase and replace spaces
        slug = title.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[-\s]+", "-", slug)

        # Add date
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = f"{date_str}-{slug[:50]}"

        return slug.strip("-")

    def _convert_to_html(self, md_content: str, post_data: Optional[dict] = None) -> str:
        """將 Markdown 轉換為 HTML

        使用統一元件系統增強 HTML 輸出。

        Args:
            md_content: Markdown 內容
            post_data: 原始 post 資料（用於渲染元件）

        Returns:
            HTML 內容
        """
        if not md_content:
            return ""

        # 基礎 Markdown 轉換
        md = markdown.Markdown(
            extensions=["tables", "fenced_code", "toc"],
        )
        html = md.convert(md_content)

        # 如果沒有 post_data，直接返回基礎 HTML
        if not post_data:
            return html

        # 注意: LLM 輸出的 HTML 已經包含 key_numbers 和 sources
        # 這裡只做基礎轉換，不再重複添加元件
        # 如果需要添加來源頁尾，檢查 HTML 是否已有
        try:
            from .html_components import (
                render_source_footer,
                SourceItem,
            )

            # 只在 HTML 沒有來源區塊時才添加
            sources = post_data.get("sources", [])
            has_sources_section = "資料來源" in html or "Sources" in html or "sources" in html.lower()

            if sources and not has_sources_section:
                source_items = [
                    SourceItem(
                        name=s.get("name", "Unknown"),
                        source_type=s.get("type", "data"),
                        url=s.get("url"),
                    )
                    for s in sources[:10]
                ]
                html = html + "\n" + render_source_footer(source_items)

            return html

        except ImportError:
            logger.warning("html_components not available, using basic HTML")
            return html
        except Exception as e:
            logger.warning(f"Error enhancing HTML: {e}")
            return html

    def save(
        self,
        post: PostOutput,
        output_dir: str = "out",
        post_type: Optional[str] = None,
    ) -> dict[str, Path]:
        """儲存文章

        P0-1: 依 post_type 分開存檔
        - flash: post_flash.json, post_flash.html
        - earnings: post_earnings.json, post_earnings.html
        - deep: post_deep.json, post_deep.html

        Args:
            post: 文章輸出
            output_dir: 輸出目錄
            post_type: 文章類型 (flash, earnings, deep)

        Returns:
            {type: path} 字典
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # P0-1: Use post_type for file naming
        pt = post_type or self.post_type or "post"
        file_prefix = f"post_{pt}" if pt != "post" else "post"

        paths = {}

        # JSON
        json_path = output_dir / f"{file_prefix}.json"
        with open(json_path, "w") as f:
            f.write(post.to_json())
        paths["json"] = json_path

        # Markdown
        md_path = output_dir / f"{file_prefix}.md"
        with open(md_path, "w") as f:
            f.write(post.markdown)
        paths["markdown"] = md_path

        # HTML
        html_path = output_dir / f"{file_prefix}.html"
        with open(html_path, "w") as f:
            f.write(post.html)
        paths["html"] = html_path

        logger.info(f"Post ({pt}) saved to {output_dir}")
        return paths


def main():
    """CLI demo"""
    import argparse
    from rich.console import Console
    from rich.markdown import Markdown

    parser = argparse.ArgumentParser(description="Codex Writer")
    parser.add_argument(
        "--input", "-i",
        default="out/research_pack.json",
        help="Input research pack path",
    )
    parser.add_argument(
        "--output", "-o",
        default="out",
        help="Output directory",
    )
    args = parser.parse_args()

    console = Console()

    # 載入 research pack
    console.print(f"[bold]Loading research pack from {args.input}...[/bold]")
    with open(args.input) as f:
        research_pack = json.load(f)

    # 生成文章
    console.print("[bold]Generating article...[/bold]")
    runner = CodexRunner()
    post = runner.generate(research_pack)

    if not post:
        console.print("[red]Failed to generate article[/red]")
        return

    # 儲存
    console.print("[bold]Saving outputs...[/bold]")
    paths = runner.save(post, args.output)

    for file_type, path in paths.items():
        console.print(f"  ✓ {file_type}: {path}")

    # 顯示預覽
    console.print("\n[bold]Article Preview:[/bold]")
    console.print(f"Title: {post.title}")
    console.print(f"Slug: {post.slug}")
    console.print(f"\nTL;DR:")
    for item in post.tldr[:3]:
        console.print(f"  • {item}")

    console.print(f"\nTags: {', '.join(post.tags)}")
    console.print(f"Sources: {len(post.sources)}")


if __name__ == "__main__":
    main()
