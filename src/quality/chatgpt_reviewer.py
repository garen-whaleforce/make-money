"""ChatGPT Pro Review Loop for Daily Brief Pipeline

設計理念：
1. ChatGPT Pro 作為「人類審稿者」審查文章
2. Claude 根據建議修正
3. 疊代直到通過 QA 或達到上限

整合到 pipeline:
- Stage 3.7: ChatGPT Pro Review Loop
- 在 LLM Review (Stage 3.6) 之後
- 在 QA (Stage 4) 之前
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from rich.console import Console

console = Console()

# ============================================================
# Configuration
# ============================================================

CHATGPT_PRO_API = os.getenv(
    "CHATGPT_PRO_API_URL",
    "http://localhost:8600"  # ChatGPT Pro API runs on gpu5090 localhost
)
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
CLAUDE_MODEL = os.getenv("CHATGPT_REVISION_MODEL", "claude-sonnet-4-5-20250514")

# ChatGPT Pro Project (must exist in ChatGPT account)
# See /app/account_project_mapping.json on gpu5090 for available projects
CHATGPT_PROJECT = os.getenv("CHATGPT_PROJECT", "daily-brief")

# Timeout settings
# Service-side timeouts:
#   - idle timeout: 300s (ChatGPT idle/waiting for 5 min)
#   - active timeout: 3600s (1 hour if still thinking/generating)
# Pipeline should wait longer than service hard timeout to get proper error
MAX_WAIT_SECONDS = 3700  # ~62 minutes (slightly longer than service 1-hour timeout)
POLL_INTERVAL = 15  # Check every 15 seconds


@dataclass
class ReviewIteration:
    """單輪審查結果"""
    iteration: int
    score: float
    passed: bool
    issues: List[str] = field(default_factory=list)
    fixes_applied: int = 0
    duration_seconds: float = 0.0


@dataclass
class ChatGPTReviewResult:
    """完整審查結果"""
    total_iterations: int
    final_passed: bool
    iterations: List[ReviewIteration] = field(default_factory=list)
    total_duration_seconds: float = 0.0


# ============================================================
# ChatGPT Pro API Client
# ============================================================

def submit_to_chatgpt_pro(prompt: str, project: str = None) -> dict:
    """提交任務到 ChatGPT Pro

    Args:
        prompt: 審查請求內容
        project: ChatGPT Project 名稱（用於分類對話）
    """
    payload = {
        "prompt": prompt,
        "project": project or CHATGPT_PROJECT,
    }
    response = requests.post(
        f"{CHATGPT_PRO_API}/chat",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def wait_for_chatgpt_result(task_id: str, max_wait: int = MAX_WAIT_SECONDS) -> dict:
    """等待 ChatGPT Pro 結果"""
    start_time = time.time()

    while time.time() - start_time < max_wait:
        wait_time = min(60, max_wait - int(time.time() - start_time))
        response = requests.get(
            f"{CHATGPT_PRO_API}/task/{task_id}",
            params={"wait": wait_time},
            timeout=wait_time + 10,
        )
        response.raise_for_status()
        result = response.json()

        status = result.get("status")
        if status == "completed":
            return result
        elif status == "failed":
            raise Exception(f"ChatGPT Pro task failed: {result.get('error')}")
        elif status == "cancelled":
            raise Exception("ChatGPT Pro task was cancelled")
        elif status == "timeout":
            raise TimeoutError(f"ChatGPT Pro service timeout: {result.get('error')}")

        console.print(f"    Status: {status}, Progress: {result.get('progress', 'unknown')}")
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"ChatGPT Pro task {task_id} timed out after {max_wait}s")


# ============================================================
# Review Prompt Builder
# ============================================================

def build_review_prompt(
    posts: Dict,
    edition_pack: Dict,
    iteration: int,
) -> str:
    """建構審查 prompt"""
    # 提取關鍵數據供驗證
    market_snapshot = edition_pack.get("meta", {}).get("market_snapshot", {})
    market_data = edition_pack.get("market_data", {})
    deep_dive_ticker = edition_pack.get("deep_dive_ticker", "")

    # 格式化 market_data 供驗證
    ticker_facts = []
    for ticker, data in list(market_data.items())[:8]:
        price = data.get("price")
        change = data.get("change_pct")
        if price:
            ticker_facts.append(f"- {ticker}: ${price:.2f} ({change:+.2f}%)")
        else:
            ticker_facts.append(f"- {ticker}: N/A")

    # 格式化文章摘要
    post_summaries = []
    for post_type, post in posts.items():
        if post is None:
            continue
        # 支援 PostOutput 物件和 dict
        if hasattr(post, 'json_data'):
            post_dict = post.json_data
        else:
            post_dict = post

        title = post_dict.get("title", "")
        excerpt = post_dict.get("excerpt", "")[:200]
        html_length = len(post_dict.get("html", ""))
        post_summaries.append(f"""
