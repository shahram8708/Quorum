"""
app/services/ai_service.py

Quorum Platform - AI Service Layer
Uses Google Gemini 2.5 Flash for all AI-powered features.

DEBUGGING: All raw Gemini responses are logged at DEBUG level.
           Set LOG_LEVEL=DEBUG in .env to see full responses in terminal.

Logger name: quorum.ai_service
"""

import json
import logging
import re
import time
import traceback
from datetime import datetime
from typing import Optional, Union

from flask import current_app, has_request_context
from flask_login import current_user

from app.extensions import db
from app.models import AICivicPulseCache, AIUsageLog, User


logger = logging.getLogger("quorum.ai_service")

AI_FEATURE_NAME_MAP = {
    "enhance_project_description": "description_enhancer",
    "validate_project_scope": "scope_validator",
    "suggest_project_roles": "role_suggester",
    "personalized_recommendations": "recommendations",
    "ai_template_search": "template_search",
    "fetch_civic_pulse": "civic_pulse",
    "generate_outcome_draft": "outcome_assistant",
    "discover_civic_challenges": "challenge_discovery",
}

try:
    from google.api_core.exceptions import (
        DeadlineExceeded,
        InvalidArgument,
        ResourceExhausted,
        ServiceUnavailable,
    )
except Exception:
    class InvalidArgument(Exception):
        """Fallback exception when google.api_core is unavailable."""

    class ResourceExhausted(Exception):
        """Fallback exception when google.api_core is unavailable."""

    class ServiceUnavailable(Exception):
        """Fallback exception when google.api_core is unavailable."""

    class DeadlineExceeded(Exception):
        """Fallback exception when google.api_core is unavailable."""


class AIParsingError(Exception):
    """Raised when Gemini response cannot be parsed into expected JSON format."""

    def __init__(self, method_name: str, raw_response: str, parse_error: str):
        self.method_name = method_name
        self.raw_response = raw_response
        self.parse_error = parse_error
        super().__init__(
            f"[AIParsingError] method={method_name} | "
            f"parse_error={parse_error} | "
            f"raw_response_preview={raw_response[:300]}"
        )


def format_civic_pulse_content(pulse_data: dict) -> str:
    """Build human-readable dashboard content from structured civic pulse data."""
    if not isinstance(pulse_data, dict):
        return "Civic pulse data unavailable."

    lines = []
    summary = str(pulse_data.get("overall_summary", "")).strip()
    if summary:
        lines.append(summary)

    stories = pulse_data.get("civic_stories", [])
    if isinstance(stories, list) and stories:
        lines.append("")
        lines.append("Top civic stories:")
        for story in stories[:5]:
            if not isinstance(story, dict):
                continue
            title = str(story.get("title", "Untitled story")).strip()
            detail = str(story.get("summary", "")).strip()
            source = str(story.get("source_hint", "")).strip()
            line = f"- {title}: {detail}"
            if source:
                line = f"{line} ({source})"
            lines.append(line)

    last_updated = str(pulse_data.get("last_updated", "")).strip()
    if last_updated:
        lines.append("")
        lines.append(f"Last updated: {last_updated}")

    return "\n".join(lines).strip() or "Civic pulse data unavailable."


