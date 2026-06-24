"""Tests for auto-computed market context EntrySignals."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jeff_sun_trading_coach import analyze_trade_description, load_rules, score_entry
from jeff_sun_trading_coach.entry_framework import (
    AUTO_FIELD_TEXT_EXTRACTORS,
    LIQUIDITY_CRITERION,
    EntrySignals,
    parse_description_to_signals,
)
from jeff_sun_trading_coach.market_context import (
    AUTO_COMPUTED_FIELDS,
    auto_criterion_values,
    auto_field_criterion_labels,
    auto_signal_summary,
    compute_avg_dollar_volume_m,
    compute_launch_orma_check,
    compute_lod_check_from_ohlcv,
    compute_orma_reclaim,
    current_price_from_ohlcv,
    compute_signals_from_ohlcv,
    resolve_price_for_check,
    compute_rs_line_new_highs_from_ohlcv,
    compute_rs_line_ratio_series,
    compute_vars_from_ohlcv,
    compute_vcp_contraction,
    data_derived_criterion_values,
    enrich_market_signals_launch_orma,
    format_launch_orma_live_analysis,
    format_lod_live_analysis,
    format_rs_line_live_analysis,
    format_vars_live_analysis,
    merge_entry_signals,
    website_process_notes,
)

RULES = load_rules()

AUTO_CRITERIA = tuple(auto_field_criterion_labels(RULES).values())


def _synthetic_market_signals():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120, last_volume_mult=1.0)
    return compute_signals_from_ohlcv(symbol_df, bench_df)


AUTO_FIELD_ISOLATION_CASES = (
    (
        "is_vars",
        "VARS Status: Confirming Strength breakout",
        "VARs confirming strength",
        "VARS (data-derived)",
        "VARS live",
    ),
    (
        "rs_line_new_highs",
        "RS Line New Highs Status: Confirming Strength",
        "RS line making new highs",
        "RS line (data-derived)",
        "RS line live",
    ),
    (
        "rvol",
        "swing RVOL 3x stop",
        f"RVOL >= {RULES.min_rvol}x",
        "RVOL (data-derived)",
        None,
    ),
    (
        "adr_pct",
        "ADR 6% swing stop",
        f"ADR% >= {RULES.min_adr_pct:.0f}%",
        "ADR% (data-derived)",
        None,
    ),
    (
        "atr_from_50ma",
        "3x ATR from 50-MA swing stop",
        f"ATR < {RULES.max_atr_from_50ma}x from 50-MA",
        "ATR from 50-MA (data-derived)",
        None,
    ),
    (
        "relative_strength",
        "relative strength outperform swing stop",
        "Relative Strength vs market/sector",
        "Relative strength vs SPY (data-derived)",
        None,
    ),
    (
        "trade_against_declining_200ma",
        "not against declining 200-ma swing stop",
        "200-MA trend (no trade against declining)",
        "200-MA context (data-derived)",
        None,
    ),
    (
        "vcp",
        "stock breakout VCP stop",
        "VCP / Tight Price Action",
        "VCP contraction (data-derived)",
        None,
    ),
    (
        "avg_dollar_volume_m",
        "high liquidity 20M avg volume swing stop",
        LIQUIDITY_CRITERION,
        "Avg $ volume (data-derived)",
        "Screener liquidity",
    ),
)


def _make_ohlcv(
    n_or_closes: int | list[float],
    *,
    close_start: float = 100.0,
    close_end: float = 150.0,
    daily_range_pct: float = 0.06,
    base_volume: float = 1_000_000.0,
    last_volume_mult: float = 2.0,
) -> pd.DataFrame:
    if isinstance(n_or_closes, list):
        closes = np.asarray(n_or_closes, dtype=float)
        dates = pd.date_range("2020-01-01", periods=len(closes), freq="B")
        highs = closes * (1 + daily_range_pct / 2)
        lows = closes * (1 - daily_range_pct / 2)
        volumes = [base_volume] * len(closes)
        return pd.DataFrame(
            {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
            index=dates,
        )
    n = n_or_closes
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    closes = np.linspace(close_start, close_end, n)
    highs = closes * (1 + daily_range_pct / 2)
    lows = closes * (1 - daily_range_pct / 2)
    volumes = np.full(n, base_volume, dtype=float)
    volumes[-1] = base_volume * last_volume_mult
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )


def _assert_auto_criteria_scored_pass_fail(scores: dict[str, str]) -> None:
    for key in AUTO_CRITERIA:
        assert key in scores
        status = scores[key]
        assert status in {"PASS", "FAIL"}, f"{key} was {status!r}, expected PASS or FAIL"
        assert not status.startswith("REVIEW"), f"{key} should not be REVIEW"


def test_compute_signals_pass_case_synthetic():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120, last_volume_mult=1.0)
    signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    scores = score_entry(signals, RULES)
    _assert_auto_criteria_scored_pass_fail(scores)
    assert signals.rvol is not None and signals.rvol >= RULES.min_rvol
    assert signals.adr_pct is not None and signals.adr_pct >= RULES.min_adr_pct
    assert signals.relative_strength is True
    assert signals.is_vars is True
    assert signals.vars_reading is not None
    assert signals.rs_line_new_highs is True
    assert signals.trade_against_declining_200ma is False


def test_compute_signals_fail_case_synthetic():
    symbol_df = _make_ohlcv(260, close_start=200, close_end=80, daily_range_pct=0.01, last_volume_mult=0.5)
    bench_df = _make_ohlcv(260, close_start=100, close_end=150, last_volume_mult=1.0)
    signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    scores = score_entry(signals, RULES)
    _assert_auto_criteria_scored_pass_fail(scores)
    assert signals.rvol is not None and signals.rvol < RULES.min_rvol
    assert signals.relative_strength is False
    assert signals.is_vars is False


def test_compute_vars_confirming_on_uptrend_synthetic():
    sym = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench = _make_ohlcv(260, close_start=100, close_end=120, last_volume_mult=1.0)
    reading, trend, confirming = compute_vars_from_ohlcv(sym, bench, rs_period=63, atr_period=14)
    assert reading is not None
    assert reading > 0
    assert trend in {"rising", "flat", "falling"}
    assert confirming is True


def test_compute_rs_line_new_highs_uptrend_synthetic():
    sym = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench = _make_ohlcv(260, close_start=100, close_end=120)
    series = compute_rs_line_ratio_series(sym, bench)
    assert series is not None and len(series) > 10
    confirming, leading, status = compute_rs_line_new_highs_from_ohlcv(sym, bench)
    assert confirming is True
    assert status == "Confirming Strength"


def test_format_rs_line_live_analysis_structure():
    sym = _make_ohlcv(260, close_start=100, close_end=180)
    bench = _make_ohlcv(260, close_start=100, close_end=120)
    signals = compute_signals_from_ohlcv(sym, bench)
    report = format_rs_line_live_analysis("NVDA", signals)
    assert "Ticker: NVDA" in report
    assert "RS Line New Highs Status:" in report
    assert "Strength Confirmation Verdict" in report
    assert "Bottom Line" in report


def test_format_vars_live_analysis_structure():
    sym = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench = _make_ohlcv(260, close_start=100, close_end=120)
    signals = compute_signals_from_ohlcv(sym, bench)
    report = format_vars_live_analysis("NVDA", signals, traditional_rs=signals.relative_strength)
    assert "Ticker: NVDA" in report
    assert "VARS Status:" in report
    assert "Strength Confirmation Verdict" in report
    assert "Bottom Line" in report
    assert "yfinance" in report


def test_merge_entry_signals_text_overrides_auto():
    text = EntrySignals(rvol=2.5)
    auto = EntrySignals(rvol=0.8, adr_pct=7.0, relative_strength=True)
    merged = merge_entry_signals(text, auto)
    assert merged.rvol == 2.5
    assert merged.adr_pct == 7.0
    assert merged.relative_strength is True


def _coach_auto_criteria_lines(report: str) -> dict[str, str]:
    lines = {}
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped.startswith("["):
            continue
        for key in AUTO_CRITERIA:
            if key in stripped:
                lines[key] = stripped.split("]", 1)[0].lstrip("[")
    return lines


def test_auto_field_extractors_cover_all_auto_computed_fields():
    assert set(AUTO_FIELD_TEXT_EXTRACTORS) == set(AUTO_COMPUTED_FIELDS)


@pytest.mark.parametrize(
    "field,desc,criterion_label,metric_marker,note_skip",
    AUTO_FIELD_ISOLATION_CASES,
)
def test_auto_field_text_override_isolation(
    field: str,
    desc: str,
    criterion_label: str,
    metric_marker: str,
    note_skip: str | None,
):
    market_signals = _synthetic_market_signals()
    text_signals = parse_description_to_signals(desc)
    assert getattr(text_signals, field) is not None, f"parse did not set {field}"
    derived = data_derived_criterion_values(market_signals, text_signals, RULES)
    assert criterion_label not in derived
    assert metric_marker not in " ".join(auto_signal_summary(market_signals, text_signals))
    if note_skip:
        assert note_skip not in " ".join(website_process_notes(market_signals, text_signals))
    raw = analyze_trade_description(desc, market_signals=market_signals)
    crit_line = next(
        line
        for line in raw.splitlines()
        if criterion_label in line and line.strip().startswith("[")
    )
    assert "[PASS]" in crit_line or "[FAIL]" in crit_line
    assert "(data-derived)" not in crit_line
    assert metric_marker not in raw
    if note_skip:
        assert note_skip not in raw


def test_data_derived_criterion_values_excludes_text_overrides():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120, last_volume_mult=1.0)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    text_signals = parse_description_to_signals(
        "AAPL swing trade RVOL 3x ADR 6%, break-even stop"
    )
    derived = data_derived_criterion_values(market_signals, text_signals, RULES)
    rvol_key = f"RVOL >= {RULES.min_rvol}x"
    adr_key = f"ADR% >= {RULES.min_adr_pct:.0f}%"
    assert rvol_key not in derived
    assert adr_key not in derived
    assert len(derived) == len(AUTO_COMPUTED_FIELDS) - 2


def test_text_override_suppresses_data_derived_on_rvol_line():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=1.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120, last_volume_mult=1.0)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    desc = "AAPL swing trade RVOL 3x, break-even stop and scale out plan"
    result = analyze_trade_description(desc, market_signals=market_signals)
    rvol_key = f"RVOL >= {RULES.min_rvol}x"
    rvol_line = next(line for line in result.splitlines() if rvol_key in line)
    assert "[PASS]" in rvol_line
    assert "(data-derived)" not in rvol_line
    assert "RVOL (data-derived)" not in result
    market_rvol = f"{market_signals.rvol:.2f}x"
    assert market_rvol not in rvol_line
    assert "ADR% (data-derived)" in result


def test_compute_vcp_contraction_detects_tightening_ranges():
    n = 90
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    closes = np.linspace(100, 130, n)
    range_pcts = np.linspace(0.10, 0.02, n)
    highs = closes * (1 + range_pcts / 2)
    lows = closes * (1 - range_pcts / 2)
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000_000.0] * n,
        },
        index=dates,
    )
    assert compute_vcp_contraction(df) is True


def test_compute_avg_dollar_volume_m_from_ohlcv():
    df = _make_ohlcv(40, close_start=50, close_end=60, base_volume=2_000_000.0)
    liq = compute_avg_dollar_volume_m(df, lookback=20)
    assert liq is not None
    assert liq > 50.0


def test_auto_criterion_values_maps_all_auto_fields():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120, last_volume_mult=1.0)
    signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    values = auto_criterion_values(signals, RULES)
    assert len(values) == len(AUTO_COMPUTED_FIELDS)
    assert values[f"RVOL >= {RULES.min_rvol}x"].endswith("x")
    assert values[f"ADR% >= {RULES.min_adr_pct:.0f}%"].endswith("%")
    assert "outperforming" in values["Relative Strength vs market/sector"]


def test_analyze_trade_description_with_market_signals():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    desc = "AAPL stock swing trade, set break-even stop and scale out plan"
    result = analyze_trade_description(desc, market_signals=market_signals)
    assert "Market context: auto-computed" in result
    assert "data-derived" in result
    scored = _coach_auto_criteria_lines(result)
    for key in AUTO_CRITERIA:
        assert key in scored
        assert scored[key] in {"PASS", "FAIL"}
    assert f"RVOL >= {RULES.min_rvol}x — " in result
    assert "outperforming" in result or "lagging" in result
    assert "VARS (data-derived)" in result
    assert "RS line (data-derived)" in result
    assert "VCP contraction (data-derived)" in result
    assert "Avg $ volume (data-derived)" in result
    assert "watchlist → focus" in result or "Process gate" in result


def test_text_override_suppresses_vcp_data_derived():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    desc = "AAPL stock no vcp, loose base, break-even stop"
    result = analyze_trade_description(desc, market_signals=market_signals)
    vcp_line = next(line for line in result.splitlines() if "VCP / Tight" in line)
    assert "(data-derived)" not in vcp_line
    assert "[FAIL]" in vcp_line
    assert "Process gate: no VCP contraction" not in result


def test_stock_breakout_vcp_text_override_hermetic_isolation():
    """Plan step-2 style: 'stock breakout VCP' must not leak OHLCV VCP into notes/lines."""
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    text_signals = parse_description_to_signals("stock breakout VCP")
    assert text_signals.vcp is True
    assert "VCP / Tight Price Action" not in data_derived_criterion_values(
        market_signals, text_signals, RULES
    )
    assert not any(
        "VCP contraction" in n
        for n in auto_signal_summary(market_signals, text_signals)
    )
    assert not any(
        "Process gate" in n or "watchlist → focus" in n
        for n in website_process_notes(market_signals, text_signals)
    )
    raw = analyze_trade_description("stock breakout VCP", market_signals=market_signals)
    vcp_line = next(line for line in raw.splitlines() if "VCP / Tight" in line)
    assert "[PASS]" in vcp_line
    assert "(data-derived)" not in vcp_line
    assert "VCP contraction (data-derived)" not in raw
    assert "Process gate" not in raw


def test_plan_validator_desc_text_override_with_market_signals():
    """Plan step-4 text: VCP + RVOL from description; OHLCV must not tag those lines."""
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=1.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    desc = "AAPL stock VCP breakout RVOL 2x"
    text_signals = parse_description_to_signals(desc)
    assert text_signals.vcp is True
    assert text_signals.rvol == 2.0
    derived = data_derived_criterion_values(market_signals, text_signals, RULES)
    assert f"RVOL >= {RULES.min_rvol}x" not in derived
    assert "VCP / Tight Price Action" not in derived
    raw = analyze_trade_description(desc, market_signals=market_signals)
    rvol_line = next(line for line in raw.splitlines() if f"RVOL >= {RULES.min_rvol}x" in line)
    vcp_line = next(line for line in raw.splitlines() if "VCP / Tight" in line)
    assert "(data-derived)" not in rvol_line
    assert "(data-derived)" not in vcp_line
    assert "[PASS]" in rvol_line
    assert "[PASS]" in vcp_line


def test_text_override_vcp_still_in_auto_criteria_display():
    from coach_outcome_formatter import build_coach_outcome_display

    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    raw = analyze_trade_description(
        "AAPL stock VCP breakout, break-even stop",
        market_signals=market_signals,
    )
    display = build_coach_outcome_display(raw)
    vcp_crit = next(c for c in display.auto_criteria if "VCP" in c.label)
    assert vcp_crit.is_pass
    assert vcp_crit.detail is None or "(data-derived)" not in (vcp_crit.detail or "").lower()
    assert len(display.auto_criteria) == len(AUTO_COMPUTED_FIELDS)


def test_website_process_notes_from_market_signals():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120)
    signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    notes = website_process_notes(signals, EntrySignals())
    assert any("Screener liquidity" in n for n in notes)


def test_website_process_notes_skip_vcp_when_text_overrides():
    symbol_df = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench_df = _make_ohlcv(260, close_start=100, close_end=120)
    market_signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    text = parse_description_to_signals("AAPL VCP breakout")
    notes = website_process_notes(market_signals, text)
    assert not any("Process gate" in n or "watchlist → focus" in n for n in notes)


def test_auto_computed_fields_populated():
    symbol_df = _make_ohlcv(260)
    bench_df = _make_ohlcv(260, close_end=120)
    signals = compute_signals_from_ohlcv(symbol_df, bench_df)
    for field in AUTO_COMPUTED_FIELDS:
        val = getattr(signals, field)
        if field == "rs_line_new_highs":
            assert val is not None or signals.rs_line_status is not None, field
        else:
            assert val is not None, field


@pytest.mark.parametrize("bar_count", [7, 56, 260])
def test_auto_signals_complete_at_all_history_lengths(bar_count: int):
    """Every auto field populated and all auto criteria PASS/FAIL (never REVIEW)."""
    sym = _make_ohlcv(
        bar_count,
        close_start=100,
        close_end=140,
        last_volume_mult=2.5,
        daily_range_pct=0.06,
    )
    bench = _make_ohlcv(bar_count, close_start=100, close_end=110)
    signals = compute_signals_from_ohlcv(sym, bench)
    for field in AUTO_COMPUTED_FIELDS:
        val = getattr(signals, field)
        if field == "rs_line_new_highs":
            assert val is not None or signals.rs_line_status is not None, f"{field} at n={bar_count}"
        else:
            assert val is not None, f"{field} at n={bar_count}"
    scores = score_entry(signals, RULES)
    for key in AUTO_CRITERIA:
        assert key in scores
        status = scores[key]
        if key == "RS line making new highs" and signals.rs_line_new_highs is None:
            assert status.startswith("REVIEW")
        else:
            assert status in {"PASS", "FAIL"}, f"{key} was {status!r}"


def test_relative_strength_lookback_anchor_non_linear():
    """Non-linear path: correct anchor outperforms; off-by-one anchor says lagging."""
    from jeff_sun_trading_coach.market_context import compute_relative_strength_vs_benchmark

    sym = _make_ohlcv([200, 60, 90, 90, 90, 90, 100], base_volume=1e6)
    bench = _make_ohlcv([200, 80, 80, 80, 80, 80, 100], base_volume=1e6)
    lookback = 5
    assert compute_relative_strength_vs_benchmark(sym, bench, lookback=lookback) is True
    wrong_sym = float(sym["Close"].iloc[-1]) / float(sym["Close"].iloc[-lookback]) - 1.0
    wrong_bench = float(bench["Close"].iloc[-1]) / float(bench["Close"].iloc[-lookback]) - 1.0
    assert (wrong_sym > wrong_bench) is False


def test_compute_lod_check_acceptable_when_close_near_lod():
    df = _make_ohlcv(30, close_start=100, close_end=100, daily_range_pct=0.02)
    check = compute_lod_check_from_ohlcv(df)
    assert check is not None
    assert not check.violated
    assert check.pct_of_atr < RULES.max_lod_atr_pct


def test_compute_lod_check_violated_when_distance_exceeds_60pct_atr():
    dates = pd.date_range("2020-01-01", periods=20, freq="B")
    closes = [100.0] * 20
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [99.0] * 19 + [85.0],
            "Close": closes,
            "Volume": [1_000_000.0] * 20,
        },
        index=dates,
    )
    check = compute_lod_check_from_ohlcv(df, max_lod_atr_pct=RULES.max_lod_atr_pct)
    assert check is not None
    assert check.violated
    assert check.pct_of_atr >= RULES.max_lod_atr_pct


def test_format_lod_live_analysis_structure():
    df = _make_ohlcv(30, close_start=100, close_end=100, daily_range_pct=0.02)
    check = compute_lod_check_from_ohlcv(df)
    report = format_lod_live_analysis("NVDA", check)
    assert "**Ticker:** NVDA" in report
    assert "**LoD Check**:" in report
    assert "**Status**:" in report
    assert "**Verdict**:" in report
    assert "ATR(14):" in report


def test_compute_signals_populates_lod_atr_pct():
    sym = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench = _make_ohlcv(260, close_start=100, close_end=120)
    signals = compute_signals_from_ohlcv(sym, bench)
    assert signals.lod_atr_pct is not None
    assert signals.lod_atr_pct >= 0


def test_analyze_trade_description_includes_lod_block_with_symbol(monkeypatch):
    sym_df = _make_ohlcv(30, close_start=100, close_end=100, daily_range_pct=0.02)

    def fake_fetch(symbol: str, period: str = "1y"):
        return sym_df.copy() if symbol.upper() == "NVDA" else None

    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_ohlcv_history",
        fake_fetch,
    )
    market_signals = compute_signals_from_ohlcv(sym_df, None)
    raw = analyze_trade_description(
        "NVDA stock swing, set break-even stop",
        market_signals=market_signals,
        symbol="NVDA",
    )
    assert "LoD Check (live OHLCV):" in raw
    assert "**LoD Check**:" in raw
    assert "LoD distance (data-derived)" in raw


def test_resolve_price_for_check_prefers_parsed_entry():
    df = _make_ohlcv(10, close_start=100, close_end=110)
    price, is_proposed = resolve_price_for_check(
        "NVDA",
        description="NVDA swing, entry at 142.50, set stop",
        ohlcv_df=df,
    )
    assert price == 142.5
    assert is_proposed is True


def test_resolve_price_for_check_falls_back_to_current_close():
    df = _make_ohlcv(10, close_start=100, close_end=110)
    price, is_proposed = resolve_price_for_check(
        "NVDA",
        description="NVDA swing breakout no entry stated",
        ohlcv_df=df,
    )
    assert price == pytest.approx(110.0)
    assert is_proposed is False


def test_current_price_from_ohlcv_matches_last_close():
    df = _make_ohlcv(10, close_start=50, close_end=88.5)
    assert current_price_from_ohlcv(df) == pytest.approx(88.5)


def test_lod_text_override_suppresses_live_block(monkeypatch):
    sym_df = _make_ohlcv(30, close_start=100, close_end=100, daily_range_pct=0.02)

    def fake_fetch(symbol: str, period: str = "1y"):
        return sym_df.copy()

    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_ohlcv_history",
        fake_fetch,
    )
    market_signals = compute_signals_from_ohlcv(sym_df, None)
    raw = analyze_trade_description(
        "NVDA stock swing, LoD at 40% ATR, set break-even stop",
        market_signals=market_signals,
        symbol="NVDA",
    )
    assert "LoD Check (live OHLCV):" not in raw


def _make_intraday_session(
    *,
    session_date: str = "2024-06-03",
    or_high: float = 110.0,
    or_low: float = 100.0,
    later_close: float = 112.0,
    n_bars: int = 8,
) -> pd.DataFrame:
    """Synthetic 15m bars: first bar = opening range, later bars trend up."""
    start = pd.Timestamp(f"{session_date} 09:30")
    idx = pd.date_range(start, periods=n_bars, freq="15min")
    highs = [or_high] + [later_close * 1.01] * (n_bars - 1)
    lows = [or_low] + [later_close * 0.99] * (n_bars - 1)
    closes = [or_high - 1.0] + [later_close] * (n_bars - 1)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000_000.0] * n_bars,
        },
        index=idx,
    )


def _make_tight_daily_with_rvol(
    *,
    n: int = 60,
    last_volume_mult: float = 2.5,
    daily_range_pct: float = 0.04,
) -> pd.DataFrame:
    """Daily frame with contracting ranges (VCP proxy) and elevated last-bar volume."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    closes = np.linspace(100.0, 130.0, n)
    range_pcts = np.linspace(0.12, 0.03, n)
    highs = closes * (1 + range_pcts / 2)
    lows = closes * (1 - range_pcts / 2)
    volumes = np.full(n, 1_000_000.0, dtype=float)
    volumes[-1] = 1_000_000.0 * last_volume_mult
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=dates,
    )


