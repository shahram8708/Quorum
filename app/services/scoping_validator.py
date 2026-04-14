OVERSCOPE_SIGNALS = {
    "end",
    "eliminate",
    "solve",
    "fix",
    "transform",
    "eradicate",
    "nationally",
    "globally",
    "all",
    "every",
    "entire city",
    "whole country",
}

UNDERSCOPE_SIGNALS = {
    "raise awareness",
    "start conversation",
    "bring attention",
    "make people aware",
    "educate the public",
}


def validate_scope(success_definition: str, timeline_days: int) -> dict:
    text = (success_definition or "").lower()

    over_hits = [signal for signal in OVERSCOPE_SIGNALS if signal in text]
    under_hits = [signal for signal in UNDERSCOPE_SIGNALS if signal in text]

    if over_hits and timeline_days <= 90:
        return {
            "is_valid": False,
            "warning_type": "over_scope",
            "message": (
                "This success definition appears overly broad for a small team in this timeline. "
                f"Potential scope flags: {', '.join(over_hits[:4])}."
            ),
        }

    if under_hits and timeline_days >= 60:
        return {
            "is_valid": False,
            "warning_type": "under_scope",
            "message": (
                "This success definition may be too vague for measurable impact. "
                f"Potential clarity gaps: {', '.join(under_hits[:4])}."
            ),
        }

    return {"is_valid": True, "warning_type": None, "message": None}
