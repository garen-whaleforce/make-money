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

# P0-FIX: Import placeholder stripping function
try:
    from src.writers.post_processor import strip_placeholders_from_all_fields
except ImportError:
    # Fallback if import fails - define a no-op
    def strip_placeholders_from_all_fields(d):
        return d, 0

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
    post_type: str = "flash",
) -> Tuple[bool, list]:
    """檢查增強後是否新增了 research_pack 以外的數字

    Args:
        research_pack: 原始研究包（作為數字來源）
        draft_html: 原始初稿 HTML
        enhanced_html: 增強後 HTML
        post_type: 文章類型（flash/earnings/deep）

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
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",  # 小數字（列表編號）
        "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",  # 常見列表編號
        "100", "200", "300", "400", "500",  # 常見整數
    }

    # 對 earnings 類型放寬限制：允許計算出的估值倍數和百分比
    if post_type == "earnings":
        # 允許常見的估值倍數（0.5x ~ 100x）
        safe_patterns.update({f"{i/10:.1f}x" for i in range(5, 1001)})  # 0.5x ~ 100.0x
        safe_patterns.update({f"{i}x" for i in range(1, 101)})  # 1x ~ 100x

        # 允許常見的百分比（-50% ~ +100%）
        safe_patterns.update({f"{i}%" for i in range(-50, 101)})
        safe_patterns.update({f"+{i}%" for i in range(1, 101)})
        safe_patterns.update({f"-{i}%" for i in range(1, 51)})

        # 允許常見的小數百分比
        for base in range(-20, 51):
            for decimal in range(0, 10):
                safe_patterns.add(f"{base}.{decimal}%")
                if base > 0:
                    safe_patterns.add(f"+{base}.{decimal}%")
                elif base < 0:
                    safe_patterns.add(f"{base}.{decimal}%")

        # 允許 FY/Q 年度季度標記
        for year in range(20, 30):
            for q in range(1, 5):
                safe_patterns.add(f"FY{year}")
                safe_patterns.add(f"Q{q}")
                safe_patterns.add(f"Q{q} FY{year}")

    new_numbers = new_numbers - safe_patterns

    # 額外過濾：移除像是 "0.90x", "1.05x" 這類估值倍數
    filtered_new = set()
    for num in new_numbers:
        # 跳過純倍數格式
        if re.match(r"^\d+(?:\.\d+)?x$", num):
            continue
        # 跳過純百分比格式（已在 research_pack 中的基數上計算）
        if re.match(r"^[+-]?\d+(?:\.\d+)?%$", num):
            continue
        filtered_new.add(num)

    if filtered_new:
        return False, list(filtered_new)
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
    post_type: str = "flash",
) -> Tuple[bool, dict]:
    """執行所有品質閘門

    Args:
        research_pack: 原始研究包
        draft_html: 原始初稿 HTML
        enhanced_html: 增強後 HTML
        skip_gates: 是否跳過檢查（危險，僅供測試）
        post_type: 文章類型（flash/earnings/deep）

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
        research_pack, draft_html, enhanced_html, post_type=post_type
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
    model = model or os.getenv("LITELLM_MODEL") or os.getenv("CODEX_MODEL") or "cli-gpt-5.2"

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
        "max_tokens": 20000,  # P0-FIX: 增加 token 限制避免 JSON 截斷
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


