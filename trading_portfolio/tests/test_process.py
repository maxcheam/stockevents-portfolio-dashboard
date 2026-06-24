"""Fill-only historical validation — no journal, honest limitations."""

from __future__ import annotations

from pathlib import Path

import pytest

from jeff_sun_trading_coach import analyze_trades, generate_report, load_trades_csv, simulate_three_stop
from jeff_sun_trading_coach import load_rules

TRADES_CSV = (
    Path(__file__).resolve().parent.parent.parent
    / "moomoo_trade_dashboard"
    / "output"
    / "trades.csv"
)
SCRATCH = Path(r"C:\Users\homeuser\AppData\Local\Temp\grok-goal-4420adbe2cc9\implementer")
RULES = load_rules()


@pytest.fixture(scope="module")
def trades_df():
    return load_trades_csv(TRADES_CSV)


def test_fill_only_entry_framework_verifiable_zero(trades_df):
    report = analyze_trades(trades_df)
    assert report.metrics["entry_framework_verifiable"] == 0
    assert report.metrics["entry_framework_pass_rate"] is None
    assert not report.journal_mode


def test_fill_only_report_no_journal_pass_rate(trades_df):
    text = generate_report(trades_df)
    assert "4/4 PASS" not in text
    assert "journal-verified" not in text
    assert "skipped — fill data lacks chart context" in text
    assert "Think in R" in text
    assert "3-Stop" in text


def test_simulate_three_stop_t3_differs_from_actual():
    sim = simulate_three_stop(pnl=-190, risk_r=1000, hold_days=7, rules=RULES, is_winner=False)
    assert sim.t3_compliant is False
    assert sim.hypothetical_r != sim.actual_r


def test_report_deterministic(trades_df):
    assert generate_report(trades_df) == generate_report(trades_df)


def test_report_contains_skill_source_and_t3_compliance_rate(trades_df):
    text = generate_report(trades_df)
    assert "Skill source: SKILL.md" in text
    assert "t3_compliance_rate:" in text
    assert "Trade horizon: swing" in text


def test_report_long_term_horizon_changes_compliance(trades_df):
    swing = generate_report(trades_df, horizon="swing")
    long_term = generate_report(trades_df, horizon="long_term")
    assert "Trade horizon: long-term" in long_term
    assert "Long-term confirmation" in long_term
    assert swing != long_term


def test_save_fill_only_validation_evidence(trades_df):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    report = generate_report(trades_df)
    out = SCRATCH / "jeff_sun_validation.log"
    out.write_text(report, encoding="utf-8")
    assert out.exists()
    assert "Closed positions analyzed:" in report
    assert "Expectancy (actual):" in report