"""
LLM-based Article Reviewer using cli-gpt-5.2

This module provides automated article review and correction using LiteLLM.
It's designed to run after QA gate and before publishing.

Flow:
1. Load generated articles
2. Send to cli-gpt-5.2 for review
3. Parse review results
4. Apply corrections automatically
5. Re-verify until PASS or max iterations

Usage:
    from src.quality.llm_reviewer import stage_review
    posts = stage_review(posts, edition_pack, max_iterations=3)
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

import requests
from dotenv import load_dotenv
from rich.console import Console

# Load environment variables
load_dotenv()

console = Console()

# Configuration
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
REVIEW_MODEL = os.getenv("REVIEW_MODEL", "cli-gpt-5.2")
REVIEW_TIMEOUT = int(os.getenv("REVIEW_TIMEOUT", "600"))
MAX_REVIEW_ITERATIONS = int(os.getenv("MAX_REVIEW_ITERATIONS", "3"))
REVIEW_PASS_THRESHOLD = 7  # Score >= 7 is considered PASS


@dataclass
class ReviewResult:
    """Single review iteration result"""
    iteration: int
    post_type: str
    score: int
    verdict: str  # PASS or FAIL
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)
    elapsed_time: float = 0.0
    raw_response: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ReviewHistory:
    """Complete review history for a post"""
    post_type: str
    iterations: List[ReviewResult] = field(default_factory=list)
    final_passed: bool = False
    total_fixes: int = 0

    def to_dict(self) -> Dict:
        return {
            "post_type": self.post_type,
            "iterations": [r.to_dict() for r in self.iterations],
            "final_passed": self.final_passed,
            "total_fixes": self.total_fixes,
        }


def _call_llm(prompt: str, timeout: int = REVIEW_TIMEOUT) -> Tuple[bool, str]:
    """Call LiteLLM API with the review model.

    Returns:
        (success, response_content)
    """
    if not LITELLM_API_KEY:
        return False, "LITELLM_API_KEY not configured"

    try:
        response = requests.post(
            f"{LITELLM_BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {LITELLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": REVIEW_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 3000,
            },
            timeout=timeout,
            verify=False,  # Disable SSL verification for internal services
        )

        result = response.json()
        if "error" in result:
            return False, f"API Error: {result['error']}"

        content = result["choices"][0]["message"]["content"]
        return True, content

    except requests.exceptions.Timeout:
        return False, f"Request timed out after {timeout}s"
    except Exception as e:
        return False, f"Request failed: {str(e)}"


def _build_review_prompt(post_type: str, markdown: str, market_data: Dict) -> str:
    """Build the review prompt for a post."""
    return f"""你是專業金融新聞編輯，請審核這篇 {post_type} 文章。

## 文章內容
{markdown[:7000]}

## 可用市場數據
{json.dumps(market_data, indent=2)}

## 審核項目
1. 數據完整性：是否有空值（⟦UNTRACED⟧、數據待補、—）
2. 措辭準確性：是否避免過度武斷（唯一、必然、肯定會）
3. 邏輯一致性：數字統計是否一致
4. 來源標註：重要數據是否有來源
5. 中英對齊：雙語摘要是否一致

## 輸出格式（JSON）
{{
  "score": 1-10,
  "verdict": "PASS/FAIL",
  "issues": ["問題1", "問題2"],
  "fixes": [
    {{"find": "原文片段", "replace": "修正後", "reason": "原因"}}
  ],
  "summary": "一句話總結"
}}

