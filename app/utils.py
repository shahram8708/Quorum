import json
import math
import re
import unicodedata
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


def slugify_text(text: str, max_len: int = 120) -> str:
    normalized = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if max_len and len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "post"


def normalize_tags(raw_tags, max_tags: int = 10) -> list[str]:
    if isinstance(raw_tags, list):
        candidates = raw_tags
    else:
        candidates = str(raw_tags or "").split(",")

    seen = set()
    cleaned = []
    for item in candidates:
        tag = strip_html(str(item or ""), 40).strip().lower()
        if not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)
        if len(cleaned) >= max_tags:
            break
    return cleaned


def sanitize_rich_html(html: str) -> str:
    allowed_tags = [
        "p",
        "br",
        "hr",
        "h2",
        "h3",
        "strong",
        "em",
        "u",
        "blockquote",
        "ul",
        "ol",
        "li",
        "pre",
        "code",
        "a",
        "img",
        "figure",
        "figcaption",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "iframe",
    ]
    allowed_attributes = {
        "a": ["href", "title", "target", "rel"],
        "img": ["src", "alt", "title", "width", "height"],
        "iframe": [
            "src",
            "title",
            "width",
            "height",
            "allow",
            "allowfullscreen",
            "frameborder",
            "referrerpolicy",
        ],
        "th": ["colspan", "rowspan"],
        "td": ["colspan", "rowspan"],
    }

    cleaned = bleach.clean(
        html or "",
        tags=allowed_tags,
        attributes=allowed_attributes,
        protocols=["http", "https", "mailto"],
        strip=True,
        strip_comments=True,
    )

    allowed_iframe_prefixes = (
        "https://www.youtube.com/embed/",
        "https://www.youtube-nocookie.com/embed/",
    )

    def _filter_iframe(match):
        src = match.group(2)
        if any(src.startswith(prefix) for prefix in allowed_iframe_prefixes):
            return match.group(0)
        return ""

    cleaned = re.sub(
        r'<iframe([^>]*?)src="([^"]+)"([^>]*)></iframe>',
        _filter_iframe,
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def html_word_count(html: str) -> int:
    plain = bleach.clean(html or "", tags=[], attributes={}, strip=True)
    return len(re.findall(r"\b[\w'-]+\b", plain))


def estimate_reading_time_minutes(html: str, words_per_minute: int = 200) -> int:
    words = html_word_count(html)
    if words <= 0:
        return 1
    return max(1, math.ceil(words / max(1, words_per_minute)))