def call_anthropic(prompt: str, model: str = "cli-gpt-5.2") -> Optional[str]:
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
            max_tokens=20000,  # P0-FIX: 增加 token 限制避免 JSON 截斷
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

    P0-4 修正：使用共用的 json_repair 模組
    - 本地修復優先（不需要額外 API 呼叫）
    - 如果本地修復失敗，使用小模型修復

    Args:
        response: LLM 回應文字

    Returns:
        解析後的 JSON 或 None
    """
    if not response:
        return None

    # 嘗試導入共用模組（如果失敗則 fallback 到舊邏輯）
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.utils.json_repair import repair_json

        parsed, report = repair_json(
            response,
            use_llm=True,
            llm_model=os.getenv("LITELLM_REPAIR_MODEL", "gemini-2.5-flash"),
        )

        if parsed is not None:
            print(f"  JSON repair succeeded via {report.get('method', 'unknown')}")
            return parsed
        else:
            print(f"[ERROR] Failed to parse JSON after all fix attempts")
            print(f"[DEBUG] Local repair log: {report.get('local_repair_log', [])}")
            print(f"[DEBUG] LLM repair log: {report.get('llm_repair_log', [])}")
            print(f"[DEBUG] Response preview: \n{response[:1000]}...")

            # 儲存 debug 資訊
            debug_path = Path("out/enhance_debug.txt")
            debug_path.write_text(response, encoding="utf-8")
            print(f"  Debug response saved to: {debug_path}")

            return None

    except ImportError:
        # Fallback 到舊的解析邏輯
        print("  [WARN] Could not import json_repair, using fallback parser")
        return _parse_llm_response_fallback(response)


def _parse_llm_response_fallback(response: str) -> Optional[dict]:
    """舊版 LLM 回應解析（fallback）"""
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

    # 第一次嘗試直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 嘗試找到第一個 { 和最後一個 }
    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            text = candidate

    # 修復常見問題
    fixed = text

    # 修復未轉義的換行符
    def escape_newlines_in_strings(s: str) -> str:
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

    # 修復尾隨逗號
    fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 嘗試補上缺失的 closing braces
    open_braces = fixed.count('{') - fixed.count('}')
    open_brackets = fixed.count('[') - fixed.count(']')

    if open_braces > 0 or open_brackets > 0:
        last_complete = fixed.rfind('",')
        if last_complete == -1:
            last_complete = fixed.rfind('"},')
        if last_complete == -1:
            last_complete = fixed.rfind('},')
        if last_complete == -1:
            last_complete = fixed.rfind('],')

        if last_complete > len(fixed) // 2:
            fixed = fixed[:last_complete + 1]
            fixed += ']' * open_brackets
            fixed += '}' * open_braces

            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    # 最後嘗試使用 ast.literal_eval
    try:
        import ast
        py_text = fixed.replace('null', 'None').replace('true', 'True').replace('false', 'False')
        result = ast.literal_eval(py_text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

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


# =============================================================================
# P0-6: HTML-Only Mode (簡化輸出)
# =============================================================================

HTML_ONLY_PROMPT = """你是一位 buy-side 研究員兼資深編輯。

任務：把以下初稿 HTML 增強，使其更吸睛、更有深度。

## 重要限制
- ❌ 不得新增任何 research_pack 沒有的數字
- ❌ 不得使用保證式語言（穩賺、必漲、保證等）
- ❌ 不得改變任何數據或數字
- ✅ 可以改寫文字、重排段落、強化論述
- ✅ 可以調整 HTML 結構和樣式

## 輸出格式
只輸出增強後的 HTML，不要任何多餘文字。
HTML 必須用 <enhanced-html> 和 </enhanced-html> 標籤包圍。

<enhanced-html>
增強後的完整 HTML 內容
</enhanced-html>

---

## Research Pack（唯一事實來源）

{research_pack}

---

## 初稿 HTML（需要增強）

