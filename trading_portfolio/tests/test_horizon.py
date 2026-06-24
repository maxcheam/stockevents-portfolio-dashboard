"""Trade horizon detection and T+3 compliance by horizon."""

from __future__ import annotations

from jeff_sun_trading_coach import (
    detect_trade_horizon,
    is_t3_compliant,
    load_rules,
    parse_horizon_arg,
    simulate_three_stop,
)

RULES = load_rules()


def test_detect_horizon_defaults_swing():
    assert detect_trade_horizon("HOOD VCP breakout RVOL 2x") == "swing"


def test_detect_horizon_mid_term():
    assert detect_trade_horizon("mid-term position hold for weeks") == "mid_term"


def test_detect_horizon_long_term():
    assert detect_trade_horizon("long-term buy and hold for months") == "long_term"


def test_t3_compliant_swing_loser_past_3_days():
    assert is_t3_compliant(hold_days=7, is_winner=False, horizon="swing") is False


def test_t3_compliant_mid_term_loser_within_21_days():
    assert is_t3_compliant(hold_days=7, is_winner=False, horizon="mid_term") is True


def test_t3_compliant_long_term_loser_extended_hold():
    assert is_t3_compliant(hold_days=120, is_winner=False, horizon="long_term") is True


def test_simulate_three_stop_mid_term_7d_loser_compliant():
    sim = simulate_three_stop(
        pnl=-190, risk_r=1000, hold_days=7, rules=RULES, is_winner=False, horizon="mid_term"
    )
    assert sim.t3_compliant is True


def test_parse_horizon_arg_cli_values():
    assert parse_horizon_arg("mid-term") == "mid_term"
    assert parse_horizon_arg("long-term") == "long_term"


def test_simulate_three_stop_swing_7d_loser_not_compliant():
    sim = simulate_three_stop(
        pnl=-190, risk_r=1000, hold_days=7, rules=RULES, is_winner=False, horizon="swing"
    )
    assert sim.t3_compliant is False