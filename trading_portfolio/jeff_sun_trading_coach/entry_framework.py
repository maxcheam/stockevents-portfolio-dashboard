"""Shared Entry Framework scoring — single source for coach and optional journal path."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .rules import JeffSunRules

# Jeff Sun screener workflow: sufficient avg $ volume limits slippage (see jfsrev process guide).
LIQUIDITY_MIN_AVG_DOLLAR_VOLUME_M: float = 10.0
LIQUIDITY_CRITERION: str = (
    f"Avg $ volume >= ${LIQUIDITY_MIN_AVG_DOLLAR_VOLUME_M:.0f}M (liquidity)"
)


@dataclass(frozen=True)
class EntrySignals:
    vcp: bool | None = None
    avg_dollar_volume_m: float | None = None
    rvol: float | None = None
    atr_from_50ma: float | None = None
    relative_strength: bool | None = None
    adr_pct: float | None = None
    lod_atr_pct: float | None = None
    is_vars: bool | None = None
    vars_reading: float | None = None
    vars_trend: str | None = None
    rs_line_new_highs: bool | None = None
    rs_line_leading_price: bool | None = None
    rs_line_status: str | None = None
    orma_reclaim: bool | None = None
    pocket_pivot: bool | None = None
    institutional: bool | None = None
    launched: bool | None = None
    trade_against_declining_200ma: bool | None = None


def score_entry(signals: EntrySignals, rules: JeffSunRules) -> dict[str, str]:
    """Pure scorer: PASS | FAIL | REVIEW per criterion from explicit signals."""
    scores: dict[str, str] = {}

    if signals.is_vars is None:
        scores["VARs confirming strength"] = "REVIEW — not stated"
    else:
        scores["VARs confirming strength"] = "PASS" if signals.is_vars else "FAIL"

    if signals.relative_strength is None:
        scores["Relative Strength vs market/sector"] = "REVIEW — not stated"
    else:
        scores["Relative Strength vs market/sector"] = (
            "PASS" if signals.relative_strength else "FAIL"
        )

    if signals.rs_line_new_highs is None:
        scores["RS line making new highs"] = "REVIEW — not stated"
    else:
        scores["RS line making new highs"] = "PASS" if signals.rs_line_new_highs else "FAIL"

    if signals.vcp is None:
        scores["VCP / Tight Price Action"] = "REVIEW — not stated"
    else:
        scores["VCP / Tight Price Action"] = "PASS" if signals.vcp else "FAIL"

    if signals.rvol is None:
        scores[f"RVOL >= {rules.min_rvol}x"] = "REVIEW — not stated"
    else:
        scores[f"RVOL >= {rules.min_rvol}x"] = (
            "PASS" if signals.rvol >= rules.min_rvol else "FAIL"
        )

    if signals.adr_pct is None:
        scores[f"ADR% >= {rules.min_adr_pct:.0f}%"] = "REVIEW — not stated"
    else:
        scores[f"ADR% >= {rules.min_adr_pct:.0f}%"] = (
            "PASS" if signals.adr_pct >= rules.min_adr_pct else "FAIL"
        )

    if signals.lod_atr_pct is None:
        scores[f"LoD within {rules.max_lod_atr_pct:.0f}% ATR"] = "REVIEW — not stated"
    else:
        scores[f"LoD within {rules.max_lod_atr_pct:.0f}% ATR"] = (
            "PASS" if signals.lod_atr_pct <= rules.max_lod_atr_pct else "FAIL"
        )

    if signals.atr_from_50ma is None:
        scores[f"ATR < {rules.max_atr_from_50ma}x from 50-MA"] = "REVIEW — not stated"
    else:
        scores[f"ATR < {rules.max_atr_from_50ma}x from 50-MA"] = (
            "PASS" if signals.atr_from_50ma <= rules.max_atr_from_50ma else "FAIL"
        )

    if signals.orma_reclaim is None:
        scores["ORMA reclaim at entry"] = "REVIEW — not stated"
    else:
        scores["ORMA reclaim at entry"] = "PASS" if signals.orma_reclaim else "FAIL"

    if signals.launched is None:
        scores['Launched signal (tight + RVOL)'] = "REVIEW — not stated"
    else:
        scores['Launched signal (tight + RVOL)'] = "PASS" if signals.launched else "FAIL"

    if signals.trade_against_declining_200ma is None:
        scores["200-MA trend (no trade against declining)"] = "REVIEW — not stated"
    else:
        scores["200-MA trend (no trade against declining)"] = (
            "FAIL" if signals.trade_against_declining_200ma else "PASS"
        )

    if signals.avg_dollar_volume_m is None:
        scores[LIQUIDITY_CRITERION] = "REVIEW — not stated"
    else:
        scores[LIQUIDITY_CRITERION] = (
            "PASS"
            if signals.avg_dollar_volume_m >= LIQUIDITY_MIN_AVG_DOLLAR_VOLUME_M
            else "FAIL"
        )

    return scores


def detect_hard_rule_violations(
    description: str,
    signals: EntrySignals,
    rules: JeffSunRules,
) -> list[str]:
    """Detect hard-rule violations from free-text description and parsed signals."""
    text = description.lower()
    violations: list[str] = []

    lod_pct = signals.lod_atr_pct
    if lod_pct is None:
        lod_match = re.search(r"lod\s*(?:at|of)?\s*([\d.]+)\s*%", text)
        if lod_match:
            lod_pct = float(lod_match.group(1))
    if lod_pct is not None and lod_pct > rules.max_lod_atr_pct:
        violations.append(rules.hard_rules[0])

    if signals.atr_from_50ma is not None and signals.atr_from_50ma > rules.max_atr_from_50ma:
        violations.append(rules.hard_rules[1])

    if signals.rvol is not None and signals.rvol < rules.min_rvol:
        violations.append(rules.hard_rules[2])

    if any(k in text for k in ("chase", "chasing", "chased", "chased in")):
        violations.append(rules.hard_rules[3])

    if signals.trade_against_declining_200ma is True:
        violations.append(rules.hard_rules[4])
    elif any(
        k in text
        for k in (
            "against 200",
            "below 200-ma",
            "under 200-ma",
            "declining 200",
            "against declining 200",
            "trading against declining 200-ma",
        )
    ):
        violations.append(rules.hard_rules[4])

    m = re.search(r"(\d+)\s*(?:new\s+)?position", text)
    if m and int(m.group(1)) > rules.max_new_positions_per_session:
        violations.append(rules.hard_rules[5])

    if any(k in text for k in ("within 30 min", "first 30 min", "30 min after open")):
        if "extreme rvol" not in text:
            violations.append(rules.hard_rules[6])

    if any(k in text for k in ("gap resistance", "into gap", "gap up resistance")):
        violations.append(rules.hard_rules[7])

    return violations


def guide_context_notes(signals: EntrySignals) -> list[str]:
    """Non-scored guide concepts detected in description text."""
    notes: list[str] = []
    if signals.pocket_pivot:
        notes.append("Pocket pivot detected — institutional accumulation day")
    if signals.institutional:
        notes.append("Institutional accumulation mentioned")
    if signals.launched:
        notes.append('Launched signal — tight price action + expanding RVOL')
    if signals.is_vars:
        notes.append("VARs confirming relative strength")
    if signals.rs_line_new_highs:
        notes.append("RS line making new highs")
    if signals.orma_reclaim:
        notes.append("ORMA reclaim entry")
    return notes


def score_entry_fill_only(rules: JeffSunRules, partial_scale_out: bool = False) -> dict[str, str]:
    """Fill-level historical path: VCP/RVOL/ATR/RS not derivable from broker fills."""
    na = "NOT_APPLICABLE — fill data lacks chart context"
    return {
        "VARs confirming strength": na,
        "Relative Strength vs market/sector": na,
        "RS line making new highs": na,
        "VCP / Tight Price Action": na,
        f"RVOL >= {rules.min_rvol}x": na,
        f"ADR% >= {rules.min_adr_pct:.0f}%": na,
        f"LoD within {rules.max_lod_atr_pct:.0f}% ATR": na,
        f"ATR < {rules.max_atr_from_50ma}x from 50-MA": na,
        "ORMA reclaim at entry": na,
        'Launched signal (tight + RVOL)': na,
        LIQUIDITY_CRITERION: na,
        "Profit-taking scale-out (fill proxy)": "PASS" if partial_scale_out else "REVIEW",
    }


def score_entry_adapted(strategy: str) -> dict[str, str]:
    return {
        "VARs confirming strength": "NOT_APPLICABLE — not equity breakout",
        "Relative Strength vs market/sector": "NOT_APPLICABLE — not equity breakout",
        "VCP / Tight Price Action": "NOT_APPLICABLE — not equity breakout",
        "RVOL": "NOT_APPLICABLE — not equity breakout",
        "ATR from 50-MA": "NOT_APPLICABLE — not equity breakout",
        f"Adapted tier: {strategy} (process/R/T+3 only)": "REVIEW",
    }


def _tri_state_bool(
    text: str,
    positive: tuple[str, ...],
    negative: tuple[str, ...],
) -> bool | None:
    if any(n in text for n in negative):
        return False
    if any(p in text for p in positive):
        return True
    return None


def _extract_vcp(text: str) -> bool | None:
    return _tri_state_bool(
        text,
        ("vcp", "contraction", "tight base", "tight price"),
        ("no vcp", "loose base", "erratic price", "not tight"),
    )


def _extract_relative_strength(text: str) -> bool | None:
    return _tri_state_bool(
        text,
        (
            "relative strength",
            "outperform",
            "rs line",
            "rs making",
            "sector highs",
            "market highs",
        ),
        ("weak relative strength", "no relative strength", "underperform"),
    )


def _extract_trade_against_declining_200ma(text: str) -> bool | None:
    return _tri_state_bool(
        text,
        (
            "against 200",
            "below 200-ma",
            "under 200-ma",
            "declining 200",
            "against declining 200",
            "trading against declining 200-ma",
            "against declining 200-ma",
        ),
        (
            "not against 200",
            "not against declining 200",
            "above 200-ma",
            "over 200-ma",
            "not declining 200",
            "200-ma rising",
        ),
    )


def _extract_avg_dollar_volume_m(text: str) -> float | None:
    patterns = (
        r"liquidity\s*([\d.]+)\s*m",
        r"high\s+liquidity\s*([\d.]+)\s*m",
        r"([\d.]+)\s*m\s*(?:avg\s*)?(?:daily\s*)?(?:\$?\s*)?vol(?:ume)?",
        r"\$\s*([\d.]+)\s*m\s*(?:avg\s*)?(?:daily\s*)?(?:\$?\s*)?vol(?:ume)?",
        r"avg\s*\$?\s*volume\s*([\d.]+)\s*m",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return float(match.group(1))
    return None


def _extract_rvol(text: str) -> float | None:
    m = re.search(r"rvol\s*[:=]?\s*([\d.]+)\s*x?", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s*x\s*rvol", text, re.I)
    return float(m.group(1)) if m else None


def _extract_atr_multiple(text: str) -> float | None:
    m = re.search(r"([\d.]+)\s*x\s*atr", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"atr\s*([\d.]+)\s*x", text, re.I)
    return float(m.group(1)) if m else None


def _extract_adr(text: str) -> float | None:
    m = re.search(r"adr\s*[:=]?\s*([\d.]+)\s*%?", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s*%\s*adr", text, re.I)
    return float(m.group(1)) if m else None


def _extract_lod_atr(text: str) -> float | None:
    m = re.search(r"lod\s*(?:at|of|within)?\s*([\d.]+)\s*%", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s*%\s*(?:of\s*)?atr\s*lod", text, re.I)
    return float(m.group(1)) if m else None


def extract_entry_price(description: str) -> float | None:
    """Parse proposed entry price from trade description.

    When None, callers must use ``resolve_price_for_check`` (market_context)
    to fall back to the current/last stock price.
    """
    text = description.lower()
    for pattern in (
        r"(?:proposed\s+)?entry\s*(?:price|at|@)\s*\$?([\d.]+)",
        r"enter\s*(?:at|@)\s*\$?([\d.]+)",
        r"entry\s*\$?([\d.]+)",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            return float(m.group(1))
    return None


def _extract_is_vars(text: str) -> bool | None:
    """Parse VARS strength from free text or structured VARS Status lines."""
    status = re.search(
        r"vars\s+status:\s*(confirming\s+strength|mixed|not\s+confirming)",
        text,
    )
    if status:
        label = status.group(1)
        if label == "confirming strength":
            return True
        if label == "not confirming":
            return False
        return None
    verdict = re.search(
        r"strength\s+confirmation\s+verdict.*?"
        r"(confirming\s+strength|not\s+confirming|does\s+not\s+confirm)",
        text,
        re.DOTALL,
    )
    if verdict:
        phrase = verdict.group(1)
        if phrase == "confirming strength":
            return True
        return False
    is_vars = _tri_state_bool(
        text,
        (
            "vars confirming",
            "vars confirm",
            "vars strength",
            "volatility adjusted relative strength confirming",
            "volatility-adjusted relative strength confirming",
        ),
        (
            "no vars",
            "weak vars",
            "vars failing",
            "vars not confirming",
            "not confirming strength",
        ),
    )
    if is_vars is None and re.search(
        r"\bvars?\b.*\b(confirming|positive|rising)\b", text
    ):
        is_vars = True
    if is_vars is None and re.search(r"\bvars?\b", text):
        is_vars = True
    return is_vars


def _extract_rs_line_new_highs(text: str) -> bool | None:
    """Parse RS line new-highs from free text or structured status lines."""
    status = re.search(
        r"rs\s+line\s+new\s+highs\s+status:\s*"
        r"(confirming\s+strength|approaching(?:\s+or\s+mixed)?|not\s+confirming)",
        text,
    )
    if status:
        label = status.group(1)
        if label == "confirming strength":
            return True
        if label.startswith("approaching"):
            return None
        return False
    return _tri_state_bool(
        text,
        (
            "rs line making new highs",
            "rs line new high",
            "rs line new highs",
            "rs line at new highs",
        ),
        ("rs line not making", "rs line failing", "no rs line", "rs line not confirming"),
    )


AUTO_FIELD_TEXT_EXTRACTORS: dict[str, Callable[[str], Any]] = {
    "rvol": _extract_rvol,
    "adr_pct": _extract_adr,
    "atr_from_50ma": _extract_atr_multiple,
    "relative_strength": _extract_relative_strength,
    "trade_against_declining_200ma": _extract_trade_against_declining_200ma,
    "vcp": _extract_vcp,
    "avg_dollar_volume_m": _extract_avg_dollar_volume_m,
    "is_vars": _extract_is_vars,
    "rs_line_new_highs": _extract_rs_line_new_highs,
}


def parse_description_to_signals(description: str) -> EntrySignals:
    """Extract entry signals from free-text trade description."""
    text = description.lower()

    auto_values = {
        field: extractor(text) for field, extractor in AUTO_FIELD_TEXT_EXTRACTORS.items()
    }
    vcp = auto_values["vcp"]
    rvol = auto_values["rvol"]

    is_vars = auto_values["is_vars"]
    orma = _tri_state_bool(
        text,
        (
            "orma reclaim",
            "orma entry",
            "opening range moving average",
            "orma breakout",
            "orh reclaim",
            "orh entry",
            "opening range high",
        ),
        ("no orma", "failed orma", "orma fail", "no orh", "failed orh"),
    )
    if orma is None and re.search(r"\borma\b", text):
        orma = True
    if orma is None and re.search(r"\borh\b", text):
        orma = True
    pocket = _tri_state_bool(
        text,
        ("pocket pivot", "pocket pivots"),
        ("no pocket pivot",),
    )
    institutional = _tri_state_bool(
        text,
        ("institutional accumulation", "institutional buying", "institutional"),
        ("no institutional", "weak institutional"),
    )
    launched = _tri_state_bool(
        text,
        ("launched", "launched signal"),
        ("not launched", "no launched", "failed launch"),
    )
    if launched is None and vcp and rvol is not None and rvol >= 1.5:
        launched = True

    return EntrySignals(
        vcp=auto_values["vcp"],
        avg_dollar_volume_m=auto_values["avg_dollar_volume_m"],
        rvol=auto_values["rvol"],
        atr_from_50ma=auto_values["atr_from_50ma"],
        relative_strength=auto_values["relative_strength"],
        adr_pct=auto_values["adr_pct"],
        lod_atr_pct=_extract_lod_atr(text),
        trade_against_declining_200ma=auto_values["trade_against_declining_200ma"],
        is_vars=is_vars,
        rs_line_new_highs=auto_values["rs_line_new_highs"],
        orma_reclaim=orma,
        pocket_pivot=pocket,
        institutional=institutional,
        launched=launched,
    )


def count_verifiable_entry(scores: dict[str, str]) -> tuple[int, int]:
    """Return (passed, verifiable) — excludes NOT_APPLICABLE and fill-proxy rows."""
    passed = verifiable = 0
    for key, status in scores.items():
        if status.startswith("NOT_APPLICABLE"):
            continue
        if "fill proxy" in key.lower():
            continue
        if status.startswith("REVIEW"):
            verifiable += 1
            continue
        verifiable += 1
        if status == "PASS":
            passed += 1
    return passed, verifiable