class AIService:
    def __init__(self):
        self.model = "gemini-2.5-flash"

    def _feature_name(self, method_name: str) -> str:
        return AI_FEATURE_NAME_MAP.get(method_name, str(method_name or "ai_call")[:100])

    def _request_user_id(self) -> Optional[int]:
        if not has_request_context():
            return None

        try:
            if current_user.is_authenticated:
                return int(current_user.id)
        except Exception:
            return None
        return None

    def _estimate_tokens(self, prompt: str, response_obj, response_text: str) -> int:
        usage = getattr(response_obj, "usage_metadata", None) or getattr(response_obj, "usage", None)

        candidates = []
        if usage is not None:
            for key in (
                "total_token_count",
                "total_tokens",
                "totalTokenCount",
                "totalTokens",
            ):
                if isinstance(usage, dict):
                    value = usage.get(key)
                else:
                    value = getattr(usage, key, None)
                if isinstance(value, int) and value > 0:
                    candidates.append(value)

            if not candidates:
                prompt_tokens = None
                completion_tokens = None
                if isinstance(usage, dict):
                    prompt_tokens = usage.get("prompt_token_count") or usage.get("prompt_tokens")
                    completion_tokens = usage.get("candidates_token_count") or usage.get("completion_tokens")
                else:
                    prompt_tokens = getattr(usage, "prompt_token_count", None) or getattr(usage, "prompt_tokens", None)
                    completion_tokens = getattr(usage, "candidates_token_count", None) or getattr(usage, "completion_tokens", None)

                if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
                    candidates.append(max(1, prompt_tokens + completion_tokens))

        if candidates:
            return int(candidates[0])

        # Fallback approximation when provider metadata is unavailable.
        estimate = max(1, int((len(prompt or "") + len(response_text or "")) / 4))
        return estimate

    def _log_ai_usage(
        self,
        method_name: str,
        response_time_ms: int,
        was_successful: bool,
        tokens_estimated: int,
    ) -> None:
        try:
            with db.engine.begin() as connection:
                connection.execute(
                    AIUsageLog.__table__.insert().values(
                        user_id=self._request_user_id(),
                        feature_name=self._feature_name(method_name),
                        called_at=datetime.utcnow(),
                        response_time_ms=max(0, int(response_time_ms or 0)),
                        was_successful=bool(was_successful),
                        tokens_estimated=max(0, int(tokens_estimated or 0)),
                    )
                )
        except Exception as error:
            logger.warning(
                "[AI SERVICE] Usage logging failed - method=%s error=%s",
                method_name,
                str(error),
            )

    def _get_client(self):
        from google import genai

        api_key = current_app.config.get("GOOGLE_API_KEY")
        if api_key:
            return genai.Client(api_key=api_key)
        return genai.Client()

    def _generate_content(self, prompt: str, method_name: str, use_grounding: bool = False) -> str:
        client = self._get_client()
        logger.info(f"[AI SERVICE] Sending request to Gemini - method={method_name}")

        started_at = time.perf_counter()
        response = None
        raw_text = ""
        was_successful = False

        try:
            if use_grounding:
                from google.genai import types

                grounding_tool = types.Tool(google_search=types.GoogleSearch())
                config = types.GenerateContentConfig(tools=[grounding_tool])
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
            else:
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )

            raw_text = getattr(response, "text", None)
            if raw_text is None:
                raw_text = str(response)
            was_successful = True
            return str(raw_text)
        finally:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            tokens_estimated = self._estimate_tokens(prompt, response, str(raw_text or ""))
            self._log_ai_usage(
                method_name=method_name,
                response_time_ms=elapsed_ms,
                was_successful=was_successful,
                tokens_estimated=tokens_estimated,
            )

    def _find_balanced_json_block(self, text: str, start_index: int, opener: str, closer: str) -> Optional[str]:
        depth = 0
        in_string = False
        escape = False

        for index in range(start_index, len(text)):
            char = text[index]

            if in_string:
                if escape:
                    escape = False
                    continue
                if char == "\\":
                    escape = True
                    continue
                if char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start_index : index + 1]

        return None

    def _extract_json(self, raw_text: str, method_name: str, expected_type: type = dict) -> Union[dict, list]:
        """
        Robustly extract and parse JSON from a Gemini raw response string.

        Steps:
        1. Log the full raw response to terminal
        2. Strip whitespace and markdown fences
        3. Try direct json.loads()
        4. If fails: try regex extraction of first JSON block
        5. If fails: raise AIParsingError with full context

        Args:
            raw_text: The raw string returned by Gemini API
            method_name: Name of the calling method (for logging)
            expected_type: dict or list - what type the top-level JSON should be

        Returns:
            Parsed dict or list

        Raises:
            AIParsingError: If all parsing attempts fail
        """
        text = raw_text if isinstance(raw_text, str) else str(raw_text)

        logger.debug(
            "\n"
            "============================================================\n"
            f"[AI SERVICE] RAW GEMINI RESPONSE - method: {method_name}\n"
            "============================================================\n"
            f"{text}\n"
            "============================================================\n"
            "[AI SERVICE] END OF RAW RESPONSE\n"
            "============================================================"
        )

        cleaned = text.strip()
        cleaned = re.sub(r"^\s*```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^`+", "", cleaned)
        cleaned = re.sub(r"`+$", "", cleaned)
        cleaned = cleaned.strip()

        first_brace = cleaned.find("{")
        first_bracket = cleaned.find("[")

        if first_brace == -1 and first_bracket == -1:
            pass
        elif first_brace == -1:
            cleaned = cleaned[first_bracket:]
        elif first_bracket == -1:
            cleaned = cleaned[first_brace:]
        else:
            cleaned = cleaned[min(first_brace, first_bracket) :]

        last_brace = cleaned.rfind("}")
        last_bracket = cleaned.rfind("]")
        end_position = max(last_brace, last_bracket)
        if end_position != -1:
            cleaned = cleaned[: end_position + 1]

        logger.debug(f"[AI SERVICE] CLEANED TEXT for method={method_name}:\n{cleaned}")

        try:
            parsed = json.loads(cleaned)
            logger.debug(
                f"[AI SERVICE] JSON PARSE SUCCESS - method={method_name} | "
                f"type={type(parsed).__name__} | "
                f"keys={list(parsed.keys()) if isinstance(parsed, dict) else f'list of {len(parsed)} items'}"
            )
            if not isinstance(parsed, expected_type):
                raise AIParsingError(
                    method_name=method_name,
                    raw_response=text,
                    parse_error=(
                        f"Top-level JSON type mismatch. Expected {expected_type.__name__}, "
                        f"got {type(parsed).__name__}"
                    ),
                )
            return parsed
        except json.JSONDecodeError as error:
            logger.warning(
                f"[AI SERVICE] Direct json.loads() failed - method={method_name} | "
                f"error={str(error)} | attempting regex fallback..."
            )

        match_dict = re.search(r"\{", text)
        match_list = re.search(r"\[", text)
        candidates = []

        if match_dict:
            dict_block = self._find_balanced_json_block(text, match_dict.start(), "{", "}")
            if dict_block:
                candidates.append(("dict", dict_block, match_dict.start()))

        if match_list:
            list_block = self._find_balanced_json_block(text, match_list.start(), "[", "]")
            if list_block:
                candidates.append(("list", list_block, match_list.start()))

        candidates.sort(key=lambda item: item[2])

        for pattern_name, candidate, _ in candidates:
            try:
                parsed = json.loads(candidate)
                if not isinstance(parsed, expected_type):
                    raise AIParsingError(
                        method_name=method_name,
                        raw_response=text,
                        parse_error=(
                            "Regex fallback parsed valid JSON but wrong top-level type: "
                            f"expected {expected_type.__name__}, got {type(parsed).__name__}"
                        ),
                    )
                logger.debug(
                    f"[AI SERVICE] REGEX FALLBACK SUCCESS - method={method_name} | pattern={pattern_name}"
                )
                return parsed
            except json.JSONDecodeError as error:
                logger.warning(
                    f"[AI SERVICE] Regex fallback failed for pattern={pattern_name} "
                    f"method={method_name} | error={str(error)}"
                )

        logger.error(
            "[AI SERVICE] JSON EXTRACTION FAILED - method=%s | raw_response=%s",
            method_name,
            text,
        )

        raise AIParsingError(
            method_name=method_name,
            raw_response=text,
            parse_error="All JSON parsing strategies failed (direct parse + regex fallback)",
        )

    def _coerce_bool(self, value, field_name: str, method_name: str, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        original = value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    f"field={field_name} | original={original} | coerced=True"
                )
                return True
            if lowered in {"false", "0", "no", "n"}:
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    f"field={field_name} | original={original} | coerced=False"
                )
                return False
        logger.warning(
            f"[AI SERVICE] TYPE COERCION FAILED - method={method_name} | "
            f"field={field_name} | original={original} | default={default}"
        )
        return default

    def _coerce_int(self, value, field_name: str, method_name: str, default: int = 0) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        original = value
        try:
            coerced = int(value)
            logger.warning(
                f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                f"field={field_name} | original={original} | coerced={coerced}"
            )
            return coerced
        except (ValueError, TypeError):
            logger.warning(
                f"[AI SERVICE] TYPE COERCION FAILED - method={method_name} | "
                f"field={field_name} | original={original} | default={default}"
            )
            return default

    def _coerce_float(self, value, field_name: str, method_name: str, default: float = 0.0) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        original = value
        try:
            coerced = float(value)
            logger.warning(
                f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                f"field={field_name} | original={original} | coerced={coerced}"
            )
            return coerced
        except (ValueError, TypeError):
            logger.warning(
                f"[AI SERVICE] TYPE COERCION FAILED - method={method_name} | "
                f"field={field_name} | original={original} | default={default}"
            )
            return default

    def _handle_method_error(self, method_name: str, error: Exception, fallback, raw_response: Optional[str] = None):
        preview_source = raw_response
        if preview_source is None and isinstance(error, AIParsingError):
            preview_source = error.raw_response
        preview = (preview_source or "")[:500]
        logger.error(
            f"[AI SERVICE ERROR] method={method_name} error_type={type(error).__name__} \n"
            f"message={str(error)}\n"
            f"raw_response={preview}\n"
            f"traceback={traceback.format_exc()}\n"
            "returning fallback value."
        )
        return fallback

    def enhance_project_description(self, raw_text: str) -> dict:
        """
        Takes a rough, casual problem description from the user and rewrites it
        into a well-structured, compelling civic project description.

        Args:
            raw_text: User's raw, unpolished problem description

        Returns:
            dict with keys: enhanced_description (str), key_points (list[str]), word_count (int)

        Fallback on error:
            {"enhanced_description": raw_text, "key_points": [], "word_count": len(raw_text.split())}
        """
        method_name = "enhance_project_description"
        fallback = {
            "enhanced_description": raw_text,
            "key_points": [],
            "word_count": len((raw_text or "").split()),
        }

        logger.info(f"[AI SERVICE] Calling Gemini - method={method_name}")
        logger.debug(f"[AI SERVICE] Input raw_text preview: {(raw_text or '')[:200]}")

        prompt = f"""
SYSTEM CONTEXT:
You are a civic action copywriter helping everyday people describe community problems
in a clear, compelling, and actionable way for a civic coordination platform.

TASK:
Rewrite the user's rough problem description into a well-structured, professional,
and emotionally engaging civic project description. Keep it factual and grounded -
no exaggeration. Preserve all specific details (numbers, locations, names) from
the original. The enhanced description should clearly explain: (1) what the problem
is, (2) who is affected and how many, (3) why existing solutions have failed,
(4) why now is the time to act.

INPUT (user's raw description):
\"\"\"{raw_text}\"\"\"

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- enhanced_description must be between 80 and 200 words.
- key_points must contain exactly 3 items, each a single sentence.

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "enhanced_description": "In the Navrangpura neighborhood of Ahmedabad, over 200 elderly residents above the age of 65 live in social isolation - many going days without any meaningful human contact. Despite being one of the most densely populated areas of the city, there is no structured community program to connect these residents with regular visitors or support networks. Local community centers exist but run no outreach programs. Research consistently shows that social isolation accelerates cognitive decline and increases mortality risk among the elderly by up to 26%. The problem is not a lack of willing volunteers - it is a lack of coordination infrastructure to connect them with isolated residents in a sustainable, accountable way.",
  "key_points": [
    "200+ elderly residents in Navrangpura live in measurable social isolation with no community support.",
    "Existing community centers have no structured elderly outreach programs despite available space.",
    "Social isolation among the elderly increases mortality risk by up to 26% - this is a solvable, urgent problem."
  ],
  "word_count": 142
}}

CONSTRAINTS:
- Preserve all specific numbers and location names from the original text.
- Do not invent statistics that were not in the original text.
- Use active, direct language - avoid passive voice and bureaucratic tone.

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            required_keys = ["enhanced_description", "key_points", "word_count"]
            for key in required_keys:
                if key not in result:
                    raise KeyError(f"Missing required key: {key}")

            if not isinstance(result["enhanced_description"], str):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    f"field=enhanced_description | original_type={type(result['enhanced_description']).__name__}"
                )
                result["enhanced_description"] = str(result["enhanced_description"])

            if not isinstance(result["key_points"], list):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    "field=key_points | coercing to empty list"
                )
                result["key_points"] = []
            else:
                result["key_points"] = [str(item) for item in result["key_points"]][:3]

            result["word_count"] = self._coerce_int(
                result.get("word_count"),
                "word_count",
                method_name,
                default=len(result["enhanced_description"].split()),
            )

            logger.info(
                f"[AI SERVICE] SUCCESS - method={method_name} | "
                f"enhanced_word_count={result.get('word_count', 'N/A')}"
            )
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)

    def validate_project_scope(self, success_definition: str, timeline_days: int, project_type: str) -> dict:
        """
        Analyzes whether the project success definition is appropriately scoped
        for a small team (5-12 people) within the given timeline.
        """
        method_name = "validate_project_scope"
        fallback = {
            "is_appropriate": True,
            "scope_rating": "appropriate",
            "score": 5,
            "feedback": "Scope analysis unavailable. Proceed with your definition.",
            "suggestions": [],
            "example_refined_definition": "",
        }

        logger.info(
            f"[AI SERVICE] Calling Gemini - method={method_name} | "
            f"timeline_days={timeline_days} | project_type={project_type}"
        )

        prompt = f"""
