"""JSON Repair Utility - P0-4

共用的 JSON 修復工具，用於處理 LLM 輸出的不完整或格式錯誤的 JSON。

設計原則：
1. 先嘗試本地修復（不需要額外 API 呼叫）
2. 如果本地修復失敗，再嘗試用小模型修復
3. 記錄所有修復嘗試，方便 debug
"""

import json
import re
import os
from typing import Optional, Tuple

from ..utils.logging import get_logger

logger = get_logger(__name__)


def extract_json_block(text: str) -> str:
    """從文本中提取 JSON 區塊

    Args:
        text: 可能包含 markdown code block 的文本

    Returns:
        清理後的 JSON 字串
    """
    if not text:
        return ""

    # 嘗試提取 ```json ... ``` 區塊
    json_block_match = re.search(r"```json\s*([\s\S]*?)```", text)
    if json_block_match:
        return json_block_match.group(1).strip()

    # 嘗試提取 ``` ... ``` 區塊
    code_block_match = re.search(r"```\s*([\s\S]*?)```", text)
    if code_block_match:
        return code_block_match.group(1).strip()

    # 嘗試找到最外層的 { ... }
    start = text.find("{")
    if start == -1:
        return text.strip()

    # 從最後一個 } 開始往前找
    end = text.rfind("}")
    if end == -1 or end < start:
        return text[start:]

    return text[start : end + 1]


def fix_common_json_issues(json_str: str) -> str:
    """修復常見的 JSON 格式問題

    Args:
        json_str: 原始 JSON 字串

    Returns:
        修復後的 JSON 字串
    """
    if not json_str:
        return json_str

    result = json_str

    # 1. 修復尾逗號（trailing comma）
    # 匹配 , 後面接 } 或 ]
    result = re.sub(r",\s*([\}\]])", r"\1", result)

    # 2. 修復未轉義的換行符
    # 在字串內的換行符應該是 \n 而不是實際換行
    # 這個比較複雜，需要判斷是否在字串內

    # 3. 修復未閉合的字串
    # 計算引號數量
    quote_count = result.count('"') - result.count('\\"')
    if quote_count % 2 == 1:
        # 奇數個引號，嘗試在末尾添加一個
        # 找到最後一個未閉合的引號位置
        result = result.rstrip() + '"'
        logger.debug("Added missing closing quote")

    # 4. 修復未閉合的括號
    open_braces = result.count("{") - result.count("}")
    if open_braces > 0:
        result = result.rstrip() + "}" * open_braces
        logger.debug(f"Added {open_braces} missing closing braces")

    open_brackets = result.count("[") - result.count("]")
    if open_brackets > 0:
        result = result.rstrip() + "]" * open_brackets
        logger.debug(f"Added {open_brackets} missing closing brackets")

    # 5. 移除控制字符（除了 \n, \r, \t）
    result = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", result)

    # 6. 修復 NaN 和 Infinity（JSON 不支援）
    result = re.sub(r"\bNaN\b", "null", result)
    result = re.sub(r"\bInfinity\b", "null", result)
    result = re.sub(r"\b-Infinity\b", "null", result)

    return result


def try_parse_json(json_str: str) -> Tuple[Optional[dict], Optional[str]]:
    """嘗試解析 JSON，返回結果和錯誤訊息

    Args:
        json_str: JSON 字串

    Returns:
        (parsed_dict, error_message) - 成功時 error_message 為 None
    """
    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            return parsed, None
        else:
            return None, f"Parsed result is not a dict: {type(parsed)}"
    except json.JSONDecodeError as e:
        return None, f"JSONDecodeError at position {e.pos}: {e.msg}"


