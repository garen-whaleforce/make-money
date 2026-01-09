#!/usr/bin/env python3
"""Post Enhancer - 第二次編輯增強

使用 LLM 把初稿升級成更吸睛、更有深度的版本。

使用方式：
    # 標準增強
    python scripts/enhance_post.py

    # 指定輸入輸出
    python scripts/enhance_post.py \
        --research-pack out/research_pack.json \
        --draft out/post.json \
        --output out/post_enhanced.json

    # 使用 LiteLLM
    python scripts/enhance_post.py --use-litellm
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set, Tuple

import markdown
import requests
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Configuration
# ============================================================

DEFAULT_RESEARCH_PACK = "out/research_pack.json"
DEFAULT_DRAFT_POST = "out/post.json"
DEFAULT_OUTPUT = "out/post_enhanced.json"
PROMPT_PATH = "prompts/enhance_post.prompt.txt"

# 被禁止的機構引述（避免無來源的 sell-side 引述）
BLOCKED_ATTRIBUTIONS = [
    "Morgan Stanley",
    "Goldman Sachs",
    "Goldman",
    "JPMorgan",
    "JP Morgan",
    "Citi",
    "Citigroup",
    "Barclays",
    "Bank of America",
    "BofA",
    "UBS",
    "Credit Suisse",
    "Deutsche Bank",
    "HSBC",
    "Wells Fargo",
    "Jefferies",
    "Bernstein",
    "Evercore",
    "Cowen",
    "Piper Sandler",
    "Raymond James",
    "Wedbush",
    "Oppenheimer",
    "Stifel",
    "RBC Capital",
    "KeyBanc",
    "Mizuho",
    "Nomura",
    "Macquarie",
]


# ============================================================
# Quality Gates
# ============================================================

def extract_numbers(text: str) -> Set[str]:
    """從文字中提取所有數字（包含價格、百分比、倍數等）

    Args:
        text: 輸入文字（HTML 或純文字）

    Returns:
        數字字串集合
    """
    # 移除 HTML tags
    clean_text = re.sub(r"<[^>]+>", " ", text)

    numbers = set()

    # 價格格式：$188.85, $4.6T, $230B
    prices = re.findall(r"\$[\d,]+(?:\.\d+)?[TBMK]?", clean_text)
    numbers.update(prices)

    # 百分比格式：+4.2%, -0.5%, 40%, 70.1%
    percentages = re.findall(r"[+-]?\d+(?:\.\d+)?%", clean_text)
    numbers.update(percentages)

    # 倍數格式：52.3x, 2.5x, 72.8x
    multiples = re.findall(r"\d+(?:\.\d+)?x", clean_text)
    numbers.update(multiples)

    # 日期格式：1/6, 1/8, 2026/01/05, 2026-01-05
    dates = re.findall(r"\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?", clean_text)
    numbers.update(dates)

    # 一般數字（獨立的）：2.5, 40, 350, 12000
    # 排除已經匹配過的（避免重複）
    standalone = re.findall(r"(?<![$/\d])\d+(?:\.\d+)?(?![%xTBMK\d])", clean_text)
    numbers.update(standalone)

    return numbers


def check_numbers_gate(
    research_pack: dict,
    draft_html: str,
    enhanced_html: str,
) -> Tuple[bool, list]:
    """檢查增強後是否新增了 research_pack 以外的數字

    Args:
        research_pack: 原始研究包（作為數字來源）
        draft_html: 原始初稿 HTML
        enhanced_html: 增強後 HTML

    Returns:
        (是否通過, 違規數字列表)
    """
    # 從 research_pack 提取所有數字（作為 allowlist）
    research_pack_text = json.dumps(research_pack, ensure_ascii=False)
    allowed_numbers = extract_numbers(research_pack_text)

    # 從初稿提取數字（也算允許）
    draft_numbers = extract_numbers(draft_html)
    allowed_numbers.update(draft_numbers)

    # 從增強版提取數字
    enhanced_numbers = extract_numbers(enhanced_html)

    # 找出新增的數字
    new_numbers = enhanced_numbers - allowed_numbers

    # 過濾掉一些常見的無害數字
    safe_patterns = {
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",  # 小數字（列表編號）
        "0",
    }
    new_numbers = new_numbers - safe_patterns

    if new_numbers:
        return False, list(new_numbers)
    return True, []


def check_attribution_gate(text: str) -> Tuple[bool, list]:
    """檢查是否包含被禁止的機構引述

    Args:
        text: 要檢查的文字

    Returns:
        (是否通過, 違規機構列表)
    """
    violations = []

    for institution in BLOCKED_ATTRIBUTIONS:
        # 使用 word boundary 避免誤判（如 "Morgan" 在其他上下文）
        pattern = rf"\b{re.escape(institution)}\b"
        if re.search(pattern, text, re.IGNORECASE):
            violations.append(institution)

    if violations:
        return False, violations
    return True, []


def run_quality_gates(
    research_pack: dict,
    draft_html: str,
    enhanced_html: str,
    skip_gates: bool = False,
) -> Tuple[bool, dict]:
    """執行所有品質閘門

    Args:
        research_pack: 原始研究包
        draft_html: 原始初稿 HTML
        enhanced_html: 增強後 HTML
        skip_gates: 是否跳過檢查（危險，僅供測試）

    Returns:
        (是否全部通過, 詳細報告)
    """
    report = {
        "passed": True,
        "gates": {},
        "skip_gates": skip_gates,
    }

    if skip_gates:
        print("  [WARNING] Quality gates skipped!")
        return True, report

    # Gate 1: Numbers allowlist
    numbers_passed, numbers_violations = check_numbers_gate(
        research_pack, draft_html, enhanced_html
    )
    report["gates"]["numbers_allowlist"] = {
        "passed": numbers_passed,
        "violations": numbers_violations,
    }
    if not numbers_passed:
        report["passed"] = False
        print(f"  [FAIL] Numbers gate: New numbers found: {numbers_violations}")
    else:
        print("  [PASS] Numbers gate")

    # Gate 2: Attribution blocking
    attr_passed, attr_violations = check_attribution_gate(enhanced_html)
    report["gates"]["attribution_blocking"] = {
        "passed": attr_passed,
        "violations": attr_violations,
    }
    if not attr_passed:
        report["passed"] = False
        print(f"  [FAIL] Attribution gate: Blocked institutions found: {attr_violations}")
    else:
        print("  [PASS] Attribution gate")

    return report["passed"], report


# ============================================================
# LLM Client
# ============================================================

def call_litellm(prompt: str, model: Optional[str] = None) -> Optional[str]:
    """使用 LiteLLM Proxy 呼叫 LLM

    Args:
        prompt: 完整 prompt
        model: 模型名稱

    Returns:
        LLM 回應文字或 None
    """
    base_url = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")
    api_key = os.getenv("LITELLM_API_KEY")
    model = model or os.getenv("LITELLM_MODEL") or os.getenv("CODEX_MODEL") or "claude-sonnet-4.5"

    if not api_key:
        print("[ERROR] LITELLM_API_KEY not set")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": """你是一位 buy-side 研究員兼資深編輯。
