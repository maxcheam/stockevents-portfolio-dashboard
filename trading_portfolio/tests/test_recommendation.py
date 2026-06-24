"""Tests for entry / hold / take profit recommendation logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from jeff_sun_trading_coach import analyze_trade_description, load_rules, score_entry
from jeff_sun_trading_coach.entry_framework import EntrySignals
from jeff_sun_trading_coach.recommendation import (
    RECOMMENDATION_LINE_PREFIX,
    VERDICT_SYNTHESIS_HEADER,
    assess_relative_strength,
    build_verdict_synthesis,
    compute_trade_recommendation,
    parse_position_context,
    parse_unrealized_pnl,
    resolve_unrealized_pnl,
)
from positions_dashboard import derive_current_positions_from_trades, run_coach_for_position

RULES = load_rules()
STOCK_EVENTS = Path(__file__).resolve().parents[1] / "stock_events_transactions_2026-06-23.csv"


def test_parse_position_context_computes_pnl_from_avg_and_current():
    pos = parse_position_context(
        "AAPL current holding 100 shares at avg cost $100.00",
        current_price=92.0,
    )
    assert pos.is_holding
    assert pos.net_shares == 100
    assert pos.avg_cost == 100.0
    assert pos.unrealized_pnl == pytest.approx(-800.0)
    assert pos.unrealized_pnl_pct == pytest.approx(-8.0)
    assert resolve_unrealized_pnl("AAPL current holding 100 shares at avg cost $100", position=pos) == pytest.approx(-800.0)


def test_holding_underwater_from_avg_cost_current_price_cut_losses():
    signals = EntrySignals(
        rvol=0.8,
        adr_pct=2.0,
        atr_from_50ma=1.0,
        relative_strength=True,
        trade_against_declining_200ma=False,
    )
    scores = score_entry(signals, RULES)
    pos = parse_position_context(
        "AAPL current holding 100 shares at avg cost $100.00",
        current_price=90.0,
    )
    rec = compute_trade_recommendation(
        description="AAPL current holding 100 shares at avg cost $100.00",
        entry_scores=scores,
        violations=[],
        signals=signals,
        rules=RULES,
        current_price=90.0,
        position=pos,
    )
    assert rec.action == "cut losses"
    assert "underwater" in rec.reason.lower() or "800" in rec.reason or "unrealized" in rec.reason.lower()


def test_build_verdict_synthesis_includes_position_context():
    sig = EntrySignals(rs_line_new_highs=True, is_vars=True, vars_trend="rising")
    scores = score_entry(sig, RULES)
    pos = parse_position_context(
        "NVDA current holding 50 shares at avg cost $100.00",
        current_price=115.0,
    )
    rec = compute_trade_recommendation(
        description="NVDA current holding 50 shares at avg cost $100.00",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
        current_price=115.0,
        position=pos,
    )
    synthesis = build_verdict_synthesis(sig, rec, position=pos)
    joined = " ".join(synthesis.observations)
    assert "50 shares" in joined
    assert "avg cost" in joined.lower()
    assert "Current price" in joined or "115" in joined
    assert "Cost basis gain" in joined or "Unrealized P&L" in joined


def test_parse_unrealized_pnl_from_description():
    assert parse_unrealized_pnl("current holding, unrealized loss $1,250") == -1250.0
    assert parse_unrealized_pnl("unrealized gain $500") == 500.0
    assert parse_unrealized_pnl("no pnl here") is None


def test_losing_extended_holding_becomes_cut_losses_not_take_profit():
    signals = EntrySignals(atr_from_50ma=5.2, rvol=2.0, adr_pct=6.0, relative_strength=True)
    scores = {k: "PASS" for k in score_entry(signals, RULES)}
    rec = compute_trade_recommendation(
        description="AAPL current holding 100 shares, unrealized loss $800",
        entry_scores=scores,
        violations=[],
        signals=signals,
        rules=RULES,
    )
    assert rec.action == "cut losses"
    assert "take profit" not in rec.format_line().lower()
    assert "cut losses" in rec.format_line().lower()


def test_winning_extended_holding_stays_take_profit():
    signals = EntrySignals(atr_from_50ma=5.2, rvol=2.0, adr_pct=6.0, relative_strength=True)
    scores = {k: "PASS" for k in score_entry(signals, RULES)}
    rec = compute_trade_recommendation(
        description="AAPL current holding 100 shares, unrealized gain $800",
        entry_scores=scores,
        violations=[],
        signals=signals,
        rules=RULES,
    )
    assert rec.action == "take profit"


def test_compute_recommendation_take_profit_when_extended():
    signals = EntrySignals(atr_from_50ma=5.2, rvol=2.0, adr_pct=6.0, relative_strength=True)
    scores = {k: "PASS" for k in score_entry(signals, RULES)}
    rec = compute_trade_recommendation(
        description="AAPL current holding 100 shares",
        entry_scores=scores,
        violations=[],
        signals=signals,
        rules=RULES,
    )
    assert rec.action == "take profit"
    assert "take profit" in rec.format_line().lower()


def test_non_holding_at_4x_atr_is_hold_not_take_profit():
    signals = EntrySignals(atr_from_50ma=4.0, rvol=2.0, adr_pct=6.0, relative_strength=True)
    scores = {k: "PASS" for k in score_entry(signals, RULES)}
    rec = compute_trade_recommendation(
        description="NVDA stock swing trade, RVOL 2x, set break-even stop",
        entry_scores=scores,
        violations=[],
        signals=signals,
        rules=RULES,
    )
    assert rec.action == "hold"
    assert "take profit" not in rec.format_line().lower()
    assert "not suitable for entry" in rec.reason.lower()
    assert "take profit" not in rec.format_line().lower()


def test_holding_at_4x_atr_is_take_profit():
    signals = EntrySignals(atr_from_50ma=4.0, rvol=2.0, adr_pct=6.0, relative_strength=True)
    scores = {k: "PASS" for k in score_entry(signals, RULES)}
    rec = compute_trade_recommendation(
        description="NVDA current holding 50 shares at avg cost $100",
        entry_scores=scores,
        violations=[],
        signals=signals,
        rules=RULES,
    )
    assert rec.action == "take profit"
    assert "scale" in rec.reason.lower() or "4x" in rec.reason.lower()


def test_compute_recommendation_hold_for_existing_position():
    signals = EntrySignals(
        rvol=0.8,
        adr_pct=2.0,
        atr_from_50ma=1.0,
        relative_strength=True,
        trade_against_declining_200ma=False,
    )
    scores = score_entry(signals, RULES)
    rec = compute_trade_recommendation(
        description="AAPL current holding 100 shares",
        entry_scores=scores,
        violations=[],
        signals=signals,
        rules=RULES,
    )
    assert rec.action == "hold"


def test_analyze_non_holding_4x_emits_not_suitable_for_entry_in_trade_line():
    market_signals = EntrySignals(
        atr_from_50ma=4.0,
        rvol=2.0,
        adr_pct=6.0,
        relative_strength=True,
        trade_against_declining_200ma=False,
    )
    desc = "NVDA stock swing trade, RVOL 2x ADR 6%, set break-even stop"
    result = analyze_trade_description(desc, rules=RULES, market_signals=market_signals)
    rec_line = next(
        line for line in result.splitlines() if line.startswith(RECOMMENDATION_LINE_PREFIX)
    )
    assert "HOLD" in rec_line
    assert "not suitable for entry" in rec_line.lower()


def test_analyze_trade_description_includes_recommendation_line():
    desc = "NVDA stock swing trade, RVOL 2x ADR 6%, VCP tight, set break-even stop"
    result = analyze_trade_description(desc, rules=RULES)
    assert RECOMMENDATION_LINE_PREFIX in result
    lower = result.lower()
    assert "entry" in lower or "hold" in lower or "take profit" in lower


def test_strong_rs_vars_promotes_entry_from_marginal_scores():
    sig = EntrySignals(
        rs_line_new_highs=True,
        rs_line_leading_price=True,
        rs_line_status="Confirming Strength",
        is_vars=True,
        vars_trend="rising",
        rvol=2.8,
        adr_pct=8.5,
        vcp=True,
        atr_from_50ma=1.8,
        relative_strength=True,
        lod_atr_pct=25,
        trade_against_declining_200ma=False,
    )
    scores = score_entry(sig, RULES)
    rec = compute_trade_recommendation(
        description="NVDA stock swing trade, set break-even stop",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
    )
    assert rec.action == "entry"
    assert "RS" in rec.reason or "strength" in rec.reason.lower()
    assert "VARS" in rec.reason or "confirming" in rec.reason.lower()


def test_compute_auto_detects_lod_violation_when_violations_list_empty():
    """Hard rules from infographic: LoD >60% ATR blocks entry even if violations=[] passed."""
    sig = EntrySignals(
        rs_line_new_highs=True,
        is_vars=True,
        vars_trend="rising",
        rvol=2.8,
        adr_pct=8.5,
        vcp=True,
        atr_from_50ma=1.8,
        relative_strength=True,
        lod_atr_pct=75,
        trade_against_declining_200ma=False,
    )
    scores = score_entry(sig, RULES)
    rec = compute_trade_recommendation(
        description="NVDA stock swing trade, set break-even stop",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
    )
    assert rec.action == "hold"
    assert "hard-rule" in rec.reason.lower() or "violation" in rec.reason.lower()


def test_compute_auto_detects_low_rvol_when_violations_list_empty():
    sig = EntrySignals(
        rs_line_new_highs=True,
        is_vars=True,
        rvol=0.8,
        adr_pct=6.0,
        vcp=True,
        atr_from_50ma=1.5,
        relative_strength=True,
        lod_atr_pct=25,
        trade_against_declining_200ma=False,
    )
    scores = score_entry(sig, RULES)
    rec = compute_trade_recommendation(
        description="NVDA stock swing trade",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
    )
    assert rec.action == "hold"
    assert "hard-rule" in rec.reason.lower() or "violation" in rec.reason.lower()


def test_strong_rs_does_not_promote_entry_when_hard_rule_violations():
    """RS-first promote must not override hard-rule hold."""
    sig = EntrySignals(
        rs_line_new_highs=True,
        rs_line_leading_price=True,
        is_vars=True,
        vars_trend="rising",
        rvol=2.8,
        adr_pct=8.5,
        vcp=True,
        atr_from_50ma=1.8,
        relative_strength=True,
        trade_against_declining_200ma=False,
    )
    scores = score_entry(sig, RULES)
    violations = ["LoD exceeds 60% ATR at entry"]
    rec = compute_trade_recommendation(
        description="NVDA stock swing trade, set break-even stop",
        entry_scores=scores,
        violations=violations,
        signals=sig,
        rules=RULES,
    )
    assert rec.action == "hold"
    assert "hard-rule" in rec.reason.lower() or "violation" in rec.reason.lower()
    assert "not suitable for entry" in rec.reason.lower()


def test_strong_rs_does_not_promote_entry_when_against_declining_200ma():
    sig = EntrySignals(
        rs_line_new_highs=True,
        is_vars=True,
        vars_trend="rising",
        rvol=2.8,
        adr_pct=8.5,
        vcp=True,
        atr_from_50ma=1.8,
        relative_strength=True,
        trade_against_declining_200ma=True,
    )
    scores = score_entry(sig, RULES)
    rec = compute_trade_recommendation(
        description="NVDA stock swing trade, set break-even stop",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
    )
    assert rec.action == "hold"
    assert "hard-rule" in rec.reason.lower() or "declining 200-ma" in rec.reason.lower()


def test_analyze_strong_rs_with_hard_violations_stays_hold_not_entry():
    sig = EntrySignals(
        rs_line_new_highs=True,
        is_vars=True,
        rvol=2.5,
        adr_pct=6.0,
        vcp=True,
        atr_from_50ma=2.0,
        relative_strength=True,
        lod_atr_pct=75,
        trade_against_declining_200ma=False,
    )
    desc = (
        "NVDA stock swing, RS line making new highs, VARS confirming, "
        "LoD 75% ATR, set break-even stop"
    )
    raw = analyze_trade_description(desc, rules=RULES, market_signals=sig, symbol="NVDA")
    rec_line = next(
        line for line in raw.splitlines() if line.startswith(RECOMMENDATION_LINE_PREFIX)
    )
    assert "HOLD" in rec_line
    assert "ENTRY" not in rec_line.split("—")[0]
    assert "hard-rule" in rec_line.lower() or "violation" in rec_line.lower()


def test_weak_rs_blocks_entry_despite_partial_passes():
    sig = EntrySignals(
        rs_line_new_highs=False,
        is_vars=False,
        rvol=2.0,
        adr_pct=6.0,
        vcp=True,
        atr_from_50ma=2.0,
        relative_strength=True,
    )
    scores = score_entry(sig, RULES)
    rec = compute_trade_recommendation(
        description="TEST stock swing breakout",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
    )
    assert rec.action == "hold"
    assert "not suitable" in rec.reason.lower() or "rs" in rec.reason.lower()


def test_build_verdict_synthesis_includes_observations_and_bottom_line():
    sig = EntrySignals(rs_line_new_highs=True, is_vars=True, vars_trend="rising")
    scores = score_entry(sig, RULES)
    rec = compute_trade_recommendation(
        description="NVDA swing",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
    )
    rs = assess_relative_strength(sig)
    assert rs.tier == "strong"
    assert any("RS line" in o for o in rs.observations)
    synthesis = build_verdict_synthesis(sig, rec, rs_assessment=rs)
    assert synthesis is not None
    assert synthesis.bottom_line
    assert len(synthesis.observations) >= 2


def test_analyze_includes_verdict_synthesis_block():
    sig = EntrySignals(
        rs_line_new_highs=True,
        is_vars=True,
        rvol=2.5,
        adr_pct=6.0,
        vcp=True,
        atr_from_50ma=2.0,
        relative_strength=True,
    )
    raw = analyze_trade_description(
        "NVDA stock swing, set break-even stop",
        rules=RULES,
        market_signals=sig,
        symbol="NVDA",
    )
    assert VERDICT_SYNTHESIS_HEADER in raw
    assert "Bottom Line" in raw
    assert "Key Observations" in raw


def test_run_coach_for_position_includes_recommendation():
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    raw = run_coach_for_position(positions[0])
    assert RECOMMENDATION_LINE_PREFIX in raw
    assert any(
        term in raw.lower() for term in ("entry", "hold", "take profit")
    )