SYSTEM CONTEXT:
You are a civic project scoping expert for a platform that coordinates small citizen
action teams. Effective projects on this platform must be completable by 5-12 people
within 30-90 days and must have a measurable, observable outcome.

TASK:
Analyze the provided project success definition and determine if it is appropriately
scoped for:
- Team size: 5 to 12 volunteers
- Timeline: {timeline_days} days
- Project type: {project_type}

Identify if the scope is too broad (unrealistic for small team), too vague (no measurable
outcome), appropriately scoped (achievable and specific), or too small (could be done
by 1-2 people alone).

INPUT:
Project Type: {project_type}
Timeline: {timeline_days} days
Success Definition: \"\"\"{success_definition}\"\"\"

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- scope_rating must be exactly one of: "too_broad", "too_vague", "appropriate", "too_small"
- score must be an integer between 1 and 10
- suggestions must contain exactly 2 or 3 items

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "is_appropriate": false,
  "scope_rating": "too_broad",
  "score": 3,
  "feedback": "The success definition 'end elderly isolation across all of India' is far too broad for a team of 5-12 people in 90 days. India has 140 million elderly citizens - no small volunteer team can address this at national scale. The ambition is admirable but the scope makes the project impossible to start or complete.",
  "suggestions": [
    "Narrow the geographic scope to one specific neighborhood or ward - for example, 'Navrangpura ward in Ahmedabad' instead of 'all of India'.",
    "Define a specific, countable outcome - for example, '30 elderly residents connected with weekly visitor volunteers' instead of 'end isolation'.",
    "Set a measurable completion threshold - for example, 'minimum 85% of matched residents report weekly contact for 8 consecutive weeks'."
  ],
  "example_refined_definition": "30 elderly residents above age 70 in Navrangpura ward, Ahmedabad, have been matched with trained volunteer visitors who make at least one in-person visit per week for 8 consecutive weeks, with attendance documented in a shared log and a minimum 80% volunteer retention rate."
}}