注意：
- Score >= 7 且無嚴重問題視為 PASS
- fixes 中的 find 必須是文章中可精確匹配的字串
"""


def _parse_review_response(response: str) -> Optional[Dict]:
    """Parse the LLM review response as JSON."""
    # Try to extract JSON from response
    try:
        # Look for JSON block
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # Try direct JSON parse
        return json.loads(response)
    except json.JSONDecodeError:
        # Try to find JSON-like structure
        start = response.find('{')
        end = response.rfind('}') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(response[start:end])
            except json.JSONDecodeError:
                pass
    return None


def _apply_fixes(post_data: Dict, fixes: List[Dict]) -> Tuple[Dict, List[str]]:
    """Apply fixes to post data.

    Returns:
        (updated_post_data, list_of_applied_fixes)
    """
    applied = []
    markdown = post_data.get("markdown", "")
    html = post_data.get("html", "")
    exec_summary = post_data.get("executive_summary", {})

    for fix in fixes:
        find_str = fix.get("find", "")
        replace_str = fix.get("replace", "")
        reason = fix.get("reason", "")

        if not find_str or find_str == replace_str:
            continue

        # Apply to markdown
        if find_str in markdown:
            markdown = markdown.replace(find_str, replace_str)
            applied.append(f"[markdown] {find_str[:50]}... -> {replace_str[:50]}...")

        # Apply to HTML
        if find_str in html:
            html = html.replace(find_str, replace_str)

        # Apply to executive summary
        for lang in ["zh", "en"]:
            if lang in exec_summary and find_str in exec_summary[lang]:
                exec_summary[lang] = exec_summary[lang].replace(find_str, replace_str)
                applied.append(f"[summary_{lang}] {find_str[:30]}...")

    post_data["markdown"] = markdown
    post_data["html"] = html
    post_data["executive_summary"] = exec_summary

    return post_data, applied


def review_single_post(
    post_type: str,
    post_data: Dict,
    market_data: Dict,
    iteration: int = 1,
) -> ReviewResult:
    """Review a single post and return result.

    Args:
        post_type: Type of post (flash, earnings, deep)
        post_data: Post JSON data
        market_data: Market data for validation
        iteration: Current iteration number

    Returns:
        ReviewResult with score, verdict, and fixes
    """
    start_time = time.time()

    markdown = post_data.get("markdown", "")
    if not markdown:
        return ReviewResult(
            iteration=iteration,
            post_type=post_type,
            score=0,
            verdict="FAIL",
            issues=["No markdown content found"],
        )

    # Build and send review prompt
    prompt = _build_review_prompt(post_type, markdown, market_data)
    success, response = _call_llm(prompt)

    elapsed = time.time() - start_time

    if not success:
        return ReviewResult(
            iteration=iteration,
            post_type=post_type,
            score=0,
            verdict="FAIL",
            issues=[f"LLM call failed: {response}"],
            elapsed_time=elapsed,
            raw_response=response,
        )

    # Parse response
    parsed = _parse_review_response(response)
    if not parsed:
        return ReviewResult(
            iteration=iteration,
            post_type=post_type,
            score=0,
            verdict="FAIL",
            issues=["Failed to parse LLM response"],
            elapsed_time=elapsed,
            raw_response=response,
        )

    score = parsed.get("score", 0)
    verdict = parsed.get("verdict", "FAIL")

    # Override verdict based on score threshold
    if score >= REVIEW_PASS_THRESHOLD and verdict != "PASS":
        verdict = "PASS"
    elif score < REVIEW_PASS_THRESHOLD and verdict == "PASS":
        verdict = "FAIL"

    return ReviewResult(
        iteration=iteration,
        post_type=post_type,
        score=score,
        verdict=verdict,
        issues=parsed.get("issues", []),
        suggestions=parsed.get("fixes", []),  # Store for later application
        elapsed_time=elapsed,
        raw_response=response,
    )


def review_and_fix_post(
    post_type: str,
    post_data: Dict,
    market_data: Dict,
    max_iterations: int = MAX_REVIEW_ITERATIONS,
) -> Tuple[Dict, ReviewHistory]:
    """Review and iteratively fix a single post.

    Args:
        post_type: Type of post
        post_data: Post JSON data (will be modified)
        market_data: Market data for validation
        max_iterations: Maximum fix iterations

    Returns:
        (updated_post_data, review_history)
    """
    history = ReviewHistory(post_type=post_type)

    for i in range(1, max_iterations + 1):
        console.print(f"    Iteration {i}/{max_iterations}...")

        # Review current state
        result = review_single_post(post_type, post_data, market_data, iteration=i)

        # Apply fixes if any
        fixes = result.suggestions or []
        if fixes and result.verdict == "FAIL":
            post_data, applied = _apply_fixes(post_data, fixes)
            result.fixes_applied = applied
            history.total_fixes += len(applied)

        history.iterations.append(result)

        # Log result
        status_color = "green" if result.verdict == "PASS" else "yellow"
        console.print(f"    [{status_color}]Score: {result.score}/10, {result.verdict}[/{status_color}] ({result.elapsed_time:.1f}s)")

        if result.fixes_applied:
            console.print(f"    Applied {len(result.fixes_applied)} fixes")

        # Check if passed
        if result.verdict == "PASS":
            history.final_passed = True
            break

        # Show issues
        for issue in result.issues[:2]:
            console.print(f"      - {issue[:80]}...")

    return post_data, history


def stage_review(
    posts: Dict[str, Any],
    edition_pack: Any,
    max_iterations: int = MAX_REVIEW_ITERATIONS,
    skip_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Stage 4.5: LLM Review and Fix

    Reviews all posts using cli-gpt-5.2 and applies corrections.

    Args:
        posts: Dict of PostOutput objects
        edition_pack: EditionPack object
        max_iterations: Max review iterations per post
        skip_types: Post types to skip

    Returns:
        Updated posts dict
    """
    console.print("\n[bold cyan]Stage 4.5: LLM Review (cli-gpt-5.2)[/bold cyan]")

    if not LITELLM_API_KEY:
        console.print("  [yellow]⚠ LITELLM_API_KEY not set - skipping review[/yellow]")
        return posts

    skip_types = skip_types or []
    all_histories: Dict[str, ReviewHistory] = {}

    # Get market data from edition pack
    market_data = {}
    if hasattr(edition_pack, 'market_data'):
        market_data = edition_pack.market_data or {}
    elif isinstance(edition_pack, dict):
        market_data = edition_pack.get("market_data", {})

    for post_type, post in posts.items():
        if post is None:
            continue
        if post_type in skip_types:
            console.print(f"  [dim]⊘ {post_type}: skipped[/dim]")
            continue

        console.print(f"  [bold]{post_type}[/bold]")

        # Get post data
        if hasattr(post, 'json_data'):
            post_data = post.json_data
        elif isinstance(post, dict):
            post_data = post
        else:
            console.print(f"    [yellow]⚠ Unknown post format[/yellow]")
            continue

        # Review and fix
        updated_data, history = review_and_fix_post(
            post_type=post_type,
            post_data=post_data,
            market_data=market_data,
            max_iterations=max_iterations,
        )

        all_histories[post_type] = history

        # Update post object
        if hasattr(post, 'json_data'):
            post.json_data = updated_data

        # Save updated post
        _save_post(post_type, updated_data)

        # Report result
        status = "✓ PASSED" if history.final_passed else "✗ FAILED"
        color = "green" if history.final_passed else "red"
        console.print(f"    [{color}]{status}[/{color}] (fixes: {history.total_fixes})")

    # Save review history
    history_path = Path("out/review_history.json")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(
            {pt: h.to_dict() for pt, h in all_histories.items()},
            f,
            indent=2,
            ensure_ascii=False,
        )
    console.print(f"\n  Review history saved to: {history_path}")

    # Summary
    passed = sum(1 for h in all_histories.values() if h.final_passed)
    total = len(all_histories)
    console.print(f"\n  Overall: {passed}/{total} posts passed review")

    return posts


def _save_post(post_type: str, post_data: Dict) -> None:
    """Save post data to file."""
    json_path = Path(f"out/post_{post_type}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(post_data, f, indent=2, ensure_ascii=False)

    # Also save HTML if present
    if "html" in post_data:
        html_path = Path(f"out/post_{post_type}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(post_data["html"])