### {post_type.upper()}
- **標題**: {title}
- **摘要**: {excerpt}...
- **HTML 長度**: {html_length} 字元
""")

    prompt = f"""# Daily Brief 文章審查請求（第 {iteration} 輪）

你是一位資深財經編輯和事實查核員。請審查以下文章，確保內容正確、可信、專業。

## 審查重點

1. **數字驗證**：文章中的價格、漲跌幅是否與下方「事實來源」一致？
2. **占位符檢查**：是否有「⟦UNTRACED⟧」「待補」「TBD」「(漲幅)」等占位符？這些必須移除！
3. **邏輯一致性**：Flash → Earnings → Deep 是否講述同一個故事？
4. **語言品質**：繁體中文是否通順？
5. **投資免責**：是否有不當的投資建議？應該用條件句

## 事實來源（用於驗證）

### 市場概況
- SPY: {market_snapshot.get('spy_change', 'N/A')}
- QQQ: {market_snapshot.get('qqq_change', 'N/A')}
- 10Y: {market_snapshot.get('us10y', 'N/A')}%
- VIX: {market_snapshot.get('vix', 'N/A')}

### 個股數據（只有這些 ticker 有價格數據！）
{chr(10).join(ticker_facts)}

### 主角 Ticker: {deep_dive_ticker}

**重要：如果文章提到上述列表以外的 ticker 價格/漲跌幅，那是錯誤的！**

## 文章摘要

{''.join(post_summaries)}

## 完整文章內容

"""

    # 添加完整文章內容（限制長度）
    for post_type, post in posts.items():
        if post is None:
            continue

        if hasattr(post, 'json_data'):
            post_dict = post.json_data
        else:
            post_dict = post

        # 取關鍵欄位
        json_summary = {
            "title": post_dict.get("title"),
            "slug": post_dict.get("slug"),
            "excerpt": post_dict.get("excerpt"),
            "tldr": post_dict.get("tldr", [])[:5],
            "key_numbers": post_dict.get("key_numbers", [])[:3],
        }

        # 取 HTML 預覽
        html = post_dict.get("html", "")
        html_preview = html[:4000] + "..." if len(html) > 4000 else html

        prompt += f"""
---

### {post_type.upper()} 完整內容

**JSON 結構摘要:**
```json
{json.dumps(json_summary, ensure_ascii=False, indent=2)}
```

**HTML 預覽:**
```html
{html_preview}
```

"""

    prompt += """
---

## 請輸出審查報告

格式如下：

### 1. 總體評分 (1-10)
- Flash: X/10
- Earnings: X/10
- Deep: X/10
- **整體: X/10**

### 2. 發現的問題

#### 🔴 嚴重問題（必須修正）
- [問題] → [建議修正]

#### 🟡 一般問題（建議修正）
- [問題] → [建議修正]

### 3. 具體修正指令

對每個需要修正的地方，給出：

```
POST: flash/earnings/deep
FIELD: 欄位名稱 (如 excerpt, tldr[0], key_numbers[1])
CURRENT: "現有內容"
FIX_TO: "修正為"
```

### 4. 審查結論

回答 **PASS** 或 **FAIL**

PASS 條件：
- 無嚴重問題（紅色）
- 無占位符
- 整體評分 >= 7/10
"""

    return prompt


def build_revision_prompt(
    post_dict: Dict,
    post_type: str,
    review_result: str,
    edition_pack: Dict,
) -> str:
    """建構修正 prompt（給 Claude）"""
    market_data = edition_pack.get("market_data", {})

    # 列出可用的 ticker 數據
    available_tickers = []
    for ticker, data in market_data.items():
        price = data.get("price")
        change = data.get("change_pct")
        if price:
            available_tickers.append(f"- {ticker}: ${price:.2f} ({change:+.2f}%)")

    prompt = f"""# 文章修正請求

