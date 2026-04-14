import json
import re
from datetime import datetime, timezone
from typing import Any

import bleach


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def strip_html(text: str, max_len: int | None = None) -> str:
    cleaned = bleach.clean(text or "", tags=[], attributes={}, strip=True)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if max_len is not None:
        return cleaned[:max_len]
    return cleaned


def safe_json_loads(value: str, fallback: Any):
    try:
        return json.loads(value)
    except Exception:
        return fallback


def safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)
