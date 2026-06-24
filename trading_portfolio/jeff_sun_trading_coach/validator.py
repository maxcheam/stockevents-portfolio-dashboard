"""Thin re-export layer — historical validation entrypoints."""

from __future__ import annotations

from .coach import analyze_trade_description, extract_skill_section, load_coaching_protocol_steps, load_skill_prompt
from .entry_framework import EntrySignals, parse_description_to_signals, score_entry, score_entry_fill_only
from .fills import build_closed_positions, load_trades_csv
from .process import analyze_trades
from .report import format_report, generate_report
from .stop_proxy import simulate_three_stop

__all__ = [
    "EntrySignals",
    "analyze_trade_description",
    "analyze_trades",
    "build_closed_positions",
    "extract_skill_section",
    "format_report",
    "generate_report",
    "load_coaching_protocol_steps",
    "load_skill_prompt",
    "load_trades_csv",
    "parse_description_to_signals",
    "score_entry",
    "score_entry_fill_only",
    "simulate_three_stop",
]