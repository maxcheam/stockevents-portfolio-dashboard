"""StockEvents CSV loader, current positions, and trading coach integration tests."""

from __future__ import annotations

from pathlib import Path

from jeff_sun_trading_coach import analyze_trades, load_rules, load_trades_csv
from positions_dashboard import (
    DEFAULT_STRATEGY,
    HORIZON_LABELS,
    STRATEGY_OPTIONS,
    derive_current_positions_from_trades,
    resolve_strategy,
    run_coach_for_position,
    run_coach_for_positions,
)

STOCK_EVENTS = (
    Path(__file__).resolve().parent.parent / "stock_events_transactions_2026-06-23.csv"
)


def test_stock_events_loads_and_builds_positions():
    assert STOCK_EVENTS.exists()
    df = load_trades_csv(STOCK_EVENTS)
    assert "strategy" in df.columns
    assert (df["strategy"] == "Stock").all()
    report = analyze_trades(df)
    assert report.metrics["position_count"] > 0
    assert report.metrics["equity_position_count"] > 0


def test_stock_events_entry_framework_not_scored_from_fills():
    report = analyze_trades(load_trades_csv(STOCK_EVENTS))
    assert report.metrics["entry_framework_verifiable"] == 0


def test_stock_events_long_term_horizon_improves_compliance():
    df = load_trades_csv(STOCK_EVENTS)
    swing = analyze_trades(df, horizon="swing")
    long_term = analyze_trades(df, horizon="long_term")
    assert long_term.horizon == "long_term"
    assert long_term.metrics["t3_compliance_rate"] >= swing.metrics["t3_compliance_rate"]


def test_derive_current_positions_via_load_trades_csv():
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    assert len(positions) > 0
    fills = load_trades_csv(STOCK_EVENTS)
    assert fills is not None
    for pos in positions:
        assert pos.net_shares > 0
        assert pos.symbol
        assert pos.avg_cost >= 0


def test_strategy_defaults_to_swing_trade_strategy():
    assert DEFAULT_STRATEGY == "Swing"
    assert resolve_strategy(None) == "Swing"
    assert resolve_strategy("") == "Swing"
    assert resolve_strategy("unknown") == "Swing"
    assert "Swing" in STRATEGY_OPTIONS


def test_run_coach_on_all_positions_default_swing():
    from jeff_sun_trading_coach.market_context import auto_field_criterion_labels

    rules = load_rules()
    auto_keys = tuple(auto_field_criterion_labels(rules).values())
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    results = run_coach_for_positions(positions)
    assert len(results) == len(positions)
    for symbol, outcome in results.items():
        assert "JEFF SUN" in outcome
        assert HORIZON_LABELS["Swing"] in outcome
        assert len(outcome) > 50
        assert "Market context: auto-computed" in outcome
        assert "data-derived" in outcome
        scored = 0
        for key in auto_keys:
            crit_line = next(
                (line for line in outcome.splitlines() if key in line and line.strip().startswith("[")),
                None,
            )
            assert crit_line is not None, f"{symbol}: missing scored line for {key}"
            assert "[PASS]" in crit_line or "[FAIL]" in crit_line, (
                f"{symbol}: {key} not PASS/FAIL — {crit_line!r}"
            )
            scored += 1
        assert scored == len(auto_keys), f"{symbol}: auto_scored={scored}/{len(auto_keys)}"


def test_run_coach_auto_metrics_strict_seven_hermetic():
    """Strict 7 data-derived auto criteria — synthetic OHLCV only (no live yfinance)."""
    from jeff_sun_trading_coach import analyze_trade_description, load_rules
    from jeff_sun_trading_coach.market_context import AUTO_COMPUTED_FIELDS, compute_signals_from_ohlcv
    from coach_outcome_formatter import build_coach_outcome_display
    from tests.test_market_context import _make_ohlcv

    sym = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench = _make_ohlcv(260, close_start=100, close_end=120)
    market_signals = compute_signals_from_ohlcv(sym, bench)
    raw = analyze_trade_description(
        "TEST stock swing trade, set break-even stop",
        market_signals=market_signals,
        rules=load_rules(),
    )
    display = build_coach_outcome_display(raw)
    assert display.has_auto_metrics
    assert len(display.auto_criteria) == len(AUTO_COMPUTED_FIELDS)
    assert all(c.is_pass or c.is_fail for c in display.auto_criteria)
    assert all(
        c.detail and "(data-derived)" in c.detail.lower() for c in display.auto_criteria
    )
    assert display.view.market_notes
    assert any("liquidity" in n.lower() or "VCP" in n for n in display.view.market_notes)


def test_run_coach_respects_mid_term_and_long_term_strategy():
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    pos = positions[0]
    mid = run_coach_for_position(pos, "Mid term")
    long_term = run_coach_for_position(pos, "Long term")
    assert HORIZON_LABELS["Mid term"] in mid
    assert HORIZON_LABELS["Long term"] in long_term