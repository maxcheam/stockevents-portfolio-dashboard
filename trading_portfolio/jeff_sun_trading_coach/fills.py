"""Load and pair broker fills into closed positions."""

from __future__ import annotations

import re
from datetime import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .entry_framework import (
    EntrySignals,
    score_entry,
    score_entry_adapted,
    score_entry_fill_only,
)
from .horizon import TradeHorizon
from .models import ClosedPosition, RuleChecks
from .rules import JeffSunRules, load_rules
from .stop_proxy import simulate_three_stop

MARKET_OPEN = time(9, 30)
MARKET_OPEN_PLUS_30 = time(10, 0)


def load_trades_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "Symbol" in df.columns and "Quantity" in df.columns:
        return load_stock_events_csv(df)
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    return df


def load_stock_events_csv(source: str | Path | pd.DataFrame) -> pd.DataFrame:
    """Convert StockEvents export to internal fill format for validation."""
    raw = pd.read_csv(source) if not isinstance(source, pd.DataFrame) else source.copy()
    rows: list[dict[str, Any]] = []
    for _, r in raw.iterrows():
        qty = float(r["Quantity"])
        price = float(r["Price"])
        comm = float(r.get("Fees Amount", 0) or 0)
        side = "Buy" if qty > 0 else "Sell"
        rows.append(
            {
                "trade_date": pd.to_datetime(r["Date"]),
                "symbol": str(r["Symbol"]),
                "symbol_raw": str(r["Symbol"]),
                "underlying": str(r["Symbol"]),
                "expiration": None,
                "option_type": None,
                "side": side,
                "quantity": abs(qty),
                "price": price,
                "net_amount": -qty * price,
                "commission": comm,
                "strategy": "Stock",
                "spread_net_amount": 0.0,
                "spread_position_id": None,
            }
        )
    return pd.DataFrame(rows)


def cashflow(row: pd.Series) -> float:
    comm = float(row.get("commission", 0) or 0)
    return float(row["net_amount"]) - comm


def _trade_time(ts: pd.Timestamp) -> time:
    if pd.isna(ts):
        return time(16, 0)
    return ts.time()


def opened_within_30min_of_open(ts: pd.Timestamp) -> bool:
    t = _trade_time(ts)
    return MARKET_OPEN <= t < MARKET_OPEN_PLUS_30


def infer_spread_width(row_group: pd.DataFrame) -> float:
    strikes = sorted(row_group["strike"].dropna().unique()) if "strike" in row_group.columns else []
    if len(strikes) >= 2:
        return abs(float(strikes[-1]) - float(strikes[0])) * 100
    underlying = str(row_group["underlying"].iloc[0]) if "underlying" in row_group.columns else ""
    if underlying in ("SPXW", "SPX"):
        return 10000.0
    if underlying == "XSP":
        return 1000.0
    return 1000.0