CONSTRAINTS:
- Be specific in your feedback - mention the exact problematic phrase from the input.
- The example_refined_definition must be realistic and achievable within {timeline_days} days by 5-12 volunteers.
- Do not be unnecessarily harsh - if scope is appropriate, say so clearly with score 7-10.

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            required_keys = [
                "is_appropriate",
                "scope_rating",
                "score",
                "feedback",
                "suggestions",
                "example_refined_definition",
            ]
            for key in required_keys:
                if key not in result:
                    raise KeyError(f"Missing required key: {key}")

            result["is_appropriate"] = self._coerce_bool(
                result.get("is_appropriate"),
                "is_appropriate",
                method_name,
                default=True,
            )

            result["score"] = self._coerce_int(result.get("score"), "score", method_name, default=5)
            result["score"] = max(1, min(10, result["score"]))

            valid_ratings = {"too_broad", "too_vague", "appropriate", "too_small"}
            if result.get("scope_rating") not in valid_ratings:
                logger.warning(
                    f"[AI SERVICE] INVALID VALUE - method={method_name} | "
                    f"field=scope_rating | value={result.get('scope_rating')} | default=appropriate"
                )
                result["scope_rating"] = "appropriate"

            if not isinstance(result.get("feedback"), str):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    f"field=feedback | original_type={type(result.get('feedback')).__name__}"
                )
                result["feedback"] = str(result.get("feedback", ""))

            if not isinstance(result.get("example_refined_definition"), str):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    "field=example_refined_definition | coercing to string"
                )
                result["example_refined_definition"] = str(result.get("example_refined_definition", ""))

            if not isinstance(result.get("suggestions"), list):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    "field=suggestions | coercing to empty list"
                )
                result["suggestions"] = []
            result["suggestions"] = [str(item) for item in result["suggestions"]][:3]

            logger.info(
                f"[AI SERVICE] SUCCESS - method={method_name} | "
                f"is_appropriate={result['is_appropriate']} | "
                f"scope_rating={result['scope_rating']} | score={result['score']}"
            )
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)

    def suggest_project_roles(self, project_type: str, domain: str, problem_statement: str) -> dict:
        """
        Suggests 3-5 appropriate civic team roles for a project based on its type,
        domain, and problem description.
        """
        method_name = "suggest_project_roles"
        fallback = {"suggested_roles": []}

        logger.info(
            f"[AI SERVICE] Calling Gemini - method={method_name} | "
            f"project_type={project_type} | domain={domain}"
        )

        prompt = f"""
SYSTEM CONTEXT:
You are a civic project design expert helping organizers build effective small teams.
You understand what roles are needed for different types of civic action projects.

TASK:
Suggest 3 to 5 team roles that would be needed for the civic project described below.
Each role must be specific, actionable, and appropriate for a volunteer contributor
spending 2-8 hours per week. The roles should collectively cover all the work
needed to complete the project successfully.

INPUT:
Project Type: {project_type}
Domain: {domain}
Problem Statement: \"\"\"{problem_statement}\"\"\"

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- suggested_roles must contain between 3 and 5 role objects.
- recommended_skills for each role must contain 2 to 4 skill names from this list:
  Web Development, Mobile Development, Data Analysis, Data Visualization, UI/UX Design,
  Graphic Design, Video Production, Photography, Writing/Editing, Research, GIS Mapping,
  Social Media Content Creation, Copywriting, Law, Medicine, Public Health, Finance,
  Accounting, Project Management, Grant Writing, Fundraising, Teaching/Education,
  Social Work, Journalism, Community Outreach, Community Facilitation, Public Speaking,
  Event Planning, Conflict Resolution, Volunteer Management, Local Government Navigation,
  Stakeholder Engagement, Logistics, Administration, PR/Media Relations, Budgeting

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "suggested_roles": [
    {{
      "title": "Community Outreach Coordinator",
      "description": "Build relationships with local elderly residents and their families. Map isolated individuals in the target area using community contacts, temple records, and local hospital outreach. Recruit and brief volunteer visitors. Serve as the primary point of contact for residents and families.",
      "recommended_skills": ["Community Outreach", "Volunteer Management", "Public Speaking"],
      "hours_per_week": 4.0,
      "is_mvt_required": true
    }},
    {{
      "title": "Volunteer Training and Support Lead",
      "description": "Design and deliver a 2-hour onboarding session for all volunteer visitors covering how to build rapport with elderly residents, conversation techniques, signs of health deterioration, and visit documentation. Provide ongoing support to volunteers.",
      "recommended_skills": ["Teaching/Education", "Social Work", "Event Planning"],
      "hours_per_week": 3.0,
      "is_mvt_required": true
    }},
    {{
      "title": "Documentation and Impact Reporting Lead",
      "description": "Maintain the shared visit log spreadsheet. Track visit frequency, resident feedback, and volunteer retention metrics. Prepare monthly progress updates and final outcome reporting.",
      "recommended_skills": ["Data Analysis", "Writing/Editing", "Research"],
      "hours_per_week": 2.5,
      "is_mvt_required": false
    }}
  ]
}}

CONSTRAINTS:
- All role titles must be specific to this project - do not use generic titles like "General Volunteer".
- hours_per_week must be a realistic float between 1.5 and 8.0.
- is_mvt_required should be true only for roles without which the project cannot start.
- Mark no more than 2 roles as is_mvt_required=true.
- All recommended_skills must come from the provided skill list above.

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            if "suggested_roles" not in result:
                raise KeyError("Missing required key: suggested_roles")

            if not isinstance(result["suggested_roles"], list):
                raise TypeError("suggested_roles must be a list")

            validated_roles = []
            mvt_count = 0
            for index, role in enumerate(result["suggested_roles"]):
                if not isinstance(role, dict):
                    logger.warning(
                        f"[AI SERVICE] INVALID ROLE TYPE - method={method_name} | "
                        f"index={index} | type={type(role).__name__}"
                    )
                    continue

                required_keys = [
                    "title",
                    "description",
                    "recommended_skills",
                    "hours_per_week",
                    "is_mvt_required",
                ]
                missing = [key for key in required_keys if key not in role]
                if missing:
                    logger.warning(
                        f"[AI SERVICE] ROLE MISSING KEYS - method={method_name} | "
                        f"index={index} | missing={missing}"
                    )
                    continue

                title = str(role.get("title", "")).strip()
                description = str(role.get("description", "")).strip()

                recommended_skills = role.get("recommended_skills", [])
                if not isinstance(recommended_skills, list):
                    logger.warning(
                        f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                        f"field=recommended_skills | role_index={index} | coercing to empty list"
                    )
                    recommended_skills = []
                recommended_skills = [str(skill) for skill in recommended_skills][:4]

                hours_per_week = self._coerce_float(
                    role.get("hours_per_week"),
                    "hours_per_week",
                    method_name,
                    default=3.0,
                )
                hours_per_week = max(1.5, min(8.0, hours_per_week))

                is_mvt_required = self._coerce_bool(
                    role.get("is_mvt_required"),
                    "is_mvt_required",
                    method_name,
                    default=False,
                )
                if is_mvt_required:
                    if mvt_count >= 2:
                        logger.warning(
                            f"[AI SERVICE] CONSTRAINT ADJUSTMENT - method={method_name} | "
                            f"role_index={index} | forcing is_mvt_required=False"
                        )
                        is_mvt_required = False
                    else:
                        mvt_count += 1

                validated_roles.append(
                    {
                        "title": title,
                        "description": description,
                        "recommended_skills": recommended_skills,
                        "hours_per_week": round(hours_per_week, 1),
                        "is_mvt_required": is_mvt_required,
                    }
                )

            result["suggested_roles"] = validated_roles[:5]
            logger.info(
                f"[AI SERVICE] SUCCESS - method={method_name} | "
                f"roles_generated={len(result['suggested_roles'])}"
            )
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)

    def generate_outcome_draft(
        self,
        project_title: str,
        domain: str,
        milestones_data: list,
        tasks_completed: int,
        tasks_total: int,
        team_size: int,
        timeline_days: int,
    ) -> dict:
        """
        Generates a structured outcome report draft based on project's
        milestone and task completion data.
        """
        method_name = "generate_outcome_draft"
        completion_pct = round((tasks_completed / tasks_total * 100) if tasks_total > 0 else 0)
        milestones_summary = "\n".join(
            [
                (
                    f"  - {item.get('title', 'Unnamed')}: "
                    f"{'COMPLETED' if item.get('completed') else 'INCOMPLETE'} "
                    f"({item.get('tasks_done', 0)}/{item.get('tasks_total', 0)} tasks done)"
                )
                for item in milestones_data
            ]
        )

        fallback = {
            "outcome_achieved": "",
            "measurable_data_suggestions": [],
            "lessons_learned_draft": "",
            "unexpected_challenges_draft": "",
            "completion_percentage": completion_pct,
        }

        logger.info(
            f"[AI SERVICE] Calling Gemini - method={method_name} | "
            f"project={project_title} | completion_pct={completion_pct}% | team_size={team_size}"
        )

        prompt = f"""
