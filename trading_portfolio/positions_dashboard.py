"""Pure logic for StockEvents current positions and Jeff Sun trading coach."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from jeff_sun_trading_coach import analyze_trade_description, load_rules, load_trades_csv
from jeff_sun_trading_coach.market_context import build_auto_signals_for_symbol
from jeff_sun_trading_coach.fills import load_stock_events_csv
from jeff_sun_trading_coach.rules import JeffSunRules

STRATEGY_OPTIONS: tuple[str, ...] = ("Swing", "Mid term", "Long term")
DEFAULT_STRATEGY = "Swing"

STRATEGY_KEYWORDS: dict[str, str] = {
    "Swing": "swing trade",
    "Mid term": "mid-term position hold for weeks",
    "Long term": "long-term investment thesis hold for months",
}

HORIZON_LABELS: dict[str, str] = {
    "Swing": "horizon: swing",
    "Mid term": "horizon: mid-term",
    "Long term": "horizon: long-term",
}


@dataclass(frozen=True)
class CurrentPosition:
    symbol: str
    net_shares: float
    avg_cost: float
    total_invested: float


def _positions_from_fills(fills: pd.DataFrame) -> list[CurrentPosition]:
    """Derive open stock positions (net shares > 0) from internal fill DataFrame."""
    stocks = fills[fills["strategy"] == "Stock"].copy()
    if stocks.empty:
        return []

    net_shares: dict[str, float] = {}
    buy_cost: dict[str, float] = {}
    buy_qty: dict[str, float] = {}

    for _, row in stocks.iterrows():
        sym = str(row["symbol"])
        qty = float(row["quantity"])
        if str(row["side"]).lower() == "buy":
            net_shares[sym] = net_shares.get(sym, 0.0) + qty
            buy_cost[sym] = buy_cost.get(sym, 0.0) + qty * float(row["price"])
            buy_qty[sym] = buy_qty.get(sym, 0.0) + qty
        else:
            net_shares[sym] = net_shares.get(sym, 0.0) - qty

    positions: list[CurrentPosition] = []
    for sym in sorted(net_shares):
        shares = net_shares[sym]
        if shares <= 0:
            continue
        total_buy = buy_qty.get(sym, 0.0)
        avg = buy_cost.get(sym, 0.0) / total_buy if total_buy > 0 else 0.0
        positions.append(
            CurrentPosition(
                symbol=sym,
                net_shares=shares,
                avg_cost=avg,
                total_invested=shares * avg,
            )
        )
    return positions


def derive_current_positions_from_trades(
    source: str | Path | pd.DataFrame,
) -> list[CurrentPosition]:
    """Derive open positions using the real load_trades_csv / load_stock_events_csv path."""
    if isinstance(source, pd.DataFrame):
        if "Symbol" in source.columns and "Quantity" in source.columns:
            fills = load_stock_events_csv(source)
        else:
            fills = source.copy()
    else:
        fills = load_trades_csv(source)
    return _positions_from_fills(fills)


# Backward-compatible alias used by the Streamlit dashboard.
derive_current_positions_from_stock_events = derive_current_positions_from_trades


def current_positions_to_dataframe(positions: list[CurrentPosition]) -> pd.DataFrame:
    """Convert positions to a holdings DataFrame for the Streamlit dashboard."""
    if not positions:
        return pd.DataFrame(
            columns=["Ticker", "Net Shares", "Avg Cost (approx)", "Total Invested (approx)"]
        )
    return pd.DataFrame(
        [
            {
                "Ticker": p.symbol,
                "Net Shares": p.net_shares,
                "Avg Cost (approx)": p.avg_cost,
                "Total Invested (approx)": p.total_invested,
            }
            for p in positions
        ]
    )


def current_positions_from_holdings_df(holdings_df: pd.DataFrame) -> list[CurrentPosition]:
    """Build coach-ready positions from the dashboard holdings table (CSV or Moomoo)."""
    positions: list[CurrentPosition] = []
    for _, row in holdings_df.iterrows():
        shares = float(row["Net Shares"])
        if shares <= 0:
            continue
        cost = row.get("Avg Cost (approx)")
        if pd.isna(cost) or cost is None:
            cost = row.get("Moomoo Cost Price", 0.0)
        cost = float(cost or 0.0)
        positions.append(
            CurrentPosition(
                symbol=str(row["Ticker"]),
                net_shares=shares,
                avg_cost=cost,
                total_invested=shares * cost,
            )
        )
    return sorted(positions, key=lambda p: p.symbol)


def resolve_strategy(strategy: str | None) -> str:
    """Return a valid strategy label; default to swing trade strategy."""
    if strategy in STRATEGY_OPTIONS:
        return strategy
    return DEFAULT_STRATEGY


def build_coach_description(
    position: CurrentPosition,
    strategy: str | None = None,
    *,
    unrealized_pnl: float | None = None,
) -> str:
    """Build free-text description for analyze_trade_description with strategy keyword."""
    strat = resolve_strategy(strategy)
    keyword = STRATEGY_KEYWORDS[strat]
    parts = [
        f"{position.symbol} stock {keyword}, "
        f"current holding {position.net_shares:.0f} shares at avg cost "
        f"${position.avg_cost:.2f}",
    ]
    if unrealized_pnl is not None:
        if unrealized_pnl < 0:
            parts.append(f"unrealized loss ${abs(unrealized_pnl):,.0f}")
        elif unrealized_pnl > 0:
            parts.append(f"unrealized gain ${unrealized_pnl:,.0f}")
        else:
            parts.append("unrealized P&L $0")
    parts.append("set break-even stop and scale out plan")
    return ", ".join(parts)


def run_coach_for_position(
    position: CurrentPosition,
    strategy: str | None = None,
    rules: JeffSunRules | None = None,
    *,
    use_market_context: bool = True,
    unrealized_pnl: float | None = None,
) -> str:
    """Invoke the real Jeff Sun trading coach skill for one open position."""
    description = build_coach_description(position, strategy, unrealized_pnl=unrealized_pnl)
    market_signals = (
        build_auto_signals_for_symbol(position.symbol) if use_market_context else None
    )
    return analyze_trade_description(
        description,
        rules=rules or load_rules(),
        market_signals=market_signals,
        symbol=position.symbol,
    )


def run_coach_for_positions(
    positions: list[CurrentPosition],
    strategies: dict[str, str] | None = None,
    rules: JeffSunRules | None = None,
    *,
    unrealized_pnl_by_symbol: dict[str, float] | None = None,
) -> dict[str, str]:
    """Run trading coach on each position; strategies default to swing."""
    strategies = strategies or {}
    rules = rules or load_rules()
    pnl_map = unrealized_pnl_by_symbol or {}
    return {
        pos.symbol: run_coach_for_position(
            pos,
            resolve_strategy(strategies.get(pos.symbol)),
            rules=rules,
            unrealized_pnl=pnl_map.get(pos.symbol),
        )
        for pos in positions
    }