#!/usr/bin/env python3
"""Post Iteration with ChatGPT Pro Review

設計理念：
1. 生成三篇文章後，打包給 ChatGPT Pro 審查
2. ChatGPT Pro 作為「人類審稿者」檢查：
   - 數字是否正確、可追溯
   - 內容是否合理、有邏輯
   - 語言是否通順
   - 是否有占位符或錯誤
3. 將 ChatGPT Pro 的建議給 Claude 修正
4. 可設定疊代次數（直到通過或達到上限）

使用方式：
    # 基本使用（默認 2 次疊代）
    python scripts/iterate_with_chatgpt.py

    # 指定疊代次數
    python scripts/iterate_with_chatgpt.py --max-iterations 3

    # 只審查不修正（dry-run）
    python scripts/iterate_with_chatgpt.py --review-only

    # 跳過生成，只審查現有文章
    python scripts/iterate_with_chatgpt.py --skip-generate
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Configuration
# ============================================================

CHATGPT_PRO_API = os.getenv(
    "CHATGPT_PRO_API_URL",
    "https://chatgpt-pro.gpu5090.whaleforce.dev"
)
CHATGPT_PRO_PROJECT = "daily-brief-review"
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")
CLAUDE_MODEL = os.getenv("LITELLM_MODEL", "cli-gpt-5.2")

MAX_WAIT_SECONDS = 300  # ChatGPT Pro 最長等待時間
POLL_INTERVAL = 5  # 輪詢間隔


# ============================================================
# ChatGPT Pro API Client
# ============================================================

def submit_to_chatgpt_pro(prompt: str, project: str = CHATGPT_PRO_PROJECT) -> dict:
    """提交任務到 ChatGPT Pro

    Args:
        prompt: 審查 prompt
        project: ChatGPT Pro project 名稱

    Returns:
        API response dict
    """
    response = requests.post(
        f"{CHATGPT_PRO_API}/chat",
        json={"prompt": prompt, "project": project},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def wait_for_chatgpt_result(task_id: str, max_wait: int = MAX_WAIT_SECONDS) -> dict:
    """等待 ChatGPT Pro 結果

    Args:
        task_id: 任務 ID
        max_wait: 最長等待秒數

    Returns:
        任務結果 dict
    """
    start_time = time.time()

    while time.time() - start_time < max_wait:
        # 使用 wait 參數，讓 API 自己等待
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

        print(f"  Status: {status}, Progress: {result.get('progress', 'unknown')}")
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"ChatGPT Pro task {task_id} timed out after {max_wait}s")


# ============================================================
# Review Prompt Builder
# ============================================================

def build_review_prompt(
    posts: dict,
    qa_report: dict,
    edition_pack: dict,
    iteration: int,
) -> str:
    """建構審查 prompt

    Args:
        posts: 三篇文章 {post_type: post_dict}
        qa_report: QA 報告
        edition_pack: 版本資料包（用於事實驗證）
        iteration: 當前疊代次數

    Returns:
        審查 prompt 字串
    """
    # 提取關鍵數據供驗證
    market_snapshot = edition_pack.get("meta", {}).get("market_snapshot", {})
    market_data = edition_pack.get("market_data", {})
    deep_dive_ticker = edition_pack.get("deep_dive_ticker", "")

    # 格式化 market_data 供驗證
    ticker_facts = []
    for ticker, data in list(market_data.items())[:6]:  # 最多 6 個
        price = data.get("price")
        change = data.get("change_pct")
        ticker_facts.append(f"- {ticker}: ${price:.2f} ({change:+.2f}%)" if price else f"- {ticker}: N/A")

    # 提取 QA 問題
    qa_errors = qa_report.get("errors", [])[:10]  # 最多 10 個
    qa_warnings = qa_report.get("warnings", [])[:5]

    # 格式化文章摘要
    post_summaries = []
    for post_type, post in posts.items():
        if post is None:
            continue
        title = post.get("title", "")
        excerpt = post.get("excerpt", "")[:200]
        html_length = len(post.get("html", ""))
        post_summaries.append(f"""