SYSTEM CONTEXT:
You are helping a civic project team document what they achieved. This documentation
will be published publicly and may serve as a template for other communities worldwide.
Write in an honest, specific, and inspiring tone - not boastful, but genuinely proud
of concrete accomplishments.

TASK:
Generate a structured outcome report draft for the civic project described below.
Base the draft on the actual task completion data provided.

INPUT:
Project Title: {project_title}
Domain: {domain}
Team Size: {team_size} people
Timeline: {timeline_days} days
Tasks Completed: {tasks_completed} out of {tasks_total} total tasks ({completion_pct}% completion)

Milestones Progress:
{milestones_summary if milestones_summary else '  - No milestones were defined'}

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- outcome_achieved must be between 100 and 200 words.
- measurable_data_suggestions must contain exactly 3 items.
- Do NOT invent specific numbers the project did not achieve - use placeholders like [X] for values the creator needs to fill in.

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "outcome_achieved": "Over 60 days, a team of 6 dedicated volunteers successfully mapped and connected [X] elderly residents in Navrangpura, Ahmedabad with regular visitor volunteers. The team completed 87% of planned project tasks including resident identification, volunteer recruitment and training, and visit coordination. All 3 project milestones were completed on schedule. The project established a functioning weekly visit rotation serving [X] residents, with volunteers documenting each visit in a shared tracking system. By project end, [X] volunteers had completed the onboarding session and were actively visiting assigned residents. The project exceeded its initial goal of connecting 30 residents and has now been handed off to a community trust for indefinite continuation.",
  "measurable_data_suggestions": [
    "How many residents were identified, approached, and ultimately matched with a volunteer visitor?",
    "What was the average number of visits per resident per week, and what percentage of volunteers maintained consistent visits throughout the project period?",
    "How many volunteer visitors completed training and how many were still active at the end of the project (retention rate)?"
  ],
  "lessons_learned_draft": "The most significant learning was that trust-building with isolated residents takes far longer than expected - typically 2-3 introductory visits before a resident felt comfortable with a new volunteer. Future teams should plan 2 additional weeks at the start specifically for relationship-building before beginning the formal visit rotation.",
  "unexpected_challenges_draft": "Several residents initially refused participation due to privacy concerns and fear of strangers - a barrier we had not anticipated in our planning. We also underestimated the time required to coordinate volunteer schedules across different availability windows.",
  "completion_percentage": 87
}}