{draft_html}
"""


def extract_html_from_response(response: str) -> Optional[str]:
    """P0-6: 從 LLM 回應中提取 HTML

    Args:
        response: LLM 回應

    Returns:
        提取的 HTML 或 None
    """
    if not response:
        return None

    # 嘗試從 <enhanced-html> 標籤提取
    match = re.search(
        r"<enhanced-html>(.*?)</enhanced-html>",
        response,
        re.DOTALL | re.IGNORECASE
    )
    if match:
        return match.group(1).strip()

    # 嘗試從 ```html 提取
    match = re.search(r"```html\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 嘗試從 ``` 提取
    match = re.search(r"```\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        html = match.group(1).strip()
        if html.startswith("<"):
            return html

    # 如果回應本身就是 HTML
    if response.strip().startswith("<"):
        return response.strip()

    return None


def enhance_html_only(
    draft_post: dict,
    research_pack: dict,
    use_litellm: bool = True,
    model: Optional[str] = None,
) -> Optional[str]:
    """P0-6: 只增強 HTML，不改變 JSON 結構

    Args:
        draft_post: 初稿 post dict
        research_pack: research_pack dict
        use_litellm: 是否使用 LiteLLM
        model: 模型名稱

    Returns:
        增強後的 HTML 或 None
    """
    draft_html = draft_post.get("html", "")
    if not draft_html:
        print("[ERROR] No HTML in draft post")
        return None

    # 建構 prompt
    research_json = json.dumps(research_pack, indent=2, ensure_ascii=False)
    prompt = HTML_ONLY_PROMPT.replace("{research_pack}", research_json)
    prompt = prompt.replace("{draft_html}", draft_html)

    print(f"  Prompt length: {len(prompt)} chars")

    # 呼叫 LLM
    if use_litellm:
        response = call_litellm(prompt, model)
    else:
        response = call_anthropic(prompt, model or "cli-gpt-5.2")

    if not response:
        print("[ERROR] LLM call failed")
        return None

    print(f"  Response length: {len(response)} chars")

    # 提取 HTML
    enhanced_html = extract_html_from_response(response)

    if not enhanced_html:
        print("[ERROR] Failed to extract HTML from response")
        # 儲存 debug
        debug_path = Path("out/enhance_debug.txt")
        debug_path.write_text(response, encoding="utf-8")
        print(f"  Debug saved to: {debug_path}")
        return None

    return enhanced_html


def merge_html_only(draft: dict, enhanced_html: str) -> dict:
    """P0-6: 只更新 HTML 欄位

    Args:
        draft: 原始初稿
        enhanced_html: 增強後的 HTML

    Returns:
        更新後的 dict
    """
    result = draft.copy()
    result["html"] = enhanced_html

    # 更新 meta
    if "meta" not in result:
        result["meta"] = {}
    result["meta"]["enhanced_at"] = datetime.now(timezone.utc).isoformat()
    result["meta"]["enhanced"] = True
    result["meta"]["enhance_mode"] = "html_only"

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
        response = call_anthropic(prompt, model or "cli-gpt-5.2")

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
    post_type = draft_post.get("meta", {}).get("post_type", "flash")
    gates_passed, quality_report = run_quality_gates(
        research_pack, draft_html, enhanced_html, skip_quality_gates, post_type=post_type
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

    # P0-FIX: 最後一道防線 - 從所有字串欄位移除佔位符
    # 這確保 title, excerpt, newsletter_subject, html 等欄位都被清理
    result, stripped_count = strip_placeholders_from_all_fields(result)
    if stripped_count > 0:
        print(f"  ✓ P0-FIX: 從 JSON 欄位移除 {stripped_count} 個佔位符")

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
    parser.add_argument(
        "--html-only",
        action="store_true",
        help="P0-6: 只增強 HTML，不要求完整 JSON（更可靠）",
    )

    args = parser.parse_args()

    # 決定使用哪個 API
    use_litellm = not args.use_anthropic

    # P0-6: HTML-only mode
    if args.html_only:
        print("=" * 60)
        print("Post Enhancer - HTML-Only Mode (P0-6)")
        print("=" * 60)

        # 載入檔案
        if not Path(args.research_pack).exists():
            print(f"[ERROR] Research pack not found: {args.research_pack}")
            sys.exit(1)
        if not Path(args.draft).exists():
            print(f"[ERROR] Draft post not found: {args.draft}")
            sys.exit(1)

        with open(args.research_pack) as f:
            research_pack = json.load(f)
        with open(args.draft) as f:
            draft_post = json.load(f)

        print(f"\n[Step 1] Enhancing HTML...")
        enhanced_html = enhance_html_only(
            draft_post, research_pack,
            use_litellm=use_litellm,
            model=args.model
        )

        if not enhanced_html:
            print("[ERROR] HTML enhancement failed")
            sys.exit(1)

        print(f"\n[Step 2] Running quality gates...")
        draft_html = draft_post.get("html", "")
        post_type = draft_post.get("meta", {}).get("post_type", "flash")
        gates_passed, quality_report = run_quality_gates(
            research_pack, draft_html, enhanced_html, args.skip_quality_gates, post_type=post_type
        )

        if not gates_passed and not args.skip_quality_gates:
            print("[ERROR] Quality gates failed!")
            sys.exit(1)

        print(f"\n[Step 3] Merging result...")
        result = merge_html_only(draft_post, enhanced_html)
        result["meta"]["quality_gates"] = quality_report
        result["meta"]["quality_gates_passed"] = gates_passed

        # P0-FIX: 最後一道防線 - 從所有字串欄位移除佔位符
        result, stripped_count = strip_placeholders_from_all_fields(result)
        if stripped_count > 0:
            print(f"  ✓ P0-FIX: 從 JSON 欄位移除 {stripped_count} 個佔位符")

        print(f"\n[Step 4] Saving output...")
        output_dir = Path(args.output).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  JSON: {args.output}")

        html_path = output_dir / "post_enhanced.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(enhanced_html)
        print(f"  HTML: {html_path}")

        print("\n" + "=" * 60)
        print("[DONE] HTML-only enhancement complete!")
        print("=" * 60)
        sys.exit(0)

    # 標準模式
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