def check_hard_rules_from_fills(
    opened_after_open_30min: bool,
    rules: JeffSunRules,
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    passed: list[str] = []
    if opened_after_open_30min:
        violations.append(
            f"No entry {rules.no_entry_minutes_after_open} mins after open "
            "(unless extreme RVOL) — verify exception"
        )
    else:
        passed.append("Entry timing outside first 30 minutes")
    return violations, passed


def _build_credit_spread_positions(
    df: pd.DataFrame,
    rules: JeffSunRules,
    horizon: TradeHorizon = "swing",
) -> list[ClosedPosition]:
    positions: list[ClosedPosition] = []
    spreads = df[df["strategy"] == "Credit Spread"].copy()
    if spreads.empty or "spread_position_id" not in spreads.columns:
        return positions

    for pid, g in spreads.groupby("spread_position_id"):
        if pd.isna(pid):
            continue
        g = g.sort_values("trade_date")
        sells = g[g["side"].str.lower() == "sell"]
        buys = g[g["side"].str.lower() == "buy"]
        if sells.empty or buys.empty:
            continue

        open_date = min(sells["trade_date"].min(), buys["trade_date"].min())
        close_date = g["trade_date"].max()
        open_rows = g[g["trade_date"] == open_date]

        pnl_values = g["spread_net_amount"].dropna().unique()
        pnl = float(pnl_values[0]) if len(pnl_values) else float(g.apply(cashflow, axis=1).sum())

        width = infer_spread_width(open_rows)
        net_credit = float(open_rows.apply(cashflow, axis=1).sum())
        max_loss = max(width - net_credit, 100.0) if net_credit > 0 else width
        risk_r = max_loss
        r_multiple = pnl / risk_r if risk_r else 0.0

        symbol = str(g["underlying"].iloc[0]) if "underlying" in g.columns else str(g["symbol"].iloc[0])
        hold_days = max((close_date - open_date).days, 0)
        opened_early = opened_within_30min_of_open(open_date)
        hard_violations, hard_passed = check_hard_rules_from_fills(opened_early, rules)

        positions.append(
            ClosedPosition(
                position_id=f"SPREAD-{int(pid)}",
                strategy="Credit Spread",
                symbol=symbol,
                open_date=open_date,
                close_date=close_date,
                pnl=pnl,
                risk_r=risk_r,
                r_multiple=r_multiple,
                hold_days=hold_days,
                opened_after_open_30min=opened_early,
                partial_scale_out=False,
                direction="short_vol",
                rule_checks=RuleChecks(
                    validation_tier="adapted",
                    entry_framework=score_entry_adapted("Credit Spread"),
                    hard_rule_violations=hard_violations,
                    hard_rules_passed=hard_passed,
                ),
                stop_sim=simulate_three_stop(
                    pnl, risk_r, hold_days, rules, pnl > 0, horizon=horizon
                ),
                notes=[],
            )
        )
    return positions


def _build_stock_roundtrips(
    df: pd.DataFrame,
    rules: JeffSunRules,
    entry_signals: dict[str, EntrySignals] | None = None,
    horizon: TradeHorizon = "swing",
) -> list[ClosedPosition]:
    positions: list[ClosedPosition] = []
    stocks = df[df["strategy"] == "Stock"].copy()
    if stocks.empty:
        return positions

    for symbol, g in stocks.groupby("symbol"):
        g = g.sort_values("trade_date")
        buys = g[g["side"].str.lower() == "buy"]
        sells = g[g["side"].str.lower() == "sell"]
        if buys.empty or sells.empty:
            continue

        buy_qty = float(buys["quantity"].sum())
        sell_qty = float(sells["quantity"].sum())
        if buy_qty <= 0 or sell_qty <= 0:
            continue

        buy_cost = float(buys.apply(cashflow, axis=1).sum())
        sell_proceeds = float(sells.apply(cashflow, axis=1).sum())
        pnl = sell_proceeds + buy_cost

        matched_qty = min(buy_qty, sell_qty)
        avg_buy = abs(buy_cost) / buy_qty if buy_qty else 0.0
        entry_value = avg_buy * matched_qty
        risk_r = max(entry_value * 0.07, 100.0)
        r_multiple = pnl / risk_r

        open_date = buys["trade_date"].min()
        close_date = sells["trade_date"].max()
        hold_days = max((close_date - open_date).days, 0)
        partial_scale_out = len(sells) > 1
        opened_early = opened_within_30min_of_open(open_date)
        hard_violations, hard_passed = check_hard_rules_from_fills(opened_early, rules)

        pos_id = f"STOCK-{symbol}"
        if entry_signals and pos_id in entry_signals:
            entry_fw = score_entry(entry_signals[pos_id], rules)
            entry_fw["Profit-taking scale-out (fill proxy)"] = (
                "PASS" if partial_scale_out else "REVIEW"
            )
        else:
            entry_fw = score_entry_fill_only(rules, partial_scale_out)

        notes: list[str] = []
        if partial_scale_out:
            notes.append(
                f"Profit-taking: {len(sells)} partial sells into strength "
                f"(ATR% scale-out {rules.scale_out_min_pct:.0f}-{rules.scale_out_max_pct:.0f}%)"
            )

        positions.append(
            ClosedPosition(
                position_id=pos_id,
                strategy="Stock",
                symbol=str(symbol),
                open_date=open_date,
                close_date=close_date,
                pnl=pnl,
                risk_r=risk_r,
                r_multiple=r_multiple,
                hold_days=hold_days,
                opened_after_open_30min=opened_early,
                partial_scale_out=partial_scale_out,
                direction="long",
                rule_checks=RuleChecks(
                    validation_tier="equity",
                    entry_framework=entry_fw,
                    hard_rule_violations=hard_violations,
                    hard_rules_passed=hard_passed,
                ),
                stop_sim=simulate_three_stop(
                    pnl, risk_r, hold_days, rules, pnl > 0, horizon=horizon
                ),
                notes=notes,
            )
        )
    return positions


def _pair_chronological_roundtrips(
    g: pd.DataFrame,
    rules: JeffSunRules,
    strategy: str,
    id_prefix: str,
    horizon: TradeHorizon = "swing",
) -> list[ClosedPosition]:
    positions: list[ClosedPosition] = []
    g = g.sort_values("trade_date").reset_index(drop=True)
    used: set[int] = set()

    for i in range(len(g)):
        if i in used:
            continue
        open_row = g.iloc[i]
        open_side = str(open_row["side"]).lower()

        close_idx = None
        for j in range(i + 1, len(g)):
            if j in used:
                continue
            close_side = str(g.iloc[j]["side"]).lower()
            if open_side == "buy" and close_side == "sell":
                close_idx = j
                break
            if open_side == "sell" and close_side == "buy":
                close_idx = j
                break

        if close_idx is None:
            continue

        close_row = g.iloc[close_idx]
        used.add(i)
        used.add(close_idx)

        open_cf = cashflow(open_row)
        close_cf = cashflow(close_row)
        pnl = open_cf + close_cf
        risk_r = max(abs(open_cf), 100.0)
        direction = "long" if open_side == "buy" else "short"
        r_multiple = pnl / risk_r if risk_r else 0.0
        open_date = open_row["trade_date"]
        close_date = close_row["trade_date"]
        hold_days = max((close_date - open_date).days, 0)
        opened_early = opened_within_30min_of_open(open_date)
        hard_violations, hard_passed = check_hard_rules_from_fills(opened_early, rules)
        underlying = (
            str(open_row["underlying"])
            if pd.notna(open_row.get("underlying"))
            else str(open_row["symbol"])
        )

        positions.append(
            ClosedPosition(
                position_id=f"{id_prefix}-{underlying}-{open_date.date()}",
                strategy=strategy,
                symbol=underlying,
                open_date=open_date,
                close_date=close_date,
                pnl=pnl,
                risk_r=risk_r,
                r_multiple=r_multiple,
                hold_days=hold_days,
                opened_after_open_30min=opened_early,
                partial_scale_out=False,
                direction=direction,
                rule_checks=RuleChecks(
                    validation_tier="adapted",
                    entry_framework=score_entry_adapted(strategy),
                    hard_rule_violations=hard_violations,
                    hard_rules_passed=hard_passed,
                ),
                stop_sim=simulate_three_stop(
                    pnl, risk_r, hold_days, rules, pnl > 0, horizon=horizon
                ),
                notes=[],
            )
        )
    return positions


def _build_option_roundtrips(
    df: pd.DataFrame,
    rules: JeffSunRules,
    horizon: TradeHorizon = "swing",
) -> list[ClosedPosition]:
    options = df[df["strategy"] == "Option"].copy()
    if "spread_position_id" in options.columns:
        options = options[options["spread_position_id"].isna() | (options["spread_position_id"] == 0)]

    positions: list[ClosedPosition] = []
    for _symbol, g in options.groupby("symbol"):
        positions.extend(
            _pair_chronological_roundtrips(g, rules, "Option", "OPT", horizon=horizon)
        )
    return positions


def build_closed_positions(
    df: pd.DataFrame,
    rules: JeffSunRules | None = None,
    entry_signals: dict[str, EntrySignals] | None = None,
    horizon: TradeHorizon = "swing",
) -> list[ClosedPosition]:
    rules = rules or load_rules()
    trade_df = df[df["strategy"].isin(["Credit Spread", "Option", "Stock"])].copy()
    if "strike" not in trade_df.columns:
        trade_df["strike"] = np.nan

    def get_strike(sym: Any) -> float | None:
        if pd.isna(sym):
            return None
        m = re.search(r"(\d+\.?\d*)\s*[CP]", str(sym).upper())
        return float(m.group(1)) if m else None

    trade_df["strike"] = trade_df["symbol"].apply(get_strike)

    positions: list[ClosedPosition] = []
    positions.extend(_build_credit_spread_positions(trade_df, rules, horizon=horizon))
    positions.extend(_build_stock_roundtrips(trade_df, rules, entry_signals, horizon=horizon))
    positions.extend(_build_option_roundtrips(trade_df, rules, horizon=horizon))
    positions.sort(key=lambda p: p.open_date)
    return positions