請嚴格按照 JSON 格式輸出，不要加 markdown code block。
所有數字必須來自提供的 research_pack，不可杜撰。"""
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 12000,
    }

    try:
        print(f"[INFO] Calling LiteLLM: {base_url} model={model}")
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content

    except requests.RequestException as e:
        print(f"[ERROR] LiteLLM request failed: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"[ERROR] Failed to parse LiteLLM response: {e}")
        return None


def call_anthropic(prompt: str, model: str = "claude-sonnet-4.5") -> Optional[str]:
    """使用 Anthropic API 呼叫 Claude

    Args:
        prompt: 完整 prompt
        model: 模型名稱

    Returns:
        LLM 回應文字或 None
    """
    try:
        import anthropic

        client = anthropic.Anthropic()

        message = client.messages.create(
            model=model,
            max_tokens=12000,
            messages=[{"role": "user", "content": prompt}],
            system="""你是一位 buy-side 研究員兼資深編輯。
請嚴格按照 JSON 格式輸出，不要加 markdown code block。
所有數字必須來自提供的 research_pack，不可杜撰。""",
        )

        return message.content[0].text

    except ImportError:
        print("[ERROR] anthropic SDK not installed. Run: pip install anthropic")
        return None
    except Exception as e:
        print(f"[ERROR] Anthropic API failed: {e}")
        return None


# ============================================================
# Enhancer
# ============================================================

def load_prompt_template() -> str:
    """載入增強 prompt 模板"""
    prompt_path = Path(PROMPT_PATH)
    if not prompt_path.exists():
        print(f"[ERROR] Prompt not found: {prompt_path}")
        sys.exit(1)

    with open(prompt_path) as f:
        return f.read()


def build_prompt(template: str, research_pack: dict, draft_post: dict) -> str:
    """建構完整 prompt

    Args:
        template: Prompt 模板
        research_pack: 研究包資料
        draft_post: 初稿內容

    Returns:
        完整 prompt
    """
    research_pack_json = json.dumps(research_pack, indent=2, ensure_ascii=False)
    draft_post_json = json.dumps(draft_post, indent=2, ensure_ascii=False)

    prompt = template.replace("{research_pack}", research_pack_json)
    prompt = prompt.replace("{draft_post}", draft_post_json)

    return prompt


def parse_llm_response(response: str) -> Optional[dict]:
    """解析 LLM 回應

    P0-3 修正：
    - 加入容錯機制，不要因為一點 JSON 問題就整個失敗
    - 借鑒 codex_runner.py 的修復策略

    Args:
        response: LLM 回應文字

    Returns:
        解析後的 JSON 或 None
    """
    if not response:
        return None

    # ===== Step 1: 清理 markdown code block =====
    text = response.strip()

    # 移除 markdown code fence
    if "```json" in text:
        parts = text.split("```json")
        if len(parts) > 1:
            text = parts[1].split("```")[0]
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].split("```")[0]

    text = text.strip()

    # ===== Step 2: 第一次嘗試直接解析 =====
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass  # 繼續嘗試修復

    # ===== Step 3: 嘗試找到第一個 { 和最後一個 } =====
    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            text = candidate  # 用這個繼續修復

    # ===== Step 4: 修復常見問題 =====
    fixed = text

    # 4a: 修復未轉義的換行符（JSON 字串中不允許）
    # 找出字串內容並轉義換行
    def escape_newlines_in_strings(s: str) -> str:
        """轉義 JSON 字串中的換行符"""
        result = []
        in_string = False
        escape_next = False
        i = 0
        while i < len(s):
            char = s[i]
            if escape_next:
                result.append(char)
                escape_next = False
            elif char == '\\':
                result.append(char)
                escape_next = True
            elif char == '"':
                result.append(char)
                in_string = not in_string
            elif in_string and char == '\n':
                result.append('\\n')
            elif in_string and char == '\t':
                result.append('\\t')
            else:
                result.append(char)
            i += 1
        return ''.join(result)

    fixed = escape_newlines_in_strings(fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 4b: 修復尾隨逗號
    fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 4c: 嘗試補上缺失的 closing braces
    open_braces = fixed.count('{') - fixed.count('}')
    open_brackets = fixed.count('[') - fixed.count(']')

    if open_braces > 0 or open_brackets > 0:
        # 移除最後可能的不完整內容（截斷）
        # 找最後一個完整的 key-value pair
        last_complete = fixed.rfind('",')
        if last_complete == -1:
            last_complete = fixed.rfind('"},')
        if last_complete == -1:
            last_complete = fixed.rfind('},')
        if last_complete == -1:
            last_complete = fixed.rfind('],')

        if last_complete > len(fixed) // 2:  # 至少保留一半
            fixed = fixed[:last_complete + 1]
            # 補上 closing
            fixed += ']' * open_brackets
            fixed += '}' * open_braces

            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    # ===== Step 5: 最後嘗試使用 ast.literal_eval（更寬鬆） =====
    try:
        import ast
        # 把 JSON null/true/false 轉成 Python
        py_text = fixed.replace('null', 'None').replace('true', 'True').replace('false', 'False')
        result = ast.literal_eval(py_text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # ===== 全部失敗 =====
    print(f"[ERROR] Failed to parse JSON after all fix attempts")
    print(f"[DEBUG] Response preview: \n{text[:1000]}...")
    return None


def merge_enhanced(draft: dict, enhanced: dict) -> dict:
    """合併增強結果到原始 draft

    Args:
        draft: 原始初稿
        enhanced: 增強後的內容

    Returns:
        合併後的結果
    """
    result = draft.copy()

    # 覆蓋/新增增強欄位
    enhanced_fields = [
        "title",
        "title_candidates",
        "newsletter_subject",
        "slug",
        "excerpt",
        "tldr",
        "hero",
        "consensus_vs_reality",
        "industry_impact",
        "valuation_bridge",
        "timeline",
        "contrarian_view",
        "peer_takeaways",
        "sections",
        "markdown",
        "what_to_watch",
    ]

    for field in enhanced_fields:
        if field in enhanced and enhanced[field]:
            result[field] = enhanced[field]

    # 更新 meta
    if "meta" not in result:
        result["meta"] = {}
    result["meta"]["enhanced_at"] = datetime.now(timezone.utc).isoformat()
    result["meta"]["enhanced"] = True

    # 轉換 markdown to html
    if result.get("markdown"):
        md = markdown.Markdown(extensions=["tables", "fenced_code", "toc"])
        result["html"] = md.convert(result["markdown"])

    return result


def enhance_post(
    research_pack_path: str,
    draft_path: str,
    output_path: str,
    use_litellm: bool = True,
    model: Optional[str] = None,
    skip_quality_gates: bool = False,
) -> bool:
    """執行文章增強

    Args:
        research_pack_path: research_pack.json 路徑
        draft_path: 初稿 post.json 路徑
        output_path: 輸出路徑
        use_litellm: 是否使用 LiteLLM
        model: 模型名稱
        skip_quality_gates: 是否跳過品質檢查（危險）

    Returns:
        是否成功
    """
    print("=" * 60)
    print("Post Enhancer - 第二次編輯增強")
    print("=" * 60)

    # 載入檔案
    print(f"\n[Step 1] Loading files...")

    if not Path(research_pack_path).exists():
        print(f"[ERROR] Research pack not found: {research_pack_path}")
        return False

    if not Path(draft_path).exists():
        print(f"[ERROR] Draft post not found: {draft_path}")
        return False

    with open(research_pack_path) as f:
        research_pack = json.load(f)
    print(f"  Loaded research_pack: {research_pack_path}")

    with open(draft_path) as f:
        draft_post = json.load(f)
    print(f"  Loaded draft: {draft_path}")

    # 建構 prompt
    print(f"\n[Step 2] Building prompt...")
    template = load_prompt_template()
    prompt = build_prompt(template, research_pack, draft_post)
    print(f"  Prompt length: {len(prompt)} chars")

    # 呼叫 LLM
    print(f"\n[Step 3] Calling LLM...")
    if use_litellm:
        response = call_litellm(prompt, model)
    else:
        response = call_anthropic(prompt, model or "claude-sonnet-4.5")

    if not response:
        print("[ERROR] LLM call failed")
        return False

    print(f"  Response length: {len(response)} chars")

    # 解析回應
    print(f"\n[Step 4] Parsing response...")
    enhanced = parse_llm_response(response)

    if not enhanced:
        # 儲存原始回應以供除錯
        debug_path = Path(output_path).parent / "enhance_debug.txt"
        with open(debug_path, "w") as f:
            f.write(response)
        print(f"  Debug response saved to: {debug_path}")
        return False

    print(f"  Parsed successfully")

    # 合併結果
    print(f"\n[Step 5] Merging enhanced content...")
    result = merge_enhanced(draft_post, enhanced)

    # 執行品質檢查
    print(f"\n[Step 6] Running quality gates...")
    draft_html = draft_post.get("html", "")
    enhanced_html = result.get("html", "")
    gates_passed, quality_report = run_quality_gates(
        research_pack, draft_html, enhanced_html, skip_quality_gates
    )

    # 儲存品質報告到結果
    result["meta"]["quality_gates"] = quality_report

    if not gates_passed:
        print("\n[ERROR] Quality gates failed! Enhancement blocked.")
        print("  Use --skip-quality-gates to bypass (危險)")

        # 仍然儲存結果以供除錯，但標記為失敗
        result["meta"]["quality_gates_passed"] = False

        # 儲存除錯檔案
        debug_path = Path(output_path).parent / "enhance_failed.json"
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  Debug output saved to: {debug_path}")
        return False

    result["meta"]["quality_gates_passed"] = True

    # 儲存
    print(f"\n[Step 7] Saving output...")
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  JSON: {output_path}")

    # Markdown
    md_path = output_dir / "post_enhanced.md"
    if result.get("markdown"):
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(result["markdown"])
        print(f"  Markdown: {md_path}")

    # HTML
    html_path = output_dir / "post_enhanced.html"
    if result.get("html"):
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(result["html"])
        print(f"  HTML: {html_path}")

    # 顯示摘要
    print(f"\n[Summary]")
    print(f"  Title: {result.get('title', 'N/A')[:60]}...")
    print(f"  Newsletter Subject: {result.get('newsletter_subject', 'N/A')[:50]}...")
    if result.get("hero"):
        print(f"  Hero Thesis: {result['hero'].get('thesis', 'N/A')[:50]}...")
    print(f"  Title Candidates: {len(result.get('title_candidates', []))}")
    print(f"  TL;DR Points: {len(result.get('tldr', []))}")
    print(f"  Timeline Events: {len(result.get('timeline', []))}")
    print(f"  Peer Takeaways: {len(result.get('peer_takeaways', []))}")

    print("\n" + "=" * 60)
    print("[DONE] Enhancement complete!")
    print("=" * 60)

    return True


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Post Enhancer - 第二次編輯增強",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 使用預設路徑
  python scripts/enhance_post.py

  # 指定檔案
  python scripts/enhance_post.py \\
      --research-pack out/research_pack.json \\
      --draft out/post.json \\
      --output out/post_enhanced.json

  # 使用 Anthropic API
  python scripts/enhance_post.py --use-anthropic
        """
    )

    parser.add_argument(
        "--research-pack", "-r",
        default=DEFAULT_RESEARCH_PACK,
        help="Research pack JSON path",
    )
    parser.add_argument(
        "--draft", "-d",
        default=DEFAULT_DRAFT_POST,
        help="Draft post JSON path",
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help="Output JSON path",
    )
    parser.add_argument(
        "--use-litellm",
        action="store_true",
        default=True,
        help="Use LiteLLM Proxy (default)",
    )
    parser.add_argument(
        "--use-anthropic",
        action="store_true",
        help="Use Anthropic API instead of LiteLLM",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Model name override",
    )
    parser.add_argument(
        "--skip-quality-gates",
        action="store_true",
        help="跳過品質檢查（危險，僅供測試）",
    )

    args = parser.parse_args()

    # 決定使用哪個 API
    use_litellm = not args.use_anthropic

    success = enhance_post(
        research_pack_path=args.research_pack,
        draft_path=args.draft,
        output_path=args.output,
        use_litellm=use_litellm,
        model=args.model,
        skip_quality_gates=args.skip_quality_gates,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
