"""Coach / --describe path exercises SKILL.md on representative text."""

from __future__ import annotations

import numpy as np
import pandas as pd

from jeff_sun_trading_coach import analyze_trade_description, load_coaching_protocol_steps, load_rules, score_entry
from jeff_sun_trading_coach.coach import extract_skill_section
from jeff_sun_trading_coach.market_context import (
    auto_field_criterion_labels,
    compute_relative_strength_vs_benchmark,
    compute_signals_from_ohlcv,
)
from jeff_sun_trading_coach.rules import SKILL_PATH

RULES = load_rules()

AUTO_CRITERIA = tuple(auto_field_criterion_labels(RULES).values())


def _make_ohlcv(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    closes_arr = np.asarray(closes, dtype=float)
    highs = closes_arr * 1.02
    lows = closes_arr * 0.98
    vols = volumes if volumes is not None else [1_000_000.0] * len(closes)
    return pd.DataFrame(
        {"Open": closes_arr, "High": highs, "Low": lows, "Close": closes_arr, "Volume": vols},
        index=dates,
    )
DESC = (
    "HOOD VCP breakout with RVOL 2.1x, entry at 50-MA reclaim, "
    "ATR 3x from 50-MA, set break-even stop and scale out plan"
)


def test_skill_contains_core_philosophy():
    assert "Trade Tight, Think in R, Focus on Process" in SKILL_PATH.read_text(encoding="utf-8")


def test_coaching_protocol_has_nine_steps():
    assert len(load_coaching_protocol_steps()) == 9


def test_extract_skill_section_full_body():
    section = extract_skill_section("Entry Framework")
    assert "Relative Strength" in section
    assert "VCP" in section
    assert len(section) > 200


def test_describe_references_guide_elements():
    result = analyze_trade_description(DESC, RULES)
    for concept in ("Think in R", "VCP", "RVOL", "ATR", "3-STOP", "SKILL EXCERPT"):
        assert concept in result or concept.lower() in result.lower()


def test_describe_passes_atr_and_rvol_via_score_entry():
    result = analyze_trade_description(DESC, RULES)
    assert "[PASS] RVOL" in result or f"RVOL >= {RULES.min_rvol}x" in result
    assert "3.0x from 50-MA" in result or "ATR <" in result
    assert RULES.core_philosophy in result


def test_describe_swing_horizon_has_strict_t3():
    desc = (
        "NVDA swing trade VCP breakout RVOL 2x, break-even stop, "
        "scale out at 4x ATR"
    )
    result = analyze_trade_description(desc, RULES)
    assert "horizon: swing" in result
    assert "T+3 RULE" in result
    assert "By end of Day T+3 position must be working or exit" in result


def test_describe_mid_term_horizon_relaxes_t3():
    desc = (
        "AAPL mid-term position trade, hold for weeks, RVOL 1.8x, "
        "thesis intact, trail stop"
    )
    result = analyze_trade_description(desc, RULES)
    assert "horizon: mid-term" in result
    assert "Swing T+3 exit rule does not apply" in result
    assert "By end of Day T+3 position must be working or exit" not in result


def test_describe_includes_profit_taking_excerpt():
    result = analyze_trade_description(DESC, RULES)
    assert "SKILL EXCERPT — Profit-Taking:" in result
    assert "4x ATR from 50-MA" in result or "ATR extensions" in result


def test_describe_full_guide_signals():
    desc = (
        "HOOD VCP breakout VARs confirming, RS line making new highs, RVOL 2.5x, "
        "ADR 6%, LoD at 40% ATR, ORMA reclaim, pocket pivot, launched, break-even stop"
    )
    result = analyze_trade_description(desc, RULES)
    assert "[PASS] VARs confirming strength" in result
    assert f"[PASS] ADR% >= {RULES.min_adr_pct:.0f}%" in result
    assert "[PASS] ORMA reclaim at entry" in result
    assert "Pocket pivot detected" in result
    assert "ORMA reclaim entry" in result


def test_describe_long_term_horizon_relaxes_t3():
    desc = (
        "MSFT long-term investment thesis, hold for months, "
        "quarterly review, trail stop on runners"
    )
    result = analyze_trade_description(desc, RULES)
    assert "horizon: long-term" in result
    assert "T+3 swing confirmation does not apply" in result
    assert "By end of Day T+3 position must be working or exit" not in result


def test_relative_strength_non_linear_paths_not_off_by_one():
    """Hand-crafted closes where wrong lookback anchor inverts RS bool."""
    sym = _make_ohlcv([200, 60, 90, 90, 90, 90, 100])
    bench = _make_ohlcv([200, 80, 80, 80, 80, 80, 100])
    lookback = 5
    rs = compute_relative_strength_vs_benchmark(sym, bench, lookback=lookback)
    assert rs is True
    sym_close = sym["Close"]
    bench_close = bench["Close"]
    wrong_sym_ret = float(sym_close.iloc[-1]) / float(sym_close.iloc[-lookback]) - 1.0
    wrong_bench_ret = float(bench_close.iloc[-1]) / float(bench_close.iloc[-lookback]) - 1.0
    assert (wrong_sym_ret > wrong_bench_ret) is False


def test_coach_market_signals_compute_and_score_pass_fail():
    sym_closes = list(np.linspace(100, 180, 260))
    sym_vols = [1_000_000.0] * 259 + [3_000_000.0]
    sym = _make_ohlcv(sym_closes, sym_vols)
    bench = _make_ohlcv(list(np.linspace(100, 120, 260)))
    market_signals = compute_signals_from_ohlcv(sym, bench)
    scores = score_entry(market_signals, RULES)
    for key in AUTO_CRITERIA:
        assert scores[key] in {"PASS", "FAIL"}, f"{key} -> {scores[key]}"
    result = analyze_trade_description(
        "AAPL swing trade, break-even stop, scale out plan",
        RULES,
        market_signals=market_signals,
    )
    assert "Market context: auto-computed" in result
    for key in AUTO_CRITERIA:
        crit_line = next(
            (line for line in result.splitlines() if key in line and line.strip().startswith("[")),
            None,
        )
        assert crit_line is not None, f"missing scored line for {key}"
        assert "[PASS]" in crit_line or "[FAIL]" in crit_line, key