"""Post translation utilities."""

import json
import os
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


class TranslationRunner:
    """Translate a post JSON into English using LiteLLM."""

    def __init__(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> None:
        env_model = os.getenv("LITELLM_MODEL") or os.getenv("CODEX_MODEL") or "claude-sonnet-4.5"
        self.model = model or env_model
        self.max_tokens = max_tokens or int(os.getenv("TRANSLATE_MAX_TOKENS", "16000"))
        self.temperature = temperature if temperature is not None else float(os.getenv("TRANSLATE_TEMPERATURE", "0.2"))

    def _parse_json_response(self, response_text: str) -> Optional[dict]:
        if not response_text:
            return None
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        response_text = response_text.strip()
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            start = response_text.find("{")
            end = response_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(response_text[start : end + 1])
                except json.JSONDecodeError:
                    return None
            return None

    def _call_litellm(self, prompt: str) -> Optional[dict]:
        try:
            from openai import OpenAI
        except Exception:
            logger.error("openai SDK not installed. Run: pip install openai")
            return None

        base_url = os.getenv("LITELLM_BASE_URL", "https://litellm.whaleforce.dev")
        api_key = os.getenv("LITELLM_API_KEY")
        if not api_key:
            logger.error("LITELLM_API_KEY not set")
            return None

        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional financial editor. "
                            "Translate JSON content to English. "
                            "Do not change numbers, tickers, URLs, or JSON structure. "
                            "Keep HTML tags and <!--members-only--> markers intact. "
                            "Output JSON only, no code fences."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        except Exception as e:
            logger.error(f"LiteLLM translation failed: {e}")
            return None

        if not response or not response.choices:
            return None
        content = response.choices[0].message.content or ""
        return self._parse_json_response(content)

    def translate(self, post_data: dict) -> Optional[dict]:
        payload = json.dumps(post_data, ensure_ascii=False)
        prompt = (
            "Translate this JSON to English. Keep structure and keys unchanged.\n\n"
            f"{payload}"
        )
        return self._call_litellm(prompt)
