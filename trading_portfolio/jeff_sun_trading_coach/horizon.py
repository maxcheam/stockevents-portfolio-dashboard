"""Trade horizon detection and confirmation timelines."""

from __future__ import annotations

from typing import Literal

TradeHorizon = Literal["swing", "mid_term", "long_term"]

HORIZON_LABELS: dict[TradeHorizon, str] = {
    "swing": "swing (days to ~2 weeks)",
    "mid_term": "mid-term (weeks to ~3 months)",
    "long_term": "long-term (months to years)",
}

# Days after entry before a non-working loser is flagged (swing = Jeff Sun T+3).
CONFIRMATION_DAYS: dict[TradeHorizon, int | None] = {
    "swing": 3,
    "mid_term": 21,
    "long_term": None,
}

_LONG_TERM_PATTERNS = (
    "long-term",
    "long term",
    "longterm",
    "buy and hold",
    "hold for years",
    "hold for months",
    "multi-year",
    "multi year",
    "investment thesis",
    "core holding",
    "years",
)

_MID_TERM_PATTERNS = (
    "mid-term",
    "mid term",
    "midterm",
    "medium-term",
    "medium term",
    "position trade",
    "position hold",
    "hold for weeks",
    "1-3 month",
    "1 to 3 month",
    "2-4 week",
    "2 to 4 week",
    "quarterly",
    "months",
)

_SWING_PATTERNS = (
    "swing",
    "swing trade",
    "t+3",
    "day t+3",
    "few days",
    "1-2 week",
    "1 to 2 week",
)


def detect_trade_horizon(text: str) -> TradeHorizon:
    """Infer trade horizon from free-text description. Defaults to swing."""
    lower = text.lower()
    if any(p in lower for p in _LONG_TERM_PATTERNS):
        return "long_term"
    if any(p in lower for p in _MID_TERM_PATTERNS):
        return "mid_term"
    if any(p in lower for p in _SWING_PATTERNS):
        return "swing"
    return "swing"


def horizon_label(horizon: TradeHorizon) -> str:
    return HORIZON_LABELS[horizon]


def confirmation_days(horizon: TradeHorizon) -> int | None:
    return CONFIRMATION_DAYS[horizon]


def is_t3_compliant(
    hold_days: int,
    is_winner: bool,
    horizon: TradeHorizon = "swing",
) -> bool:
    """Return whether hold duration satisfies horizon-specific confirmation rule."""
    if is_winner:
        return True
    days = confirmation_days(horizon)
    if days is None:
        return True
    return hold_days < days


HORIZON_CLI_ALIASES: dict[str, TradeHorizon] = {
    "swing": "swing",
    "mid-term": "mid_term",
    "mid_term": "mid_term",
    "midterm": "mid_term",
    "long-term": "long_term",
    "long_term": "long_term",
    "longterm": "long_term",
}


def parse_horizon_arg(value: str) -> TradeHorizon:
    """Parse CLI --horizon value. Raises ValueError on unknown input."""
    key = value.strip().lower().replace(" ", "-")
    if key not in HORIZON_CLI_ALIASES:
        allowed = ", ".join(sorted({"swing", "mid-term", "long-term"}))
        raise ValueError(f"Unknown horizon {value!r}; expected one of: {allowed}")
    return HORIZON_CLI_ALIASES[key]


def confirmation_score_label(horizon: TradeHorizon) -> str:
    if horizon == "swing":
        return "T+3 confirmation compliance"
    if horizon == "mid_term":
        return "21-day confirmation compliance (mid-term)"
    return "Quarterly confirmation compliance (long-term)"


def confirmation_rate_label(horizon: TradeHorizon) -> str:
    if horizon == "swing":
        return "T+3 compliance rate"
    if horizon == "mid_term":
        return "21-day confirmation compliance rate (mid-term)"
    return "Confirmation compliance rate (long-term)"


def confirmation_position_label(horizon: TradeHorizon) -> str:
    if horizon == "swing":
        return "T+3"
    if horizon == "mid_term":
        return "21-day confirmation"
    return "Long-term confirmation"


def confirmation_violation_note(horizon: TradeHorizon, failure_count: int) -> str:
    if horizon == "swing":
        return (
            f"T+3 rule: {failure_count} position(s) held losers past Day T+3 — exit earlier."
        )
    if horizon == "mid_term":
        return (
            f"Mid-term confirmation: {failure_count} position(s) held losers past "
            "21-day window — re-evaluate thesis or exit."
        )
    return (
        f"Long-term review: {failure_count} position(s) held as extended losers — "
        "quarterly thesis check recommended."
    )


def fill_validation_intro(horizon: TradeHorizon) -> str:
    label = horizon_label(horizon)
    return (
        f"Fill-level validation ({label}) covers R-multiples, session hard rules, "
        "3-stop proxy, and horizon-specific confirmation — not equity VCP/RVOL/ATR "
        "entry criteria (use --describe for setup analysis)."
    )


def data_limitation_horizon_note(horizon: TradeHorizon) -> str:
    label = horizon_label(horizon)
    days = confirmation_days(horizon)
    if days is None:
        return (
            f"Confirmation compliance uses {label}; swing T+3 does not apply — "
            "stops and quarterly review still required."
        )
    if horizon == "swing":
        return (
            f"Confirmation compliance uses {label} (default when --horizon omitted)."
        )
    return (
        f"Confirmation compliance uses {label} ({days}-day loser hold threshold "
        "via --horizon)."
    )


def t3_guidance_for_horizon(horizon: TradeHorizon) -> list[str]:
    """Coaching lines for timeline / confirmation step."""
    if horizon == "swing":
        return [
            "6. T+3 RULE (SKILL.md §3 — swing trades):",
            "   By end of Day T+3 position must be working or exit.",
            "   Do not reduce or exit early before T+3 unless stop hit.",
        ]
    if horizon == "mid_term":
        return [
            "6. CONFIRMATION TIMELINE (SKILL.md §3 — mid-term trades):",
            "   Swing T+3 exit rule does not apply; allow 2–4 weeks for thesis to work.",
            "   Set 3-tier stops on Day T; review at weekly checkpoints.",
            "   Exit if thesis breaks or stop hit — do not let a mid-term drift into hope.",
        ]
    return [
        "6. CONFIRMATION TIMELINE (SKILL.md §3 — long-term trades):",
        "   T+3 swing confirmation does not apply; hold for thesis over months/years.",
        "   Stops and position sizing still mandatory; review at quarterly milestones.",
        "   Scale out into strength using ATR extensions; trail runners on winners.",
    ]