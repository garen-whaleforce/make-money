"""Codex CLI Writer

使用 Claude/Codex CLI 生成文章。
"""

import json
import os
import subprocess
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

    def to_dict(self) -> dict:
        return {
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
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class CodexRunner:
    """Codex CLI 執行器"""

    # Post type specific configurations
    POST_TYPE_CONFIG = {
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

    # P0 優化：各文章類型的推薦模型（成本/品質平衡）
    POST_TYPE_MODELS = {
        "flash": "gemini-3-flash-preview",    # 制式內容，用 Flash 節省成本
        "earnings": "gemini-3-flash-preview", # 結構化輸出，Flash 足夠
        "deep": "gemini-3-pro-preview",       # 深度分析，需要更強模型
    }

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
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
        self.max_tokens = max_tokens
        self.temperature = temperature
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
        if "{research_pack}" in self.prompt_template:
            return self.prompt_template.replace("{research_pack}", research_pack_json)
        return f"{self.prompt_template.rstrip()}\n\n## Research Pack 資料\n{research_pack_json}\n"

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

    def _call_litellm_api(self, prompt: str) -> Optional[dict]:
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
            client_kwargs = {"api_key": api_key, "base_url": base_url}
            if not verify_ssl:
                import httpx
                client_kwargs["http_client"] = httpx.Client(verify=False)

            client = OpenAI(**client_kwargs)

            logger.info(f"Calling LiteLLM with model: {self.model}")

            # 某些模型 (如 gpt-5) 只支援 temperature=1
            temperature = self.temperature
            if "gpt-5" in self.model.lower():
                temperature = 1.0
                logger.info(f"Model {self.model} only supports temperature=1, adjusted")

            # 根據模型調整 max_tokens (不同模型有不同上限)
            max_tokens = self.max_tokens
            model_lower = self.model.lower()
            if "gpt-4o" in model_lower and max_tokens > 16384:
                max_tokens = 16384
                logger.info(f"Model {self.model} max_tokens capped at 16384")
            elif "gpt-4" in model_lower and max_tokens > 8192:
                max_tokens = 8192
                logger.info(f"Model {self.model} max_tokens capped at 8192")

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            # 提取回應文字
            response_text = response.choices[0].message.content

            # 解析 JSON
            return self._parse_json_response(response_text)

        except ImportError:
            logger.error("openai SDK not installed. Run: pip install openai")
            return None
        except Exception as e:
            logger.error(f"LiteLLM API call failed: {e}")
            return None

    def _call_claude_api(self, prompt: str) -> Optional[dict]:
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
            return self._call_litellm_api(prompt)

        try:
            import anthropic

            # 直連 Anthropic API
            api_key = anthropic_key
            base_url = os.getenv("ANTHROPIC_BASE_URL")

            if base_url:
                client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
            else:
                client = anthropic.Anthropic(api_key=api_key)

            logger.info(f"Calling Claude API with model: {self.model}, max_tokens: {self.max_tokens}")

            # 使用 streaming 來處理長時間請求 (避免 10 分鐘超時)
            response_text = ""
            with client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system=self._get_system_prompt(),
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

        # 嘗試呼叫 API
        result = self._call_claude_api(prompt)

        if not result:
            logger.error("Failed to generate article")
            return None

        # 補充必要欄位
        result = self._fill_defaults(result, research_pack, run_id)

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
            post = PostOutput(
                meta={
                    "run_id": run_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "edition": research_pack.get("meta", {}).get("edition", "postclose"),
                    "research_pack_id": research_pack.get("meta", {}).get("run_id"),
                },
                title=result.get("title", "Untitled"),
                title_candidates=result.get("title_candidates", []),
                slug=result.get("slug", self._generate_slug(result.get("title", ""))),
                excerpt=result.get("excerpt", ""),
                tldr=result.get("tldr", []),
                sections=result.get("sections", {}),
                markdown=result.get("markdown", ""),
                html=self._convert_to_html(result.get("markdown", ""), result),
                tags=result.get("tags", []),
                tickers_mentioned=result.get("tickers_mentioned", []),
                theme=research_pack.get("primary_theme", {}),
                what_to_watch=result.get("what_to_watch", []),
                sources=result.get("sources", research_pack.get("sources", [])),
                disclosures=result.get("disclosures", {
                    "not_investment_advice": True,
                    "risk_warning": "投資有風險，請審慎評估",
                }),
            )

            return post

        except Exception as e:
            logger.error(f"Failed to build PostOutput: {e}")
            return None

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

        # 確保有候選標題
        if not result.get("title_candidates"):
            result["title_candidates"] = [
                {"title": result["title"], "style": "news", "score": 100}
            ]

        # 確保有 TL;DR
        if not result.get("tldr"):
            result["tldr"] = [
                research_pack.get("primary_event", {}).get("summary", "Summary not available")
            ]

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

        # 使用元件系統增強 HTML
        try:
            from .html_components import (
                render_card_box,
                render_source_footer,
                render_paywall_divider,
                CardItem,
                SourceItem,
            )

            enhanced_parts = []

            # 1. 如果有 key_numbers，在開頭加入卡片
            key_numbers = post_data.get("key_numbers", [])
            if key_numbers and len(key_numbers) >= 3:
                cards = [
                    CardItem(
                        value=str(kn.get("value", "")),
                        label=kn.get("label", ""),
                        sublabel=kn.get("source"),
                    )
                    for kn in key_numbers[:3]
                ]
                enhanced_parts.append(render_card_box(cards, title="三個必記數字"))

            # 2. 主要內容
            enhanced_parts.append(html)

            # 3. 檢查是否需要插入 paywall
            if "<!--members-only-->" not in html:
                # 在適當位置插入 paywall
                # 這裡只是示範，實際位置應該由 LLM 輸出控制
                pass

            # 4. 如果有 sources，加入來源頁尾
            sources = post_data.get("sources", [])
            if sources:
                source_items = [
                    SourceItem(
                        name=s.get("name", "Unknown"),
                        source_type=s.get("type", "data"),
                        url=s.get("url"),
                    )
                    for s in sources[:10]
                ]
                enhanced_parts.append(render_source_footer(source_items))

            return "\n".join(enhanced_parts)

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