### {post_type.upper()}
- **標題**: {title}
- **摘要**: {excerpt}...
- **HTML 長度**: {html_length} 字元
""")

    prompt = f"""# Daily Brief 文章審查請求（第 {iteration} 輪）

你是一位資深財經編輯和事實查核員。請審查以下三篇文章，確保內容正確、可信、專業。

## 審查重點

1. **數字驗證**：文章中的價格、漲跌幅、市值等數字是否與下方「事實來源」一致？
2. **邏輯一致性**：三篇文章的觀點是否連貫？Flash → Earnings → Deep 是否講述同一個故事？
3. **占位符檢查**：是否有「數據」「⟦UNTRACED⟧」「TBD」等占位符？
4. **語言品質**：繁體中文是否通順？是否有翻譯腔或用詞不當？
5. **投資免責**：是否有不當的投資建議（如「應該買入」）？應該用條件句（如「若...則...」）

## 事實來源（用於驗證）

### 市場概況
- SPY: {market_snapshot.get('spy_change', 'N/A')}
- QQQ: {market_snapshot.get('qqq_change', 'N/A')}
- 10Y: {market_snapshot.get('us10y', 'N/A')}
- VIX: {market_snapshot.get('vix', 'N/A')}

### 個股數據
{chr(10).join(ticker_facts)}

### 主角 Ticker: {deep_dive_ticker}

## QA 系統發現的問題

### Errors
{chr(10).join(f'- {e}' for e in qa_errors) if qa_errors else '- 無'}

### Warnings
{chr(10).join(f'- {w}' for w in qa_warnings) if qa_warnings else '- 無'}

## 文章摘要

{''.join(post_summaries)}

## 完整文章內容

請仔細閱讀以下三篇完整文章：

"""

    # 添加完整文章內容（限制長度避免 token 超限）
    for post_type, post in posts.items():
        if post is None:
            continue

        # 取 JSON 的關鍵欄位
        json_summary = {
            "title": post.get("title"),
            "slug": post.get("slug"),
            "excerpt": post.get("excerpt"),
            "tldr": post.get("tldr", [])[:5],
            "key_numbers": post.get("key_numbers", [])[:3],
        }

        # 取 HTML 的前 3000 字元（預覽區）
        html = post.get("html", "")
        html_preview = html[:3000] + "..." if len(html) > 3000 else html

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

請按以下格式輸出：

### 1. 總體評分 (1-10)
- Flash: X/10
- Earnings: X/10
- Deep: X/10

### 2. 發現的問題（按嚴重程度排序）

#### 🔴 嚴重問題（必須修正）
- [問題描述] → [建議修正方式]

#### 🟡 一般問題（建議修正）
- [問題描述] → [建議修正方式]

#### 🟢 小問題（可選修正）
- [問題描述] → [建議修正方式]

### 3. 具體修正建議

對每篇文章給出具體的修正指令，格式如下：

```
POST_TYPE: flash
FIELD: excerpt
CURRENT: "現有內容..."
SUGGESTED: "建議修改為..."
REASON: "修改原因"
```

### 4. 是否通過審查？

回答 PASS 或 FAIL，並說明原因。

PASS 條件：
- 無嚴重問題（紅色）
- 一般問題不超過 3 個
- 總體評分 >= 7/10
"""

    return prompt


def build_revision_prompt(
    posts: dict,
    review_result: str,
    post_type: str,
) -> str:
    """建構修正 prompt（給 Claude）

    Args:
        posts: 三篇文章
        review_result: ChatGPT Pro 的審查結果
        post_type: 要修正的文章類型

    Returns:
        修正 prompt
    """
    post = posts.get(post_type, {})
    if not post:
        return ""

    prompt = f"""# 文章修正請求

## 審稿者反饋

以下是審稿者（ChatGPT Pro）對文章的審查結果：

{review_result}

## 待修正文章

類型: {post_type.upper()}
標題: {post.get('title', '')}

### 當前 JSON 內容

```json
{json.dumps(post, ensure_ascii=False, indent=2)[:8000]}
```

## 修正要求

1. 根據審稿者的「具體修正建議」，逐項修改文章
2. 修正所有「嚴重問題」和「一般問題」
3. 保持文章的整體結構和風格
4. 確保所有數字與原始資料一致
5. 移除任何占位符

## 輸出格式

請輸出完整的修正後 JSON，格式與輸入相同。只輸出 JSON，不要有其他文字。

```json
"""

    return prompt