CONSTRAINTS:
- Use [X] as a placeholder wherever a specific number is needed that the creator must fill in.
- The tone must be honest - if only 60% of tasks were completed, reflect that accurately.
- lessons_learned_draft and unexpected_challenges_draft should be based on typical challenges for {domain} domain projects.

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            required_keys = [
                "outcome_achieved",
                "measurable_data_suggestions",
                "lessons_learned_draft",
                "unexpected_challenges_draft",
            ]
            for key in required_keys:
                if key not in result:
                    raise KeyError(f"Missing required key: {key}")

            for text_key in ["outcome_achieved", "lessons_learned_draft", "unexpected_challenges_draft"]:
                if not isinstance(result.get(text_key), str):
                    logger.warning(
                        f"[AI SERVICE] TYPE COERCION - method={method_name} | field={text_key}"
                    )
                    result[text_key] = str(result.get(text_key, ""))

            suggestions = result.get("measurable_data_suggestions")
            if not isinstance(suggestions, list):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    "field=measurable_data_suggestions | coercing to empty list"
                )
                suggestions = []
            result["measurable_data_suggestions"] = [str(item) for item in suggestions][:3]
            result["completion_percentage"] = completion_pct

            logger.info(
                f"[AI SERVICE] SUCCESS - method={method_name} | "
                f"outcome_word_count={len(result.get('outcome_achieved', '').split())}"
            )
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)

    def personalized_recommendations(
        self,
        user_skills: list,
        user_domains: list,
        user_city: str,
        user_country: str,
        completed_project_titles: list,
        available_hours_per_week: int,
    ) -> dict:
        """
        Generates a personalized recommendation explanation for discover pages.
        """
        method_name = "personalized_recommendations"
        skills_str = ", ".join(user_skills[:10]) if user_skills else "No skills listed yet"
        domains_str = ", ".join(user_domains) if user_domains else "No domain preferences set"
        completed_str = ", ".join(completed_project_titles[:5]) if completed_project_titles else "No projects completed yet"

        fallback = {
            "recommendation_headline": "Projects matching your skills",
            "recommendation_explanation": "Browse projects below that match your profile.",
            "top_skill_matches": user_skills[:3] if user_skills else [],
            "suggested_search_terms": user_domains[:3] if user_domains else [],
        }

        logger.info(
            f"[AI SERVICE] Calling Gemini - method={method_name} | "
            f"city={user_city} | skills_count={len(user_skills)} | domains={domains_str}"
        )

        prompt = f"""
SYSTEM CONTEXT:
You are a personalization engine for Quorum, a civic action platform.
Your job is to write a warm, specific, encouraging explanation of why certain
types of projects would be a great fit for this specific user based on their profile.

TASK:
Generate a personalized project recommendation explanation for this user.
The explanation should feel like it was written by a knowledgeable friend who
knows both the user and the civic project landscape in their area.

INPUT (User Profile):
City: {user_city}
Country: {user_country}
Skills: {skills_str}
Domain Interests: {domains_str}
Available Hours Per Week: {available_hours_per_week} hours
Projects Already Completed: {completed_str}

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- recommendation_explanation should be 80-120 words.
- top_skill_matches must contain 3 to 5 skill strings.
- suggested_search_terms must contain 3 to 4 strings.

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "recommendation_headline": "Your community outreach skills are exactly what 3 active projects in Ahmedabad need right now.",
  "recommendation_explanation": "Based on your skills in Community Outreach, Volunteer Management, and Event Planning, you are ideally suited for direct service and community coordination projects. With {available_hours_per_week} hours per week available, you can meaningfully contribute to a 60-90 day project without overcommitting. Projects in the community and health domains in Ahmedabad are currently actively assembling teams - and outreach coordinators are the most-requested role across active projects in your city. Your experience from past projects will also help you hit the ground running. We have highlighted the best matches for you below.",
  "top_skill_matches": [
    "Community Outreach",
    "Volunteer Management",
    "Event Planning"
  ],
  "suggested_search_terms": [
    "Community - Ahmedabad - Assembling Team",
    "Health - City Scope - 2-5 hrs/week",
    "Direct Service - India - Outreach Coordinator role"
  ]
}}

CONSTRAINTS:
- Reference the user's actual city and skills specifically - do not be generic.
- If the user has completed projects, acknowledge their experience.
- Do not promise specific outcomes - be encouraging but honest.
- available_hours_per_week={available_hours_per_week}: tailor urgency accordingly
  (low hours = suggest smaller roles, high hours = suggest creator or lead roles).

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            required_keys = [
                "recommendation_headline",
                "recommendation_explanation",
                "top_skill_matches",
                "suggested_search_terms",
            ]
            for key in required_keys:
                if key not in result:
                    raise KeyError(f"Missing required key: {key}")

            for text_key in ["recommendation_headline", "recommendation_explanation"]:
                if not isinstance(result.get(text_key), str):
                    logger.warning(f"[AI SERVICE] TYPE COERCION - method={method_name} | field={text_key}")
                    result[text_key] = str(result.get(text_key, ""))

            for list_key in ["top_skill_matches", "suggested_search_terms"]:
                value = result.get(list_key)
                if not isinstance(value, list):
                    logger.warning(
                        f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                        f"field={list_key} | coercing to empty list"
                    )
                    value = []
                result[list_key] = [str(item) for item in value]

            result["top_skill_matches"] = result["top_skill_matches"][:5]
            result["suggested_search_terms"] = result["suggested_search_terms"][:4]

            logger.info(f"[AI SERVICE] SUCCESS - method={method_name}")
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)

    def ai_template_search(self, user_query: str, templates_summary: list) -> dict:
        """
        Fuzzy-matches user's natural language query to the most relevant templates.
        """
        method_name = "ai_template_search"
        fallback = {"matched_template_ids": [], "match_explanations": {}}

        logger.info(
            f"[AI SERVICE] Calling Gemini - method={method_name} | "
            f"query='{(user_query or '')[:100]}' | templates_count={len(templates_summary)}"
        )

        templates_text = "\n".join(
            [
                (
                    f"  ID {item['id']}: \"{item['title']}\" | Domain: {item['domain']} | "
                    f"Problem: {str(item.get('problem_archetype', 'N/A'))[:100]}"
                )
                for item in templates_summary[:20]
                if isinstance(item, dict) and "id" in item and "title" in item and "domain" in item
            ]
        )

        prompt = f"""
SYSTEM CONTEXT:
You are a semantic search engine for a civic action template library.
You understand that users may describe problems in casual, imprecise language
and your job is to match them to the most relevant proven civic action templates.

TASK:
Given the user's search query and the list of available templates, identify which
templates are most relevant to what the user is looking for. Consider semantic
meaning - the user may use different words than the template titles.
Return up to 5 best matches ordered by relevance (most relevant first).
If no templates are a good match, return an empty list.

INPUT:
User Query: "{user_query}"

Available Templates:
{templates_text if templates_text else 'No templates available.'}

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- matched_template_ids must be a list of integer IDs from the available templates above.
- Only include IDs that exist in the provided template list.
- match_explanations keys must be string versions of the template IDs.
- If no templates match, return empty list and empty object.

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "matched_template_ids": [3, 7, 1],
  "match_explanations": {
    "3": "This template addresses elderly social isolation through structured volunteer visitor programs - a direct match for your query about helping lonely older people.",
    "7": "This community befriending network template is slightly broader but includes components specifically for elderly residents in urban neighborhoods.",
    "1": "This general community connection template could be adapted for elderly isolation, though it is less specific than templates 3 and 7."
  }
}}

