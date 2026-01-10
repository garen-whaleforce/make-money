"""Placeholder Sanitizer - P0-2

清理文章中的占位符，確保不會有「數據」「⟦UNTRACED⟧」等出現在讀者可見區域。

設計原則：
1. 優先刪除含占位符的整句（比 N/A 更乾淨）
2. 對於表格 cell，用 「—」替代
3. 只處理 public 區域（excerpt、html_preview、paywall 前的 HTML）
4. 記錄所有清理動作，方便 debug
"""

import re
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


# 占位符 patterns（務實版：常見的 LLM 占位輸出）
PLACEHOLDER_PATTERNS = [
    r"⟦UNTRACED⟧",           # 明確標記
    r"⟦[^⟧]+⟧",               # 任何 ⟦...⟧ 格式
    r"\+數據%?",              # +數據 或 +數據%
    r"-數據%?",               # -數據 或 -數據%
    r"數據%",                 # 數據%
    r"數據/年",               # 數據/年
    r"約數據",                # 約數據
    r"QoQ\s*[+-]?數據",       # QoQ +數據
    r"YoY\s*[+-]?數據",       # YoY +數據
    r"\$數據",                # $數據
    r"數據億",                # 數據億
    r"數據B",                 # 數據B
    r"數據M",                 # 數據M
    r"\[待補\]",              # [待補]
    r"\[TBD\]",               # [TBD]
    r"\[PLACEHOLDER\]",       # [PLACEHOLDER]
    r"N/A%",                  # N/A%（格式錯誤）
]

# 編譯 regex
PLACEHOLDER_REGEX = re.compile("|".join(PLACEHOLDER_PATTERNS), re.IGNORECASE)

# 表格 cell 替代值
TABLE_CELL_REPLACEMENT = "—"

# 句子分隔符
SENTENCE_DELIMITERS = r"[。.！!？?；;]"


def find_placeholders(text: str) -> list[dict]:
    """找出文本中的所有占位符

    Returns:
        list of {match, start, end, pattern}
    """
    if not text:
        return []

    results = []
    for match in PLACEHOLDER_REGEX.finditer(text):
        results.append({
            "match": match.group(),
            "start": match.start(),
            "end": match.end(),
            "context": text[max(0, match.start()-20):min(len(text), match.end()+20)]
        })
    return results


def sanitize_text(text: str, mode: str = "delete_sentence") -> tuple[str, list[str]]:
    """清理文本中的占位符

    Args:
        text: 原始文本
        mode: 處理模式
            - "delete_sentence": 刪除整個句子（預設）
            - "replace_dash": 用 — 替代
            - "delete_only": 只刪除占位符本身

    Returns:
        (cleaned_text, list of changes made)
    """
    if not text:
        return text, []

    changes = []
    result = text

    if mode == "delete_sentence":
        # 找出所有占位符
        placeholders = find_placeholders(result)

        # 對每個占位符，找到包含它的句子並刪除
        sentences_to_remove = set()
        for ph in placeholders:
            # 找句子邊界
            start = ph["start"]
            end = ph["end"]

            # 往前找句子開頭
            sentence_start = start
            while sentence_start > 0:
                if re.match(SENTENCE_DELIMITERS, result[sentence_start-1]):
                    break
                sentence_start -= 1

            # 往後找句子結尾
            sentence_end = end
            while sentence_end < len(result):
                if re.match(SENTENCE_DELIMITERS, result[sentence_end]):
                    sentence_end += 1  # 包含標點
                    break
                sentence_end += 1

            sentence = result[sentence_start:sentence_end].strip()
            if sentence:
                sentences_to_remove.add(sentence)
                changes.append(f"Removed sentence: '{sentence[:50]}...'")

        # 刪除句子
        for sentence in sentences_to_remove:
            result = result.replace(sentence, "")

        # 清理多餘空白
        result = re.sub(r"\n\s*\n\s*\n", "\n\n", result)
        result = re.sub(r"  +", " ", result)

    elif mode == "replace_dash":
        def replace_fn(m):
            changes.append(f"Replaced '{m.group()}' with '—'")
            return TABLE_CELL_REPLACEMENT
        result = PLACEHOLDER_REGEX.sub(replace_fn, result)

    elif mode == "delete_only":
        def delete_fn(m):
            changes.append(f"Deleted '{m.group()}'")
            return ""
        result = PLACEHOLDER_REGEX.sub(delete_fn, result)

    return result.strip(), changes