# ============================================================
# Claude API Client (for revisions)
# ============================================================

def call_claude_for_revision(prompt: str) -> Optional[dict]:
    """呼叫 Claude 進行修正

    Args:
        prompt: 修正 prompt

    Returns:
        修正後的 post dict 或 None
    """
    try:
        import litellm

        response = litellm.completion(
            model=CLAUDE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8000,
            temperature=0.3,
            base_url=LITELLM_BASE_URL,
        )

        content = response.choices[0].message.content

        # 解析 JSON
        # 嘗試提取 ```json ... ``` 區塊
        import re
        json_match = re.search(r"```json\s*([\s\S]*?)```", content)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 嘗試直接解析
            json_str = content

        # 清理並解析
        json_str = json_str.strip()
        if json_str.startswith("{"):
            return json.loads(json_str)

    except Exception as e:
        print(f"  [ERROR] Claude revision failed: {e}")

    return None


# ============================================================
# Main Iteration Loop
# ============================================================

def load_posts() -> dict:
    """載入現有文章"""
    posts = {}
    for post_type in ["flash", "earnings", "deep"]:
        json_path = Path(f"out/post_{post_type}.json")
        if json_path.exists():
            with open(json_path, "r") as f:
                posts[post_type] = json.load(f)
    return posts


def load_qa_report() -> dict:
    """載入 QA 報告"""
    path = Path("out/quality_report.json")
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {}


def load_edition_pack() -> dict:
    """載入 edition_pack"""
    path = Path("out/edition_pack.json")
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_post(post_type: str, post: dict):
    """儲存修正後的文章"""
    json_path = Path(f"out/post_{post_type}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Saved {json_path}")


def run_iteration(
    iteration: int,
    posts: dict,
    qa_report: dict,
    edition_pack: dict,
    review_only: bool = False,
) -> tuple[dict, bool]:
    """執行一輪審查+修正

    Args:
        iteration: 當前疊代次數
        posts: 文章 dict
        qa_report: QA 報告
        edition_pack: 版本資料包
        review_only: 只審查不修正

    Returns:
        (updated_posts, passed)
    """
    print(f"\n{'='*60}")
    print(f"Iteration {iteration}: ChatGPT Pro Review")
    print(f"{'='*60}")

    # Step 1: 建構審查 prompt
    print("\n[1/4] Building review prompt...")
    review_prompt = build_review_prompt(posts, qa_report, edition_pack, iteration)
    print(f"  Prompt length: {len(review_prompt)} chars")

    # Step 2: 提交給 ChatGPT Pro
    print("\n[2/4] Submitting to ChatGPT Pro...")
    try:
        submit_result = submit_to_chatgpt_pro(review_prompt)
        task_id = submit_result.get("task_id")
        print(f"  Task ID: {task_id}")
        print(f"  Chat URL: {submit_result.get('chat_url', 'pending...')}")
    except Exception as e:
        print(f"  [ERROR] Failed to submit: {e}")
        return posts, False

    # Step 3: 等待結果
    print("\n[3/4] Waiting for ChatGPT Pro response...")
    try:
        result = wait_for_chatgpt_result(task_id)
        review_result = result.get("answer", "")
        print(f"  Response length: {len(review_result)} chars")

        # 儲存審查結果
        review_path = Path(f"out/review_iteration_{iteration}.txt")
        review_path.write_text(review_result, encoding="utf-8")
        print(f"  Saved to: {review_path}")

        # 檢查是否通過
        passed = "PASS" in review_result.upper() and "FAIL" not in review_result.upper()
        print(f"  Review result: {'PASS ✓' if passed else 'FAIL ✗'}")

        if passed or review_only:
            return posts, passed

    except Exception as e:
        print(f"  [ERROR] Failed to get result: {e}")
        return posts, False

    # Step 4: 根據建議修正（使用 Claude）
    print("\n[4/4] Applying revisions with Claude...")
    updated_posts = posts.copy()

    for post_type in ["flash", "earnings", "deep"]:
        if post_type not in posts or posts[post_type] is None:
            continue

        print(f"\n  Revising {post_type}...")
        revision_prompt = build_revision_prompt(posts, review_result, post_type)

        if not revision_prompt:
            continue

        revised_post = call_claude_for_revision(revision_prompt)

        if revised_post:
            updated_posts[post_type] = revised_post
            save_post(post_type, revised_post)
            print(f"    ✓ {post_type} revised and saved")
        else:
            print(f"    ✗ {post_type} revision failed, keeping original")

    return updated_posts, False


