"""Process metrics, session rules, and analyze_trades orchestration."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .entry_framework import EntrySignals, count_verifiable_entry
from .fills import build_closed_positions
from .horizon import (
    TradeHorizon,
    confirmation_score_label,
    confirmation_violation_note,
    data_limitation_horizon_note,
    fill_validation_intro,
    horizon_label,
)
from .models import ClosedPosition, ValidationReport
from .rules import JeffSunRules, load_rules


def count_daily_new_positions(df: pd.DataFrame) -> dict[str, int]:
    trade_df = df[df["strategy"].isin(["Credit Spread", "Option", "Stock"])].copy()
    if trade_df.empty:
        return {}

    counts: dict[str, int] = {}
    subset = trade_df[trade_df["strategy"] == "Credit Spread"]
    for pid, g in subset.groupby("spread_position_id"):
        if pd.isna(pid):
            continue
        d = g["trade_date"].min().date().isoformat()
        counts[d] = counts.get(d, 0) + 1

    for strategy in ("Option", "Stock"):
        subset = trade_df[trade_df["strategy"] == strategy]
        for symbol, g in subset.groupby("symbol"):
            g = g.sort_values("trade_date")
            for i in range(len(g)):
                side = str(g.iloc[i]["side"]).lower()
                if side == "buy" or (
                    side == "sell"
                    and not any(str(g.iloc[k]["side"]).lower() == "sell" for k in range(i))
                ):
                    d = g.iloc[i]["trade_date"].date().isoformat()
                    counts[d] = counts.get(d, 0) + 1
                    break

    return counts


def check_session_violations(
    daily_counts: dict[str, int], rules: JeffSunRules
) -> list[str]:
    violations: list[str] = []
    for day, count in sorted(daily_counts.items()):
        if count > rules.max_new_positions_per_session:
            violations.append(
                f"{day}: {count} new positions (max {rules.max_new_positions_per_session} per session)"
            )
    return violations


def compute_metrics(
    positions: list[ClosedPosition],
    session_violations: list[str],
    rules: JeffSunRules,
    journal_mode: bool = False,
) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "position_count": 0,
        "equity_position_count": 0,
        "adapted_position_count": 0,
        "hard_rule_violation_count": 0,
        "entry_framework_passed": 0,
        "entry_framework_verifiable": 0,
        "entry_framework_pass_rate": None,
        "simulation_delta_count": 0,
        "t3_compliance_rate": 0.0,
        "win_rate": 0.0,
        "num_wins": 0,
        "num_losses": 0,
        "avg_win_r": 0.0,
        "avg_loss_r": 0.0,
        "avg_win_dollars": 0.0,
        "avg_loss_dollars": 0.0,
        "expectancy_r": 0.0,
        "expectancy_dollars": 0.0,
        "simulated_expectancy_r": 0.0,
        "simulated_avg_loss_r": 0.0,
        "profit_factor": 0.0,
        "largest_win_r": 0.0,
        "largest_loss_r": 0.0,
        "overall_process_score": 0.0,
    }
    if not positions:
        return empty

    wins = [p for p in positions if p.pnl > 0]
    losses = [p for p in positions if p.pnl < 0]
    equity = [p for p in positions if p.rule_checks.validation_tier == "equity"]
    adapted = [p for p in positions if p.rule_checks.validation_tier == "adapted"]

    hard_violations = sum(len(p.rule_checks.hard_rule_violations) for p in positions)
    hard_violations += len(session_violations)

    equity_passes = equity_checks = 0
    if journal_mode:
        for p in equity:
            p_passed, p_verifiable = count_verifiable_entry(p.rule_checks.entry_framework)
            equity_passes += p_passed
            equity_checks += p_verifiable

    t3_ok = sum(1 for p in positions if p.stop_sim.t3_compliant)
    sim_rs = [p.stop_sim.hypothetical_r for p in positions]
    sim_losses = [p.stop_sim.hypothetical_r for p in positions if p.pnl < 0]
    sim_delta = sum(
        1 for p in positions
        if abs(p.stop_sim.hypothetical_r - p.stop_sim.actual_r) > 0.001
    )

    pass_rate: float | None = None
    if journal_mode and equity_checks > 0:
        pass_rate = equity_passes / equity_checks

    return {
        "position_count": len(positions),
        "equity_position_count": len(equity),
        "adapted_position_count": len(adapted),
        "hard_rule_violation_count": hard_violations,
        "entry_framework_passed": equity_passes,
        "entry_framework_verifiable": equity_checks,
        "entry_framework_pass_rate": pass_rate,
        "simulation_delta_count": sim_delta,
        "t3_compliance_rate": t3_ok / len(positions),
        "win_rate": len(wins) / len(positions),
        "num_wins": len(wins),
        "num_losses": len(losses),
        "avg_win_r": float(np.mean([p.r_multiple for p in wins])) if wins else 0.0,
        "avg_loss_r": float(np.mean([p.r_multiple for p in losses])) if losses else 0.0,
        "avg_win_dollars": float(np.mean([p.pnl for p in wins])) if wins else 0.0,
        "avg_loss_dollars": float(np.mean([p.pnl for p in losses])) if losses else 0.0,
        "expectancy_r": float(np.mean([p.r_multiple for p in positions])),
        "expectancy_dollars": float(np.mean([p.pnl for p in positions])),
        "simulated_expectancy_r": float(np.mean(sim_rs)),
        "simulated_avg_loss_r": float(np.mean(sim_losses)) if sim_losses else 0.0,
        "profit_factor": (
            sum(p.pnl for p in wins) / abs(sum(p.pnl for p in losses))
            if losses
            else float("inf")
        ),
        "largest_win_r": max((p.r_multiple for p in positions), default=0.0),
        "largest_loss_r": min((p.r_multiple for p in positions), default=0.0),
        "overall_process_score": 0.0,
    }


def compute_process_scores(
    positions: list[ClosedPosition],
    session_violations: list[str],
    metrics: dict[str, Any],
    rules: JeffSunRules,
    horizon: TradeHorizon = "swing",
) -> dict[str, float]:
    discipline = 10.0 - min(len(session_violations) * 2.5, 5.0)
    discipline -= min(metrics["hard_rule_violation_count"] * 0.5, 4.0)
    discipline = max(discipline, 0.0)

    r_thinking = 6.0
    if metrics["simulated_avg_loss_r"] >= -rules.target_avg_loss_r:
        r_thinking += 2.0
    if metrics["avg_loss_r"] < -1.0:
        r_thinking -= 3.0
    r_thinking = min(max(r_thinking, 0.0), 10.0)

    scale_outs = sum(1 for p in positions if p.partial_scale_out)
    profit_taking = 5.0 + min(scale_outs * 2.5, 5.0)

    benchmark = rules.math_of_success["benchmark_expectancy_r"]
    edge = 5.0
    if metrics["simulated_expectancy_r"] >= benchmark:
        edge = 8.0

    t3_score = metrics["t3_compliance_rate"] * 10.0

    return {
        "Execution discipline (hard rules)": discipline,
        "Think in R (3-stop simulated)": r_thinking,
        "Profit-taking / scale-out (ATR%)": profit_taking,
        confirmation_score_label(horizon): t3_score,
        "Mathematical edge vs benchmark": edge,
    }


def generate_coaching_notes(
    positions: list[ClosedPosition],
    metrics: dict[str, Any],
    session_violations: list[str],
    rules: JeffSunRules,
    journal_mode: bool,
    horizon: TradeHorizon = "swing",
) -> list[str]:
    notes: list[str] = [fill_validation_intro(horizon)]

    if session_violations:
        notes.append(
            f"Reduce new entries: {len(session_violations)} session(s) exceeded "
            f"{rules.max_new_positions_per_session} positions."
        )

    if metrics["simulated_avg_loss_r"] < -rules.target_avg_loss_r:
        notes.append(
            f"Apply 3-Stop earlier: simulated avg loss {metrics['simulated_avg_loss_r']:.2f}R "
            f"vs -{rules.target_avg_loss_r}R target."
        )
    else:
        notes.append(
            f"3-Stop discipline: simulated avg loss {metrics['simulated_avg_loss_r']:.2f}R "
            f"within -{rules.target_avg_loss_r}R target."
        )

    t3_failures = [p for p in positions if not p.stop_sim.t3_compliant]
    if t3_failures:
        notes.append(confirmation_violation_note(horizon, len(t3_failures)))

    if not journal_mode:
        notes.append(
            "Entry Framework (VCP/RVOL/ATR) skipped on fill-only path — "
            "broker fills lack chart context per plan scope."
        )

    return notes


def analyze_trades(
    df: pd.DataFrame,
    rules: JeffSunRules | None = None,
    entry_signals: dict[str, EntrySignals] | None = None,
    horizon: TradeHorizon = "swing",
) -> ValidationReport:
    """Default fill-only analysis. Pass entry_signals only for optional journal demo."""
    rules = rules or load_rules()
    journal_mode = entry_signals is not None and len(entry_signals) > 0
    positions = build_closed_positions(df, rules, entry_signals, horizon=horizon)
    daily_counts = count_daily_new_positions(df)
    session_violations = check_session_violations(daily_counts, rules)
    metrics = compute_metrics(positions, session_violations, rules, journal_mode)
    process_scores = compute_process_scores(
        positions, session_violations, metrics, rules, horizon=horizon
    )
    metrics["overall_process_score"] = float(np.mean(list(process_scores.values())))
    coaching_notes = generate_coaching_notes(
        positions, metrics, session_violations, rules, journal_mode, horizon=horizon
    )

    data_limitations = [
        "Historical validation uses fill-level trades.csv only (plan scope).",
        "VCP, RVOL, ADR, ATR-from-50-MA require chart context — NOT scored on default path.",
        f"Trade horizon: {horizon_label(horizon)} (set via --horizon on CLI).",
        "Credit spreads validated under adapted tier (process, R-thinking, 3-stop, confirmation).",
        "3-stop simulation uses hold_days proxy from fill timestamps.",
        data_limitation_horizon_note(horizon),
    ]
    if journal_mode:
        data_limitations.append(
            f"Optional journal mode: {len(entry_signals or {})} position signal(s) supplied."
        )

    return ValidationReport(
        rules=rules,
        positions=positions,
        daily_new_positions=daily_counts,
        session_violations=session_violations,
        metrics=metrics,
        process_scores=process_scores,
        coaching_notes=coaching_notes,
        data_limitations=data_limitations,
        journal_mode=journal_mode,
        horizon=horizon,
    )