def sanitize_html(html: str) -> tuple[str, list[str]]:
    """清理 HTML 中的占位符

    特殊處理：
    1. 表格 cell (<td>) 內的占位符用 — 替代
    2. 其他區域刪除整句
    """
    if not html:
        return html, []

    all_changes = []
    result = html

    # 1. 處理表格 cell
    def replace_td_content(match):
        td_content = match.group(1)
        cleaned, changes = sanitize_text(td_content, mode="replace_dash")
        all_changes.extend(changes)
        return f"<td>{cleaned}</td>"

    result = re.sub(r"<td>([^<]*)</td>", replace_td_content, result, flags=re.IGNORECASE)

    # 2. 處理其他區域（刪除整句）
    # 找到 <!--members-only--> 分界點
    paywall_marker = "<!--members-only-->"
    paywall_pos = result.find(paywall_marker)

    if paywall_pos > 0:
        # 只處理 paywall 前的 public 區域
        public_html = result[:paywall_pos]
        members_html = result[paywall_pos:]

        cleaned_public, changes = sanitize_text(public_html, mode="delete_sentence")
        all_changes.extend([f"[PUBLIC] {c}" for c in changes])

        result = cleaned_public + members_html
    else:
        # 沒有 paywall，處理全部
        result, changes = sanitize_text(result, mode="delete_sentence")
        all_changes.extend(changes)

    return result, all_changes


def sanitize_excerpt(excerpt: str) -> tuple[str, list[str]]:
    """清理 excerpt 中的占位符

    excerpt 是最重要的區域（會顯示在 email subject、SEO、社群分享）
    策略：刪除整句
    """
    return sanitize_text(excerpt, mode="delete_sentence")


def sanitize_post(post_data: dict) -> tuple[dict, dict]:
    """清理整篇文章的占位符

    Args:
        post_data: 文章 JSON 資料

    Returns:
        (cleaned_post_data, sanitization_report)
    """
    report = {
        "total_placeholders_found": 0,
        "changes": [],
        "fields_sanitized": []
    }

    result = post_data.copy()

    # 1. 清理 excerpt
    if "excerpt" in result and result["excerpt"]:
        original = result["excerpt"]
        cleaned, changes = sanitize_excerpt(original)
        if changes:
            result["excerpt"] = cleaned
            report["changes"].extend([f"excerpt: {c}" for c in changes])
            report["fields_sanitized"].append("excerpt")

    # 2. 清理 html（如果存在）
    if "html" in result and result["html"]:
        original = result["html"]
        cleaned, changes = sanitize_html(original)
        if changes:
            result["html"] = cleaned
            report["changes"].extend([f"html: {c}" for c in changes])
            report["fields_sanitized"].append("html")

    # 3. 清理 html_preview（如果存在）
    if "html_preview" in result and result["html_preview"]:
        original = result["html_preview"]
        cleaned, changes = sanitize_html(original)
        if changes:
            result["html_preview"] = cleaned
            report["changes"].extend([f"html_preview: {c}" for c in changes])
            report["fields_sanitized"].append("html_preview")

    # 4. 清理 newsletter_subject
    if "newsletter_subject" in result and result["newsletter_subject"]:
        original = result["newsletter_subject"]
        cleaned, changes = sanitize_text(original, mode="delete_only")
        if changes:
            result["newsletter_subject"] = cleaned
            report["changes"].extend([f"newsletter_subject: {c}" for c in changes])
            report["fields_sanitized"].append("newsletter_subject")

    # 5. 統計
    report["total_placeholders_found"] = len(report["changes"])

    if report["changes"]:
        logger.warning(f"Sanitized {len(report['changes'])} placeholders from post")

    return result, report


def check_for_placeholders(text: str) -> list[str]:
    """檢查文本是否包含占位符（用於 Quality Gate）

    Returns:
        發現的占位符列表
    """
    placeholders = find_placeholders(text)
    return [p["match"] for p in placeholders]