def main():
    parser = argparse.ArgumentParser(description="Iterate posts with ChatGPT Pro review")
    parser.add_argument(
        "--max-iterations", "-n",
        type=int,
        default=2,
        help="Maximum iteration count (default: 2)"
    )
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="Only review, don't apply revisions"
    )
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Skip generation, use existing posts"
    )
    parser.add_argument(
        "--posts", "-p",
        type=str,
        help="Comma-separated post types to review (default: all)"
    )
    args = parser.parse_args()

    print("="*60)
    print("Post Iteration with ChatGPT Pro Review")
    print("="*60)
    print(f"Max iterations: {args.max_iterations}")
    print(f"Review only: {args.review_only}")
    print(f"ChatGPT Pro API: {CHATGPT_PRO_API}")
    print(f"Claude Model: {CLAUDE_MODEL}")

    # Step 0: 生成文章（如果需要）
    if not args.skip_generate:
        print("\n[Step 0] Generating posts...")
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "src.pipeline.run_daily", "--mode", "test", "--skip-publish"],
            capture_output=False,
        )
        if result.returncode != 0:
            print("[ERROR] Post generation failed")
            sys.exit(1)

    # 載入資料
    posts = load_posts()
    qa_report = load_qa_report()
    edition_pack = load_edition_pack()

    if not posts:
        print("[ERROR] No posts found in out/")
        sys.exit(1)

    print(f"\nLoaded {len(posts)} posts: {list(posts.keys())}")
    print(f"QA overall: {'PASS' if qa_report.get('overall_passed') else 'FAIL'}")

    # 過濾指定的 post types
    if args.posts:
        filter_types = [p.strip() for p in args.posts.split(",")]
        posts = {k: v for k, v in posts.items() if k in filter_types}
        print(f"Filtered to: {list(posts.keys())}")

    # 疊代審查+修正
    for i in range(1, args.max_iterations + 1):
        posts, passed = run_iteration(
            iteration=i,
            posts=posts,
            qa_report=qa_report,
            edition_pack=edition_pack,
            review_only=args.review_only,
        )

        if passed:
            print(f"\n{'='*60}")
            print(f"✓ PASSED at iteration {i}")
            print(f"{'='*60}")
            break

        if i < args.max_iterations:
            # 重新執行 QA
            print(f"\n  Re-running QA for iteration {i+1}...")
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "src.pipeline.run_daily", "--skip-ingest", "--skip-pack", "--skip-write"],
                capture_output=True,
            )
            qa_report = load_qa_report()

    else:
        print(f"\n{'='*60}")
        print(f"✗ Did not pass after {args.max_iterations} iterations")
        print(f"{'='*60}")

    # 最終報告
    print("\n[Final Report]")
    for post_type, post in posts.items():
        if post:
            print(f"  {post_type}: {post.get('title', 'N/A')[:50]}...")

    # 儲存疊代歷史
    history_path = Path("out/iteration_history.json")
    history = {
        "timestamp": datetime.now().isoformat(),
        "max_iterations": args.max_iterations,
        "final_posts": list(posts.keys()),
        "passed": passed if 'passed' in dir() else False,
    }
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2))
    print(f"\nIteration history saved to: {history_path}")


if __name__ == "__main__":
    main()