## 審稿者反饋

{review_result}

## 可用的 Ticker 數據（只能使用這些！）

{chr(10).join(available_tickers)}

**重要：如果某個 ticker 不在上面列表中，不要引用它的價格/漲跌幅！**

## 待修正文章

類型: {post_type.upper()}
標題: {post_dict.get('title', '')}

### 當前 JSON 內容

```json
{json.dumps(post_dict, ensure_ascii=False, indent=2)[:12000]}
```

## 修正要求

1. 根據審稿者的「具體修正指令」，逐項修改
2. **移除所有占位符**：⟦UNTRACED⟧、待補、TBD、(漲幅) 等
3. 如果某個數字無法驗證，改寫句子不使用該數字
4. 保持文章結構和風格
5. 確保 HTML 中的數字與 JSON 一致

## 輸出格式

只輸出修正後的完整 JSON，不要有其他文字。

```json
"""

    return prompt


# ============================================================
# Claude Revision
# ============================================================

def call_claude_for_revision(prompt: str) -> Optional[Dict]:
    """呼叫 Claude 進行修正"""
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=f"{LITELLM_BASE_URL}/v1",
            api_key=LITELLM_API_KEY,
        )

        response = client.chat.completions.create(
            model=CLAUDE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=12000,
            temperature=0.3,
        )

        content = response.choices[0].message.content

        # 解析 JSON
        import re
        json_match = re.search(r"```json\s*([\s\S]*?)```", content)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = content

        json_str = json_str.strip()
        if json_str.startswith("{"):
            return json.loads(json_str)

    except Exception as e:
        console.print(f"    [red]Claude revision failed: {e}[/red]")

    return None


# ============================================================
# Main Stage Function
# ============================================================

def stage_chatgpt_review(
    posts: Dict,
    edition_pack,
    max_iterations: int = 3,
    project: str = None,
) -> Tuple[Dict, ChatGPTReviewResult]:
    """Stage 3.7: ChatGPT Pro Review Loop

    Args:
        posts: Generated posts dict
        edition_pack: Edition pack (EditionPack or dict)
        max_iterations: Maximum iterations (default 3)
        project: ChatGPT Project name (default: CHATGPT_PROJECT env var)

    Returns:
        (updated_posts, review_result)
    """
    project = project or CHATGPT_PROJECT
    console.print("\n[bold cyan]Stage 3.7: ChatGPT Pro Review Loop[/bold cyan]")

    # 檢查 ChatGPT Pro API 是否可用 (使用 /tasks endpoint)
    try:
        check = requests.get(f"{CHATGPT_PRO_API}/tasks", timeout=10)
        if check.status_code != 200:
            console.print(f"  [yellow]⚠ ChatGPT Pro API not available (status={check.status_code}), skipping[/yellow]")
            return posts, ChatGPTReviewResult(total_iterations=0, final_passed=False)
    except Exception as e:
        console.print(f"  [yellow]⚠ ChatGPT Pro API check failed: {e}[/yellow]")
        return posts, ChatGPTReviewResult(total_iterations=0, final_passed=False)

    console.print(f"  Max iterations: {max_iterations}")
    console.print(f"  Project: {project}")
    console.print(f"  API: {CHATGPT_PRO_API}")
    console.print(f"  Timeout: {MAX_WAIT_SECONDS}s (service: idle=300s, active=3600s)")

    # 轉換 edition_pack 為 dict
    if hasattr(edition_pack, 'to_dict'):
        pack_dict = edition_pack.to_dict()
    else:
        pack_dict = edition_pack

    result = ChatGPTReviewResult(total_iterations=0, final_passed=False)
    start_time = time.time()
    current_posts = posts.copy()

    for iteration in range(1, max_iterations + 1):
        iter_start = time.time()
        console.print(f"\n  [bold]Iteration {iteration}/{max_iterations}[/bold]")

        # Step 1: Build review prompt
        console.print(f"    Building review prompt...")
        review_prompt = build_review_prompt(current_posts, pack_dict, iteration)
        console.print(f"    Prompt: {len(review_prompt)} chars")

        # Step 2: Submit to ChatGPT Pro
        console.print(f"    Submitting to ChatGPT Pro (project={project})...")
        try:
            submit_result = submit_to_chatgpt_pro(review_prompt, project=project)
            task_id = submit_result.get("task_id")
            account = submit_result.get("account", "unknown")
            console.print(f"    Task ID: {task_id} (account: {account})")
        except Exception as e:
            console.print(f"    [red]Submit failed: {e}[/red]")
            break

        # Step 3: Wait for result
        console.print(f"    Waiting for response (max {MAX_WAIT_SECONDS}s)...")
        try:
            chatgpt_result = wait_for_chatgpt_result(task_id)
            review_text = chatgpt_result.get("answer", "")
            console.print(f"    Response: {len(review_text)} chars")

            # Save review
            review_path = Path(f"out/review_chatgpt_r{iteration}.txt")
            review_path.write_text(review_text, encoding="utf-8")

            # Parse score and pass/fail
            passed = "PASS" in review_text.upper() and "FAIL" not in review_text.split("PASS")[0].upper()

            # Extract score (look for "整體: X/10")
            import re
            score_match = re.search(r"整體[：:]\s*(\d+(?:\.\d+)?)\s*/\s*10", review_text)
            score = float(score_match.group(1)) if score_match else 5.0

            # Count issues
            red_issues = review_text.count("🔴")
            yellow_issues = review_text.count("🟡")

            iter_result = ReviewIteration(
                iteration=iteration,
                score=score,
                passed=passed,
                issues=[f"{red_issues} 嚴重, {yellow_issues} 一般"],
                duration_seconds=time.time() - iter_start,
            )

            console.print(f"    Score: {score}/10, {'PASS ✓' if passed else 'FAIL ✗'}")
            console.print(f"    Issues: {red_issues} 嚴重, {yellow_issues} 一般")

            if passed:
                result.iterations.append(iter_result)
                result.final_passed = True
                result.total_iterations = iteration
                console.print(f"  [green]✓ PASSED at iteration {iteration}[/green]")
                break

        except Exception as e:
            console.print(f"    [red]Failed: {e}[/red]")
            break

        # Step 4: Apply revisions with Claude
        if iteration < max_iterations and not passed:
            console.print(f"    Applying revisions with Claude...")
            fixes_applied = 0

            for post_type, post in current_posts.items():
                if post is None:
                    continue

                # Get post dict
                if hasattr(post, 'json_data'):
                    post_dict = post.json_data
                else:
                    post_dict = post

                revision_prompt = build_revision_prompt(
                    post_dict, post_type, review_text, pack_dict
                )

                revised = call_claude_for_revision(revision_prompt)

                if revised:
                    # Update post
                    if hasattr(post, 'json_data'):
                        post.json_data = revised
                        post.html_content = revised.get("html", "")
                    else:
                        current_posts[post_type] = revised

                    # Save
                    json_path = Path(f"out/post_{post_type}.json")
                    json_path.write_text(json.dumps(revised, ensure_ascii=False, indent=2))

                    fixes_applied += 1
                    console.print(f"      ✓ {post_type} revised")
                else:
                    console.print(f"      ✗ {post_type} revision failed")

            iter_result.fixes_applied = fixes_applied
            result.iterations.append(iter_result)
        else:
            result.iterations.append(iter_result)

        result.total_iterations = iteration

    result.total_duration_seconds = time.time() - start_time

    # Summary
    if result.final_passed:
        console.print(f"\n  [green]✓ Review passed after {result.total_iterations} iteration(s)[/green]")
    else:
        console.print(f"\n  [yellow]⚠ Review did not pass after {result.total_iterations} iteration(s)[/yellow]")

    console.print(f"  Total duration: {result.total_duration_seconds:.1f}s")

    # Save result
    result_path = Path("out/chatgpt_review_result.json")
    result_path.write_text(json.dumps({
        "total_iterations": result.total_iterations,
        "final_passed": result.final_passed,
        "total_duration_seconds": result.total_duration_seconds,
        "iterations": [
            {
                "iteration": i.iteration,
                "score": i.score,
                "passed": i.passed,
                "issues": i.issues,
                "fixes_applied": i.fixes_applied,
                "duration_seconds": i.duration_seconds,
            }
            for i in result.iterations
        ]
    }, ensure_ascii=False, indent=2))

    return current_posts, result