def repair_json_local(json_str: str, max_attempts: int = 3) -> Tuple[Optional[dict], list]:
    """本地 JSON 修復（不需要 API 呼叫）

    Args:
        json_str: 原始 JSON 字串
        max_attempts: 最大嘗試次數

    Returns:
        (parsed_dict, repair_log) - parsed_dict 為 None 表示修復失敗
    """
    repair_log = []

    if not json_str:
        return None, ["Empty input"]

    # Step 1: 提取 JSON 區塊
    extracted = extract_json_block(json_str)
    repair_log.append(f"Extracted JSON block: {len(extracted)} chars")

    # Step 2: 嘗試直接解析
    parsed, error = try_parse_json(extracted)
    if parsed is not None:
        repair_log.append("Direct parse succeeded")
        return parsed, repair_log

    repair_log.append(f"Direct parse failed: {error}")

    # Step 3: 嘗試修復常見問題
    for attempt in range(max_attempts):
        fixed = fix_common_json_issues(extracted)
        repair_log.append(f"Attempt {attempt + 1}: Applied common fixes")

        parsed, error = try_parse_json(fixed)
        if parsed is not None:
            repair_log.append(f"Attempt {attempt + 1}: Parse succeeded after fixes")
            return parsed, repair_log

        repair_log.append(f"Attempt {attempt + 1}: Still failed - {error}")

        # 嘗試更激進的修復
        if attempt == 0:
            # 移除可能導致問題的尾部內容
            # 找到最後一個完整的 key-value pair
            last_comma = fixed.rfind(",")
            if last_comma > 0:
                extracted = fixed[:last_comma] + "}"
                repair_log.append("Truncated at last comma")
        elif attempt == 1:
            # 嘗試找到嵌套層級較低的閉合點
            depth = 0
            last_valid_pos = 0
            in_string = False

            for i, char in enumerate(fixed):
                if char == '"' and (i == 0 or fixed[i - 1] != "\\"):
                    in_string = not in_string
                elif not in_string:
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            last_valid_pos = i + 1

            if last_valid_pos > 0:
                extracted = fixed[:last_valid_pos]
                repair_log.append(f"Truncated at valid closing brace (pos {last_valid_pos})")

    return None, repair_log


def repair_json_with_llm(
    json_str: str,
    model: str = "gemini-2.5-flash",
    max_tokens: int = 2000,
) -> Tuple[Optional[dict], list]:
    """使用小模型修復 JSON

    Args:
        json_str: 原始 JSON 字串
        model: 使用的模型
        max_tokens: 最大輸出 token

    Returns:
        (parsed_dict, repair_log)
    """
    repair_log = []

    try:
        import litellm

        # 構建修復 prompt
        prompt = f"""你是一個 JSON 修復專家。以下是一個損壞的 JSON，請修復它並只輸出修復後的 JSON，不要有任何其他文字：

損壞的 JSON（可能被截斷或有語法錯誤）：
```
{json_str[:8000]}
```

請修復這個 JSON 並輸出完整的有效 JSON。如果 JSON 被截斷，請合理地閉合所有括號和引號。"""

        base_url = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")

        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.1,
            base_url=base_url,
        )

        repaired_str = response.choices[0].message.content
        repair_log.append(f"LLM repair response: {len(repaired_str)} chars")

        # 嘗試解析修復後的 JSON
        extracted = extract_json_block(repaired_str)
        parsed, error = try_parse_json(extracted)

        if parsed is not None:
            repair_log.append("LLM repair succeeded")
            return parsed, repair_log
        else:
            repair_log.append(f"LLM repair parse failed: {error}")
            # 再嘗試本地修復
            fixed = fix_common_json_issues(extracted)
            parsed, error = try_parse_json(fixed)
            if parsed is not None:
                repair_log.append("LLM repair + local fix succeeded")
                return parsed, repair_log

    except Exception as e:
        repair_log.append(f"LLM repair error: {e}")

    return None, repair_log


def repair_json(
    json_str: str,
    use_llm: bool = True,
    llm_model: str = "gemini-2.5-flash",
) -> Tuple[Optional[dict], dict]:
    """完整的 JSON 修復流程

    Args:
        json_str: 原始 JSON 字串
        use_llm: 是否在本地修復失敗後使用 LLM
        llm_model: LLM 模型名稱

    Returns:
        (parsed_dict, repair_report)
    """
    report = {
        "input_length": len(json_str) if json_str else 0,
        "local_repair_log": [],
        "llm_repair_log": [],
        "success": False,
        "method": None,
    }

    # Step 1: 嘗試本地修復
    parsed, local_log = repair_json_local(json_str)
    report["local_repair_log"] = local_log

    if parsed is not None:
        report["success"] = True
        report["method"] = "local"
        return parsed, report

    # Step 2: 嘗試 LLM 修復（如果啟用）
    if use_llm:
        parsed, llm_log = repair_json_with_llm(json_str, model=llm_model)
        report["llm_repair_log"] = llm_log

        if parsed is not None:
            report["success"] = True
            report["method"] = "llm"
            return parsed, report

    return None, report