CONSTRAINTS:
- Do not return template IDs that do not exist in the provided list.
- matched_template_ids must contain integer values, not strings.
- Return a maximum of 5 template IDs.

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            if "matched_template_ids" not in result:
                raise KeyError("Missing required key: matched_template_ids")

            valid_ids = {item.get("id") for item in templates_summary if isinstance(item, dict) and "id" in item}
            cleaned_ids = []
            for value in result.get("matched_template_ids", []):
                converted = self._coerce_int(value, "matched_template_ids", method_name, default=-1)
                if converted in valid_ids and converted not in cleaned_ids:
                    cleaned_ids.append(converted)

            match_explanations = result.get("match_explanations", {})
            if not isinstance(match_explanations, dict):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | "
                    "field=match_explanations | coercing to empty object"
                )
                match_explanations = {}

            filtered_explanations = {
                str(template_id): str(match_explanations.get(str(template_id), "")).strip()
                for template_id in cleaned_ids
                if str(match_explanations.get(str(template_id), "")).strip()
            }

            result["matched_template_ids"] = cleaned_ids[:5]
            result["match_explanations"] = filtered_explanations

            logger.info(
                f"[AI SERVICE] SUCCESS - method={method_name} | "
                f"matches_found={len(result['matched_template_ids'])}"
            )
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)

    def fetch_civic_pulse(self, city: str, country: str, domain_interests: list) -> dict:
        """
        Uses Gemini with Google Search grounding to fetch real-time civic news
        and insights relevant to the user's city and domain interests.
        """
        method_name = "fetch_civic_pulse"
        domains_str = ", ".join(domain_interests) if domain_interests else "general community issues"

        fallback = {
            "civic_stories": [],
            "overall_summary": "Civic pulse data unavailable.",
            "last_updated": datetime.utcnow().isoformat(),
        }

        logger.info(
            f"[AI SERVICE] Calling Gemini WITH GOOGLE SEARCH GROUNDING - "
            f"method={method_name} | city={city} | domains={domains_str}"
        )

        prompt = f"""
SYSTEM CONTEXT:
You are a civic intelligence assistant for Quorum, a civic action platform.
Search the web for the latest real-world civic developments, grassroots success stories,
and community challenges in the specified location and domains.

TASK:
Search for and summarize 3 to 5 recent civic news stories or community developments
from {city}, {country} (or nearby region if nothing specific to that city)
related to these domains: {domains_str}.

Focus on:
- Recent grassroots community projects that succeeded or are currently active
- Local civic problems that are currently unsolved or actively being discussed
- Community organizations, citizen groups, or government initiatives making impact
- Anything that would inspire or inform citizens wanting to take civic action

INPUT:
City: {city}
Country: {country}
Domain Interests: {domains_str}
Current date: Search for news from the last 90 days.

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- civic_stories must contain 3 to 5 story objects.
- If you cannot find real news, generate plausible and realistic civic stories for that city/domain.

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "overall_summary": "Ahmedabad is seeing growing citizen-led activity around urban heat island mitigation and Sabarmati riverfront community access, with several grassroots groups forming in the last 3 months.",
  "civic_stories": [
    {{
      "title": "Citizens Launch Tree Plantation Drive in East Ahmedabad Industrial Zones",
      "summary": "A group of residents from Vatva and Naroda have started a weekly tree plantation initiative targeting heat-affected industrial corridors. They are currently recruiting volunteers for weekend sessions.",
      "relevance": "This directly relates to your environment domain interest and shows active citizen organizing in Ahmedabad.",
      "source_hint": "Ahmedabad Mirror / Times of India Ahmedabad"
    }},
    {{
      "title": "Navrangpura Residents Association Secures Park Renovation Approval",
      "summary": "After months of organized advocacy, the residents association secured approval for renovating underused parks into active community spaces. The group used a petition and public meetings to build their case.",
      "relevance": "A strong example of how small organized groups can achieve civic change through structured advocacy in your city.",
      "source_hint": "Divya Bhaskar / Gujarat Samachar"
    }},
    {{
      "title": "Urban Food Waste Redistribution Network Pilots in SG Highway Restaurants",
      "summary": "Restaurants in the SG Highway corridor partnered with a citizen-organized food redistribution team to redirect daily surplus food to community kitchens.",
      "relevance": "A successful completed civic project with a documented outcome - a strong template for replication.",
      "source_hint": "Ahmedabad Times / Gujarat government press releases"
    }}
  ],
  "last_updated": "2026-04-14T10:30:00"
}}

CONSTRAINTS:
- source_hint should be a plausible local news source for that city/country.
- All stories must be geographically relevant (city or nearby region).
- Do not fabricate specific statistics you cannot verify - use approximate language.
- last_updated must be today's date in ISO 8601 format.

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name, use_grounding=True)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            if "civic_stories" not in result:
                raise KeyError("Missing required key: civic_stories")
            if "overall_summary" not in result:
                raise KeyError("Missing required key: overall_summary")

            if not isinstance(result.get("overall_summary"), str):
                logger.warning(
                    f"[AI SERVICE] TYPE COERCION - method={method_name} | field=overall_summary"
                )
                result["overall_summary"] = str(result.get("overall_summary", ""))

            if not isinstance(result.get("civic_stories"), list):
                raise TypeError("civic_stories must be a list")

            cleaned_stories = []
            for index, story in enumerate(result.get("civic_stories", [])):
                if not isinstance(story, dict):
                    logger.warning(
                        f"[AI SERVICE] INVALID STORY TYPE - method={method_name} | "
                        f"index={index} | type={type(story).__name__}"
                    )
                    continue
                cleaned_stories.append(
                    {
                        "title": str(story.get("title", "")).strip(),
                        "summary": str(story.get("summary", "")).strip(),
                        "relevance": str(story.get("relevance", "")).strip(),
                        "source_hint": str(story.get("source_hint", "")).strip(),
                    }
                )

            result["civic_stories"] = cleaned_stories[:5]
            result["last_updated"] = str(result.get("last_updated") or datetime.utcnow().isoformat())

            logger.info(
                f"[AI SERVICE] SUCCESS - method={method_name} | "
                f"stories_found={len(result['civic_stories'])}"
            )
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)

    def discover_civic_challenges(self, geography: str, domain: str) -> dict:
        """
        Uses Gemini with Google Search grounding to surface real civic problems
        in a specified geography and domain that have not been addressed yet.
        """
        method_name = "discover_civic_challenges"
        fallback = {"challenges": []}

        logger.info(
            f"[AI SERVICE] Calling Gemini WITH GOOGLE SEARCH GROUNDING - "
            f"method={method_name} | geography={geography} | domain={domain}"
        )

        prompt = f"""
SYSTEM CONTEXT:
You are a civic intelligence researcher for Quorum, a platform that helps citizen
teams organize and address real community problems. Your job is to identify real,
current, unaddressed or under-addressed civic problems in a specific geography
and domain that a small volunteer team (5-12 people) could meaningfully address.

TASK:
Search the web for real civic challenges in {geography} related to {domain}.
Find 3 to 5 specific, concrete problems that:
1. Are real and currently exist (not hypothetical)
2. Have NOT been effectively addressed by citizen action yet
3. Are small enough for a team of 5-12 volunteers to make meaningful progress in 60-90 days
4. Would benefit from organized citizen coordination rather than just government action

