"""PnL and pairing tests on real historical fills."""

from __future__ import annotations

from pathlib import Path

import pytest

from jeff_sun_trading_coach import build_closed_positions, load_trades_csv

TRADES_CSV = (
    Path(__file__).resolve().parent.parent.parent
    / "moomoo_trade_dashboard"
    / "output"
    / "trades.csv"
)


@pytest.fixture(scope="module")
def trades_df():
    assert TRADES_CSV.exists()
    return load_trades_csv(TRADES_CSV)


def test_hood_stock_pnl_commission_correct(trades_df):
    positions = build_closed_positions(trades_df)
    hood = next(p for p in positions if p.position_id == "STOCK-HOOD")
    assert hood.pnl == pytest.approx(268.91, abs=0.02)


def test_msft_option_pnl_commission_correct(trades_df):
    positions = build_closed_positions(trades_df)
    msft = next(p for p in positions if p.symbol == "MSFT" and p.strategy == "Option")
    assert msft.pnl == pytest.approx(787.98, abs=0.02)
    assert msft.direction == "long"


def test_hood_option_chronological_short_pairing(trades_df):
    positions = build_closed_positions(trades_df)
    hood_opts = [p for p in positions if p.symbol == "HOOD" and p.strategy == "Option"]
    assert len(hood_opts) == 1
    assert hood_opts[0].direction == "short"
    assert hood_opts[0].pnl == pytest.approx(-86.97, abs=0.02)


def test_unclosed_hood_option_excluded(trades_df):
    positions = build_closed_positions(trades_df)
    assert not any("260508" in p.position_id for p in positions)


def test_fill_only_equity_entry_not_applicable(trades_df):
    hood = next(p for p in build_closed_positions(trades_df) if p.position_id == "STOCK-HOOD")
    for key, status in hood.rule_checks.entry_framework.items():
        if "fill proxy" not in key.lower():
            assert status.startswith("NOT_APPLICABLE"), f"{key} should be N/A on fill-only path"