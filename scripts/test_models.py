#!/usr/bin/env python3
"""測試不同 LLM 模型的品質和成本"""

import json
import time
import requests
from typing import Dict, Any

API_KEY = "sk-uI7-kCNyMyXW8QnSAbKrMg"
BASE_URL = "https://litellm.whaleforce.dev/chat/completions"

TEST_PROMPT = """你是美股分析師。請用繁體中文分析 QBTS (D-Wave Quantum) 這支量子運算股票的投資價值，包含：
1. 一句話結論
2. 三個關鍵數字（可以假設）
3. Bull Case 和 Bear Case

請用 JSON 格式輸出，包含 conclusion, key_numbers (array), bull_case, bear_case 欄位。不要加 markdown code block。"""

MODELS = [
    "claude-sonnet-4.5",
    "gpt-5.2",
    "gpt-5-mini",
    "gemini-2.5-flash",
    "qwen3-max",
]

# 估計成本 (USD per 1M tokens) - 基於公開定價
COST_ESTIMATES = {
    "claude-sonnet-4.5": {"input": 3.0, "output": 15.0},
    "gpt-5.2": {"input": 5.0, "output": 15.0},
    "gpt-5-mini": {"input": 0.15, "output": 0.60},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "qwen3-max": {"input": 0.50, "output": 2.0},
}

def test_model(model: str) -> Dict[str, Any]:
    """測試單一模型"""
    print(f"\n{'='*60}")
    print(f"Testing: {model}")
    print('='*60)

    start = time.time()

    try:
        response = requests.post(
            BASE_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": TEST_PROMPT}],
                "max_tokens": 1000
            },
            timeout=120
        )

        elapsed = time.time() - start

        if response.status_code != 200:
            return {
                "model": model,
                "success": False,
                "error": response.text[:200],
                "time": elapsed
            }

        data = response.json()

        # 提取資訊
        usage = data.get("usage", {})
        content = data["choices"][0]["message"]["content"]

        # 計算成本
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost_info = COST_ESTIMATES.get(model, {"input": 1.0, "output": 3.0})
        cost = (input_tokens * cost_info["input"] + output_tokens * cost_info["output"]) / 1_000_000

        # 檢查 JSON 格式
        json_valid = False
        parsed_json = None
        try:
            # 嘗試解析 JSON
            clean_content = content
            if "```json" in content:
                clean_content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                clean_content = content.split("```")[1].split("```")[0]
            parsed_json = json.loads(clean_content.strip())
            json_valid = True
        except:
            pass

        return {
            "model": model,
            "success": True,
            "time": round(elapsed, 2),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost, 6),
            "json_valid": json_valid,
            "content": content,
            "parsed_json": parsed_json
        }

    except Exception as e:
        return {
            "model": model,
            "success": False,
            "error": str(e),
            "time": time.time() - start
        }

def evaluate_quality(result: Dict) -> Dict[str, int]:
    """評估輸出品質 (1-5分)"""
    if not result.get("success"):
        return {"overall": 0, "chinese": 0, "structure": 0, "insight": 0}

    content = result.get("content", "")
    parsed = result.get("parsed_json")

    scores = {}

    # 中文品質 (檢查是否有簡體字或奇怪用語)
    simplified_chars = ["这", "们", "没", "为", "与", "发", "对", "种"]
    has_simplified = any(c in content for c in simplified_chars)
    scores["chinese"] = 3 if has_simplified else 5

    # JSON 結構
    if parsed:
        required_fields = ["conclusion", "key_numbers", "bull_case", "bear_case"]
        has_all = all(f in parsed for f in required_fields)
        scores["structure"] = 5 if has_all else 3
    else:
        scores["structure"] = 1

    # 內容深度 (簡單檢查長度)
    if len(content) > 800:
        scores["insight"] = 5
    elif len(content) > 500:
        scores["insight"] = 4
    elif len(content) > 300:
        scores["insight"] = 3
    else:
        scores["insight"] = 2

    scores["overall"] = round((scores["chinese"] + scores["structure"] + scores["insight"]) / 3, 1)

    return scores

def main():
    results = []

    for model in MODELS:
        result = test_model(model)

        if result["success"]:
            quality = evaluate_quality(result)
            result["quality"] = quality

            print(f"Time: {result['time']}s")
            print(f"Tokens: {result['input_tokens']} in / {result['output_tokens']} out")
            print(f"Cost: ${result['cost_usd']:.6f}")
            print(f"JSON Valid: {'✅' if result['json_valid'] else '❌'}")
            print(f"Quality: {quality}")
            print(f"\nContent Preview:")
            print(result['content'][:600])
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown')}")

        results.append(result)

    # 總結比較表
    print("\n" + "="*80)
    print("📊 模型比較總結")
    print("="*80)
    print(f"{'模型':<20} {'速度':<8} {'Token數':<10} {'成本':<12} {'JSON':<6} {'品質':<8}")
    print("-"*80)

    for r in results:
        if r["success"]:
            print(f"{r['model']:<20} {r['time']:<8}s {r['total_tokens']:<10} ${r['cost_usd']:<11.6f} {'✅' if r['json_valid'] else '❌':<6} {r['quality']['overall']:<8}")
        else:
            print(f"{r['model']:<20} {'FAIL':<8} {'-':<10} {'-':<12} {'-':<6} {'-':<8}")

    # 推薦
    print("\n" + "="*80)
    print("📋 推薦結論")
    print("="*80)

    successful = [r for r in results if r["success"]]
    if successful:
        # 按品質排序
        by_quality = sorted(successful, key=lambda x: x["quality"]["overall"], reverse=True)
        print(f"🏆 最高品質: {by_quality[0]['model']} (品質分: {by_quality[0]['quality']['overall']})")

        # 按成本排序
        by_cost = sorted(successful, key=lambda x: x["cost_usd"])
        print(f"💰 最低成本: {by_cost[0]['model']} (${by_cost[0]['cost_usd']:.6f})")

        # 按速度排序
        by_speed = sorted(successful, key=lambda x: x["time"])
        print(f"⚡ 最快速度: {by_speed[0]['model']} ({by_speed[0]['time']}s)")

        # 性價比 (品質/成本)
        for r in successful:
            if r["cost_usd"] > 0:
                r["value"] = r["quality"]["overall"] / (r["cost_usd"] * 10000)
            else:
                r["value"] = 0
        by_value = sorted(successful, key=lambda x: x["value"], reverse=True)
        print(f"📈 最佳性價比: {by_value[0]['model']}")

if __name__ == "__main__":
    main()