def test_compute_orma_reclaim_above_and_below():
    intra = _make_intraday_session(or_high=110.0, or_low=100.0)
    orma = 105.0
    level, reclaimed, label = compute_orma_reclaim(intra, 106.0)
    assert level == pytest.approx(orma)
    assert reclaimed is True
    assert "15" in label
    _, not_reclaimed, _ = compute_orma_reclaim(intra, 104.0)
    assert not_reclaimed is False


def test_compute_launch_orma_check_strong_launch_with_orma_reclaim():
    daily = _make_tight_daily_with_rvol(last_volume_mult=2.5)
    intra = _make_intraday_session(or_high=110.0, or_low=100.0, later_close=112.0)
    check = compute_launch_orma_check(
        "NVDA",
        daily_df=daily,
        intraday_df=intra,
        explicit_price=106.0,
    )
    assert check is not None
    assert check.tight_label in {"Yes", "Partial"}
    assert check.rvol is not None and check.rvol >= 1.5
    assert check.launch_status in {"Strong Launch Signal", "Moderate"}
    assert check.orma_reclaimed is True
    assert check.launched_pass is True
    assert check.entry_recommendation == "Favorable"


def test_format_launch_orma_live_analysis_structure():
    daily = _make_tight_daily_with_rvol()
    intra = _make_intraday_session(later_close=112.0)
    check = compute_launch_orma_check(
        "NVDA",
        daily_df=daily,
        intraday_df=intra,
        explicit_price=106.0,
    )
    report = format_launch_orma_live_analysis("NVDA", check)
    assert "**Ticker:** NVDA" in report
    assert "**1. Launch Signal Check (Tight + RVOL)**" in report
    assert "**2. ORMA Reclaim Check**" in report
    assert "**Combined Entry Quality**" in report
    assert "**Notes** (if any):" in report
    assert "Recommendation for Entry:" in report


