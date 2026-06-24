#!/usr/bin/env python3
"""CLI entrypoint: validate historical trades against Jeff Sun trading coach rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jeff_sun_trading_coach import (
    EntrySignals,
    analyze_trade_description,
    build_auto_signals_for_symbol,
    generate_report,
    load_rules,
    load_trades_csv,
    parse_horizon_arg,
)

DEFAULT_DATA = (
    Path(__file__).resolve().parent.parent
    / "moomoo_trade_dashboard"
    / "output"
    / "trades.csv"
)


def _load_journal_signals(path: Path) -> dict[str, EntrySignals]:
    """Optional demo: load position signals from JSON (not used by default)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    signals: dict[str, EntrySignals] = {}
    for row in data:
        pid = row["position_id"]
        signals[pid] = EntrySignals(
            vcp=row.get("vcp"),
            rvol=row.get("rvol"),
            atr_from_50ma=row.get("atr_from_50ma"),
            relative_strength=row.get("relative_strength"),
        )
    return signals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Jeff Sun Trading Coach — historical trade validation"
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Path to trades CSV (moomoo or StockEvents format)",
    )
    parser.add_argument(
        "--stock-events",
        type=Path,
        default=None,
        help="Path to StockEvents transactions CSV (equity history)",
    )
    parser.add_argument(
        "--describe",
        type=str,
        default=None,
        help="Analyze a free-text trade description instead of CSV",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Ticker for OHLCV market context when using --describe",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Optional JSON file with EntrySignals per position_id (demo only)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write report text",
    )
    parser.add_argument(
        "--horizon",
        type=str,
        default=None,
        choices=["swing", "mid-term", "long-term"],
        help="Trade horizon for fill validation (swing, mid-term, long-term). "
        "Defaults to swing for CSV; inferred from --describe text when omitted.",
    )
    args = parser.parse_args(argv)

    rules = load_rules()
    print(f"Loaded Jeff Sun rules — {rules.core_philosophy}", file=sys.stderr)

    if args.describe:
        market_signals = (
            build_auto_signals_for_symbol(args.symbol.upper())
            if args.symbol
            else None
        )
        report = analyze_trade_description(
            args.describe,
            rules,
            market_signals=market_signals,
            symbol=args.symbol.upper() if args.symbol else None,
        )
    else:
        data_path = args.stock_events or args.data or DEFAULT_DATA
        if not data_path.exists():
            print(f"Error: data file not found: {data_path}", file=sys.stderr)
            return 1
        df = load_trades_csv(data_path)
        if args.stock_events:
            print(f"Loaded StockEvents equity history: {data_path.name}", file=sys.stderr)
        entry_signals = _load_journal_signals(args.journal) if args.journal else None
        if args.horizon:
            horizon = parse_horizon_arg(args.horizon)
        else:
            horizon = "swing"
        print(f"Validation horizon: {horizon}", file=sys.stderr)
        report = generate_report(df, rules, entry_signals, horizon=horizon)

    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())