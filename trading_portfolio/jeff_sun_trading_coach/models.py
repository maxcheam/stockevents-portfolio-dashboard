"""Shared dataclasses for Jeff Sun trading coach validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .horizon import TradeHorizon
from .rules import JeffSunRules


@dataclass
class StopSimulation:
    stop_triggered: str
    actual_r: float
    hypothetical_r: float
    t3_compliant: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class RuleChecks:
    validation_tier: str  # equity | adapted
    entry_framework: dict[str, str]
    hard_rule_violations: list[str]
    hard_rules_passed: list[str]


@dataclass
class ClosedPosition:
    position_id: str
    strategy: str
    symbol: str
    open_date: pd.Timestamp
    close_date: pd.Timestamp
    pnl: float
    risk_r: float
    r_multiple: float
    hold_days: int
    opened_after_open_30min: bool
    partial_scale_out: bool
    direction: str
    rule_checks: RuleChecks
    stop_sim: StopSimulation
    notes: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    rules: JeffSunRules
    positions: list[ClosedPosition]
    daily_new_positions: dict[str, int]
    session_violations: list[str]
    metrics: dict[str, Any]
    process_scores: dict[str, float]
    coaching_notes: list[str]
    data_limitations: list[str]
    journal_mode: bool = False
    horizon: TradeHorizon = "swing"