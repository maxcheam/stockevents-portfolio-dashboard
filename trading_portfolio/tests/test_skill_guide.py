"""SKILL.md content coverage vs Complete Trading Guide infographic."""

from __future__ import annotations

from pathlib import Path

from jeff_sun_trading_coach.rules import SKILL_PATH, load_rules

SKILL_TEXT = SKILL_PATH.read_text(encoding="utf-8")
RULES = load_rules()


def test_skill_contains_entry_framework_guide_terms():
    for term in (
        "VARs",
        "Volatility Adjusted Relative Strength",
        "nbgyYwu1",
        "VARS Status",
        "RS Line New Highs Status",
        "Relative Strength First, Setup Second",
        "RS line making new highs",
        "ORMA",
        "ORMA reclaim",
        "Pocket pivots",
        "Institutional accumulation",
        "LoD",
        "spring coil",
        "launched",
    ):
        assert term.lower() in SKILL_TEXT.lower(), f"missing: {term}"


def test_skill_contains_workflow_and_math():
    for term in (
        "Post-Market Process",
        "Pre-Market Routine",
        "5%+",
        "13+",
        "5% monthly",
        "Sell some into strength",
        "declining 200-MA",
        "Think in 10s of trades",
        "A-rated setup with C-rated entry",
        "add aggressively when oversold",
        "sustainable lifestyle",
        "pocket pivots",
    ):
        assert term in SKILL_TEXT, f"missing: {term}"


def test_rules_entry_framework_parsed_from_skill():
    items = RULES.entry_framework
    joined = " ".join(items).lower()
    assert "vars" in joined
    assert "rs line" in joined
    assert "orma" in joined
    assert len(items) >= 8


def test_rules_profit_taking_parsed_from_skill():
    joined = " ".join(RULES.profit_taking_atr).lower()
    assert "6x atr" in joined
    assert "10x" in joined
    assert "let winners run with trail stops" in joined
    assert "golden rule" in joined


def test_rules_three_stop_parsed_from_skill():
    joined = " ".join(RULES.three_stop_strategy).lower()
    assert "1–2 days" in joined or "1-2 days" in joined
    assert "sell 1/3" in joined
    assert "1r" in joined and "2r" in joined and "3r" in joined


def test_rules_benchmark_avg_win_is_6r():
    assert RULES.benchmark_avg_win_r == 6.0
    assert ">6R" in SKILL_TEXT or "6.0" in SKILL_TEXT