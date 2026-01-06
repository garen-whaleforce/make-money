"""Schema Validators

JSON Schema 驗證器。
"""

import json
from pathlib import Path
from typing import Any, Optional

import jsonschema

from ..utils.logging import get_logger

logger = get_logger(__name__)


class SchemaValidator:
    """JSON Schema 驗證器"""

    def __init__(self, schema_path: str):
        """初始化驗證器

        Args:
            schema_path: Schema 檔案路徑
        """
        self.schema_path = Path(schema_path)
        self.schema = None

        if self.schema_path.exists():
            with open(self.schema_path) as f:
                self.schema = json.load(f)
        else:
            logger.warning(f"Schema not found: {schema_path}")

    def validate(self, data: dict) -> tuple[bool, list[str]]:
        """驗證資料

        Args:
            data: 要驗證的資料

        Returns:
            (is_valid, errors)
        """
        if not self.schema:
            return True, []

        errors = []

        try:
            jsonschema.validate(data, self.schema)
        except jsonschema.ValidationError as e:
            errors.append(f"Validation error: {e.message}")
            if e.path:
                errors[-1] += f" at {'.'.join(str(p) for p in e.path)}"
        except jsonschema.SchemaError as e:
            errors.append(f"Schema error: {e.message}")

        return len(errors) == 0, errors


def validate_research_pack(data: dict) -> tuple[bool, list[str]]:
    """驗證 research_pack

    Args:
        data: research_pack 資料

    Returns:
        (is_valid, errors)
    """
    validator = SchemaValidator("schemas/research_pack.schema.json")
    is_valid, schema_errors = validator.validate(data)

    errors = list(schema_errors)

    # 額外檢查
    if len(data.get("sources", [])) < 5:
        errors.append(f"Insufficient sources: {len(data.get('sources', []))} < 5")

    if len(data.get("key_stocks", [])) < 2:
        errors.append(f"Insufficient key stocks: {len(data.get('key_stocks', []))} < 2")

    if not data.get("primary_event", {}).get("title"):
        errors.append("Missing primary event title")

    return len(errors) == 0, errors


def validate_post(data: dict) -> tuple[bool, list[str]]:
    """驗證 post

    Args:
        data: post 資料

    Returns:
        (is_valid, errors)
    """
    validator = SchemaValidator("schemas/post.schema.json")
    is_valid, schema_errors = validator.validate(data)

    errors = list(schema_errors)

    # 額外檢查
    if not data.get("title"):
        errors.append("Missing title")

    if len(data.get("tldr", [])) < 3:
        errors.append(f"Insufficient TL;DR items: {len(data.get('tldr', []))} < 3")

    if not data.get("markdown"):
        errors.append("Missing markdown content")

    disclosures = data.get("disclosures", {})
    if not disclosures.get("not_investment_advice"):
        errors.append("Missing investment disclaimer")

    return len(errors) == 0, errors
