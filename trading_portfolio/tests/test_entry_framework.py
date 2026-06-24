"""Unit tests for shared score_entry — synthetic signals, no fixtures."""

from __future__ import annotations

import pytest

from jeff_sun_trading_coach import EntrySignals, load_rules, score_entry
from jeff_sun_trading_coach.entry_framework import (
    count_verifiable_entry,
    detect_hard_rule_violations,
    extract_entry_price,
    parse_description_to_signals,
    score_entry_fill_only,
)

RULES = load_rules()


def test_score_entry_all_pass():
    signals = EntrySignals(
        vcp=True,
        rvol=2.0,
        atr_from_50ma=3.0,
        relative_strength=True,
        adr_pct=6.0,
        lod_atr_pct=45.0,
        is_vars=True,
        rs_line_new_highs=True,
        orma_reclaim=True,
        launched=True,
        trade_against_declining_200ma=False,
        avg_dollar_volume_m=20.0,
    )
    scores = score_entry(signals, RULES)
    assert all(v == "PASS" for v in scores.values())


def test_score_entry_rvol_fail():
    signals = EntrySignals(vcp=True, rvol=1.0, atr_from_50ma=3.0, relative_strength=True)
    scores = score_entry(signals, RULES)
    assert scores[f"RVOL >= {RULES.min_rvol}x"] == "FAIL"


def test_score_entry_atr_fail():
    signals = EntrySignals(vcp=True, rvol=2.0, atr_from_50ma=5.0, relative_strength=True)
    scores = score_entry(signals, RULES)
    assert scores[f"ATR < {RULES.max_atr_from_50ma}x from 50-MA"] == "FAIL"


def test_score_entry_missing_signals_review():
    signals = EntrySignals()
    scores = score_entry(signals, RULES)
    assert all(v.startswith("REVIEW") for v in scores.values())


def test_score_entry_fill_only_not_applicable():
    scores = score_entry_fill_only(RULES, partial_scale_out=True)
    assert scores["VCP / Tight Price Action"].startswith("NOT_APPLICABLE")
    assert scores["Profit-taking scale-out (fill proxy)"] == "PASS"


def test_parse_description_atr_3x():
    signals = parse_description_to_signals("ATR 3x from 50-MA, RVOL 2.1x, VCP breakout")
    assert signals.atr_from_50ma == pytest.approx(3.0)
    assert signals.rvol == pytest.approx(2.1)
    assert signals.vcp is True


def test_count_verifiable_entry_excludes_not_applicable():
    scores = score_entry_fill_only(RULES)
    passed, verifiable = count_verifiable_entry(scores)
    assert verifiable == 0
    assert passed == 0


def test_extract_entry_price_from_description():
    assert extract_entry_price("NVDA swing, entry at 142.50, set stop") == 142.5
    assert extract_entry_price("proposed entry price $155") == 155.0
    assert extract_entry_price("NVDA swing breakout no price stated") is None


def test_parse_description_vars_adr_lod():
    desc = (
        "NVDA VARS confirming strength, RS line making new highs, VCP breakout, "
        "RVOL 2.5x, ADR 6%, LoD at 40% ATR, ORMA reclaim, pocket pivot, launched"
    )
    signals = parse_description_to_signals(desc)
    assert signals.is_vars is True
    assert signals.rs_line_new_highs is True
    assert signals.adr_pct == 6.0
    assert signals.lod_atr_pct == 40.0
    assert signals.orma_reclaim is True
    assert signals.pocket_pivot is True
    assert signals.launched is True
    scores = score_entry(signals, RULES)
    assert scores["VARs confirming strength"] == "PASS"
    assert scores[f"ADR% >= {RULES.min_adr_pct:.0f}%"] == "PASS"
    assert scores[f"LoD within {RULES.max_lod_atr_pct:.0f}% ATR"] == "PASS"
    assert scores["ORMA reclaim at entry"] == "PASS"


def test_parse_description_rs_line_status_structured_format():
    desc = """Ticker: NVDA
RS Line New Highs Status: Confirming Strength
Strength Confirmation Verdict
RS line making new highs confirms strength."""
    signals = parse_description_to_signals(desc)
    assert signals.rs_line_new_highs is True
    assert score_entry(signals, RULES)["RS line making new highs"] == "PASS"


def test_parse_description_rs_line_status_approaching_is_review():
    desc = "Ticker: ABC\nRS Line New Highs Status: Approaching or Mixed"
    signals = parse_description_to_signals(desc)
    assert signals.rs_line_new_highs is None
    assert score_entry(signals, RULES)["RS line making new highs"].startswith("REVIEW")


def test_parse_description_vars_status_structured_format():
    desc = """Ticker: NVDA
Analysis Date / Time: 2026-06-24 09:30
VARS Status: Confirming Strength
Key Observations
- VARS rising, histogram bars positive
Strength Confirmation Verdict
VARS is confirming strength on pullback to 20-MA."""
    signals = parse_description_to_signals(desc)
    assert signals.is_vars is True
    scores = score_entry(signals, RULES)
    assert scores["VARs confirming strength"] == "PASS"


def test_parse_description_vars_status_not_confirming():
    desc = "Ticker: XYZ\nVARS Status: Not Confirming\nBottom Line: avoid new longs"
    signals = parse_description_to_signals(desc)
    assert signals.is_vars is False
    assert score_entry(signals, RULES)["VARs confirming strength"] == "FAIL"


def test_parse_description_vars_status_mixed_is_review():
    desc = "Ticker: ABC\nVARS Status: Mixed\nhistogram flat"
    signals = parse_description_to_signals(desc)
    assert signals.is_vars is None
    assert score_entry(signals, RULES)["VARs confirming strength"].startswith("REVIEW")


def test_parse_description_orma_reclaim_primary():
    signals = parse_description_to_signals("NVDA ORMA reclaim at breakout, RVOL 2x")
    assert signals.orma_reclaim is True
    scores = score_entry(signals, RULES)
    assert scores["ORMA reclaim at entry"] == "PASS"


def test_detect_hard_rule_violations_lod_and_200ma():
    desc = "chased breakout, lod at 70% ATR, trading against declining 200-MA"
    signals = parse_description_to_signals(desc)
    violations = detect_hard_rule_violations(desc, signals, RULES)
    assert any("LoD exceeds" in v for v in violations)
    assert any("chasing" in v.lower() for v in violations)
    assert any("200-MA" in v for v in violations)


def test_detect_hard_rule_violations_no_duplicate_lod():
    desc = "lod at 70% ATR breakout"
    signals = parse_description_to_signals(desc)
    violations = detect_hard_rule_violations(desc, signals, RULES)
    lod_violations = [v for v in violations if "LoD exceeds" in v]
    assert len(lod_violations) == 1


def test_parse_description_negative_signals_score_fail():
    desc = "no vars, rs line not making new highs, no orma, not launched, weak relative strength"
    signals = parse_description_to_signals(desc)
    assert signals.is_vars is False
    assert signals.rs_line_new_highs is False
    assert signals.orma_reclaim is False
    assert signals.launched is False
    assert signals.relative_strength is False
    scores = score_entry(signals, RULES)
    assert scores["VARs confirming strength"] == "FAIL"
    assert scores["RS line making new highs"] == "FAIL"
    assert scores["ORMA reclaim at entry"] == "FAIL"
    assert scores['Launched signal (tight + RVOL)'] == "FAIL"