INPUT:
Geography: {geography}
Domain: {domain}

IMPORTANT INSTRUCTIONS:
- You must respond with ONLY a valid JSON object.
- Do NOT include any markdown formatting, code fences, backticks, or explanation text.
- Do NOT write anything before or after the JSON.
- Return raw JSON only.
- Follow EXACTLY the schema shown in the EXAMPLE OUTPUT below.
- challenges must contain 3 to 5 challenge objects.
- difficulty must be exactly one of: "beginner", "intermediate", "advanced"
- estimated_team_size must be an integer between 3 and 12
- suggested_timeline_days must be exactly 30, 60, or 90

EXAMPLE OUTPUT (use this exact schema with your own generated values):
{{
  "challenges": [
    {{
      "title": "Air Quality Citizen Monitoring Network - Vatva Industrial Zone, Ahmedabad",
      "description": "Vatva, one of Ahmedabad's most polluted industrial areas, has no citizen-operated air quality monitoring. Government sensors exist but are sparse and data is not community-accessible.",
      "rationale": "Government data is publicly available but not analyzed or communicated at a community level. A citizen team could establish local monitoring points and publish monthly public reports.",
      "estimated_team_size": 7,
      "suggested_timeline_days": 60,
      "difficulty": "intermediate"
    }},
    {{
      "title": "Sabarmati Riverbank Informal Settlement Waste Collection Gap",
      "description": "Informal settlements along the Sabarmati riverbank have irregular municipal waste collection, with open dumping affecting resident health and river quality.",
      "rationale": "A citizen advocacy team could document the gap between official service coverage and actual service delivery and escalate with evidence.",
      "estimated_team_size": 8,
      "suggested_timeline_days": 30,
      "difficulty": "beginner"
    }},
    {{
      "title": "Urban Heat Island Mapping and Tree Cover Advocacy - East Ahmedabad",
      "description": "Eastern Ahmedabad experiences significantly higher temperatures due to industrial heat generation and limited tree cover.",
      "rationale": "A team with data collection and GIS skills could create a citizen-generated heat map to support ward-level advocacy for tree plantation drives.",
      "estimated_team_size": 6,
      "suggested_timeline_days": 90,
      "difficulty": "advanced"
    }}
  ]
}}

CONSTRAINTS:
- All challenges must be genuinely relevant to {geography} and {domain}.
- Be specific - mention actual neighborhood names, institutions, or specific gaps.
- Do not suggest challenges requiring government authority or large budgets.
- Focus on what organized volunteers can realistically accomplish.

Now generate the actual JSON response for the input provided above. Return ONLY the JSON object, nothing else.
"""

        raw_response: Optional[str] = None
        try:
            raw_response = self._generate_content(prompt, method_name, use_grounding=True)
            result = self._extract_json(raw_response, method_name, expected_type=dict)

            if "challenges" not in result:
                raise KeyError("Missing required key: challenges")
            if not isinstance(result.get("challenges"), list):
                raise TypeError("challenges must be a list")

            valid_difficulties = {"beginner", "intermediate", "advanced"}
            valid_timelines = {30, 60, 90}
            cleaned = []

            for index, challenge in enumerate(result.get("challenges", [])):
                if not isinstance(challenge, dict):
                    logger.warning(
                        f"[AI SERVICE] INVALID CHALLENGE TYPE - method={method_name} | "
                        f"index={index} | type={type(challenge).__name__}"
                    )
                    continue

                required = [
                    "title",
                    "description",
                    "rationale",
                    "estimated_team_size",
                    "suggested_timeline_days",
                    "difficulty",
                ]
                missing = [key for key in required if key not in challenge]
                if missing:
                    logger.warning(
                        f"[AI SERVICE] CHALLENGE MISSING KEYS - method={method_name} | "
                        f"index={index} | missing={missing}"
                    )
                    continue

                estimated_team_size = self._coerce_int(
                    challenge.get("estimated_team_size"),
                    "estimated_team_size",
                    method_name,
                    default=6,
                )
                estimated_team_size = max(3, min(12, estimated_team_size))

                suggested_timeline_days = self._coerce_int(
                    challenge.get("suggested_timeline_days"),
                    "suggested_timeline_days",
                    method_name,
                    default=60,
                )
                if suggested_timeline_days not in valid_timelines:
                    logger.warning(
                        f"[AI SERVICE] INVALID VALUE - method={method_name} | "
                        f"field=suggested_timeline_days | value={suggested_timeline_days} | default=60"
                    )
                    suggested_timeline_days = 60

                difficulty = str(challenge.get("difficulty", "intermediate")).strip().lower()
                if difficulty not in valid_difficulties:
                    logger.warning(
                        f"[AI SERVICE] INVALID VALUE - method={method_name} | "
                        f"field=difficulty | value={difficulty} | default=intermediate"
                    )
                    difficulty = "intermediate"

                cleaned.append(
                    {
                        "title": str(challenge.get("title", "")).strip(),
                        "description": str(challenge.get("description", "")).strip(),
                        "rationale": str(challenge.get("rationale", "")).strip(),
                        "estimated_team_size": estimated_team_size,
                        "suggested_timeline_days": suggested_timeline_days,
                        "difficulty": difficulty,
                    }
                )

            result["challenges"] = cleaned[:5]
            logger.info(
                f"[AI SERVICE] SUCCESS - method={method_name} | "
                f"challenges_found={len(result['challenges'])}"
            )
            return result

        except InvalidArgument as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ResourceExhausted as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except ServiceUnavailable as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except DeadlineExceeded as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except json.JSONDecodeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except KeyError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except TypeError as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)
        except AIParsingError as error:
            return self._handle_method_error(method_name, error, fallback, error.raw_response)
        except Exception as error:
            return self._handle_method_error(method_name, error, fallback, raw_response)


def refresh_all_civic_pulse():
    users = User.query.filter_by(onboarding_complete=True).all()
    service = AIService()

    for user in users:
        pulse_data = service.fetch_civic_pulse(
            user.city,
            user.country,
            user.domain_interests or [],
        )
        content = format_civic_pulse_content(pulse_data)

        cache = AICivicPulseCache.query.filter_by(user_id=user.id).first()
        if not cache:
            cache = AICivicPulseCache(user_id=user.id, content=content)
            db.session.add(cache)
        else:
            cache.content = content

        from app.utils import utcnow

        cache.generated_at = utcnow()

    db.session.commit()