def test_enrich_market_signals_launch_orma_sets_fields(monkeypatch):
    daily = _make_tight_daily_with_rvol()
    intra = _make_intraday_session(later_close=112.0)

    def fake_daily(symbol: str, period: str = "3mo"):
        return daily.copy()

    def fake_intra(symbol: str, period: str = "5d", interval: str = "15m"):
        return intra.copy()

    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_ohlcv_history",
        fake_daily,
    )
    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_intraday_ohlcv",
        fake_intra,
    )
    enriched = enrich_market_signals_launch_orma("NVDA", None)
    assert enriched is not None
    assert enriched.launched is not None
    assert enriched.orma_reclaim is not None


def test_analyze_trade_description_includes_launch_orma_block(monkeypatch):
    daily = _make_tight_daily_with_rvol()
    intra = _make_intraday_session(later_close=112.0)

    def fake_daily(symbol: str, period: str = "1y"):
        return daily.copy()

    def fake_intra(symbol: str, period: str = "5d", interval: str = "15m"):
        return intra.copy()

    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_ohlcv_history",
        fake_daily,
    )
    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_intraday_ohlcv",
        fake_intra,
    )
    market_signals = compute_signals_from_ohlcv(daily, None)
    raw = analyze_trade_description(
        "NVDA stock swing, set break-even stop",
        market_signals=market_signals,
        symbol="NVDA",
    )
    assert "Launch & ORMA Analysis (live OHLCV):" in raw
    assert "**1. Launch Signal Check (Tight + RVOL)**" in raw
    assert "**2. ORMA Reclaim Check**" in raw


def test_launch_orma_text_override_suppresses_live_block(monkeypatch):
    daily = _make_tight_daily_with_rvol()
    intra = _make_intraday_session()

    def fake_daily(symbol: str, period: str = "1y"):
        return daily.copy()

    def fake_intra(symbol: str, period: str = "5d", interval: str = "15m"):
        return intra.copy()

    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_ohlcv_history",
        fake_daily,
    )
    monkeypatch.setattr(
        "jeff_sun_trading_coach.market_context.fetch_intraday_ohlcv",
        fake_intra,
    )
    market_signals = compute_signals_from_ohlcv(daily, None)
    raw = analyze_trade_description(
        "NVDA stock swing, ORMA reclaim, launched, set break-even stop",
        market_signals=market_signals,
        symbol="NVDA",
    )
    assert "Launch & ORMA Analysis (live OHLCV):" not in raw