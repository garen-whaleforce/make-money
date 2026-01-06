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

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        prompt_path: str = "prompts/daily_brief.prompt.txt",
        schema_path: str = "schemas/post.schema.json",
        max_tokens: int = 16000,
        temperature: float = 0.7,
    ):
        """初始化 Codex 執行器

        Args:
            model: 使用的模型
            prompt_path: Prompt 檔案路徑
            schema_path: 輸出 Schema 路徑
            max_tokens: 最大 token 數
            temperature: Temperature 參數
        """
        self.model = os.getenv("CODEX_MODEL", model)
        self.prompt_path = Path(prompt_path)
        self.schema_path = Path(schema_path)
        self.max_tokens = max_tokens
        self.temperature = temperature

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
        return self.prompt_template.replace("{research_pack}", research_pack_json)

    def _call_claude_api(self, prompt: str) -> Optional[dict]:
        """直接呼叫 Claude API (使用 anthropic SDK 或 LiteLLM)

        Args:
            prompt: 完整 prompt

        Returns:
            解析後的 JSON 或 None
        """
        try:
            import anthropic

            # 支援 LiteLLM Proxy
            api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("LITELLM_API_KEY")
            base_url = os.getenv("LITELLM_BASE_URL")

            if base_url:
                client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
                # 使用 LiteLLM 模型
                model = os.getenv("LITELLM_MODEL", self.model)
            else:
                client = anthropic.Anthropic(api_key=api_key)
                model = self.model

            # 構建系統提示
            system_prompt = """你是一位專業的美股研究分析師。
請嚴格按照 JSON 格式輸出，包含以下欄位：
- title: 選定標題
- title_candidates: 候選標題列表 (5-12個)
- slug: URL 友好的 slug
- excerpt: 摘要 (300字內)
- tldr: 摘要重點列表 (3-6條)，在 markdown 中顯示為「摘要」標題
- sections: 各章節內容
- markdown: 完整 Markdown 內容
- tags: 標籤列表
- tickers_mentioned: 提及的股票代碼
- what_to_watch: 觀察清單 (3-8點)
- sources: 來源列表
- disclosures: 免責聲明 (必須包含 not_investment_advice: true)

輸出純 JSON，不要加 markdown code block。"""

            message = client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system=system_prompt,
            )

            # 提取回應文字
            response_text = message.content[0].text

            # 嘗試解析 JSON
            # 有時候回應會包含 ```json ... ```，需要清理
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            # 嘗試修復被截斷的 JSON
            response_text = response_text.strip()

            # 清理控制字符 (保留換行和 tab)
            import re
            response_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', response_text)

            try:
                return json.loads(response_text)
            except json.JSONDecodeError as first_error:
                # 嘗試修復常見的截斷問題
                logger.warning(f"JSON parsing failed at position {first_error.pos}, attempting fixes...")

                fixed = response_text

                # 修復策略 1: 截斷在字串中間
                # 找到最後一個完整的 key-value pair
                if fixed.count('"') % 2 != 0:
                    # 找最後一個引號的位置，截斷到那裡
                    last_quote = fixed.rfind('"')
                    if last_quote > 0:
                        # 檢查是否在 value 中間被截斷
                        before_quote = fixed[:last_quote].rstrip()
                        if before_quote.endswith(':'):
                            # key: "value 被截斷，補上引號
                            fixed = fixed + '"'
                        elif not before_quote.endswith(',') and not before_quote.endswith('{') and not before_quote.endswith('['):
                            # 可能是 "key": "val 被截斷
                            fixed = fixed + '"'

                # 修復策略 2: 補上缺失的括號
                open_braces = fixed.count('{') - fixed.count('}')
                open_brackets = fixed.count('[') - fixed.count(']')

                # 如果有未閉合的陣列或物件，先嘗試清理尾部不完整的項目
                if open_braces > 0 or open_brackets > 0:
                    # 移除尾部可能不完整的逗號
                    fixed = fixed.rstrip()
                    if fixed.endswith(','):
                        fixed = fixed[:-1]

                    # 補上括號
                    fixed += ']' * open_brackets + '}' * open_braces

                try:
                    result = json.loads(fixed)
                    logger.info("JSON repair successful")
                    return result
                except json.JSONDecodeError as second_error:
                    # 修復失敗，記錄詳細信息
                    logger.error(f"JSON repair failed: {second_error}")
                    logger.error(f"Original error position: {first_error.pos}")
                    logger.error(f"Response preview (last 500 chars): {response_text[-500:]}")

                    # 嘗試最後手段：找到最後一個完整的 JSON 物件
                    try:
                        # 找到最後一個 } 的位置，嘗試截斷
                        last_brace = fixed.rfind('}')
                        if last_brace > 0:
                            truncated = fixed[:last_brace + 1]
                            # 確保括號平衡
                            open_b = truncated.count('{') - truncated.count('}')
                            open_br = truncated.count('[') - truncated.count(']')
                            truncated += ']' * open_br + '}' * open_b
                            return json.loads(truncated)
                    except:
                        pass

                    return None

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
                html=self._convert_to_html(result.get("markdown", "")),
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

    def _convert_to_html(self, md_content: str) -> str:
        """將 Markdown 轉換為 HTML

        Args:
            md_content: Markdown 內容

        Returns:
            HTML 內容
        """
        if not md_content:
            return ""

        md = markdown.Markdown(
            extensions=["tables", "fenced_code", "toc"],
        )
        return md.convert(md_content)

    def save(
        self,
        post: PostOutput,
        output_dir: str = "out",
    ) -> dict[str, Path]:
        """儲存文章

        Args:
            post: 文章輸出
            output_dir: 輸出目錄

        Returns:
            {type: path} 字典
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        paths = {}

        # JSON
        json_path = output_dir / "post.json"
        with open(json_path, "w") as f:
            f.write(post.to_json())
        paths["json"] = json_path

        # Markdown
        md_path = output_dir / "post.md"
        with open(md_path, "w") as f:
            f.write(post.markdown)
        paths["markdown"] = md_path

        # HTML
        html_path = output_dir / "post.html"
        with open(html_path, "w") as f:
            f.write(post.html)
        paths["html"] = html_path

        logger.info(f"Post saved to {output_dir}")
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
