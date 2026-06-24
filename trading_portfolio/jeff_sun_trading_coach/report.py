"""Report text assembly."""

from __future__ import annotations

import pandas as pd

from .horizon import (
    TradeHorizon,
    confirmation_position_label,
    confirmation_rate_label,
    horizon_label,
)
from .models import ValidationReport
from .process import analyze_trades
from .rules import JeffSunRules, SKILL_PATH


def format_report(report: ValidationReport) -> str:
    lines: list[str] = []
    r = report.rules
    m = report.metrics

    horizon = report.horizon
    confirm_label = confirmation_rate_label(horizon)
    pos_confirm_label = confirmation_position_label(horizon)

    lines.append("=" * 72)
    lines.append("JEFF SUN TRADING COACH — HISTORICAL VALIDATION REPORT")
    lines.append("=" * 72)
    lines.append(f"Skill source: {SKILL_PATH.name}")
    lines.append(f"Core Philosophy: {r.core_philosophy}")
    lines.append(f"Trade horizon: {horizon_label(horizon)}")
    lines.append("")
    lines.append("DATA SCOPE & LIMITATIONS")
    lines.append("-" * 40)
    for lim in report.data_limitations:
        lines.append(f"  • {lim}")
    lines.append("")
    lines.append("GUIDE FRAMEWORKS APPLIED")
    lines.append("-" * 40)
    lines.append("Entry Framework (VCP, RVOL, ATR% from 50-MA):")
    for item in r.entry_framework:
        lines.append(f"  • {item}")
    lines.append("3-Stop Risk Management:")
    for item in r.three_stop_strategy:
        lines.append(f"  • {item}")
    lines.append("Profit-Taking (ATR extensions from 50-MA):")
    for item in r.profit_taking_atr:
        lines.append(f"  • {item}")
    lines.append("Execution Discipline (hard rules):")
    for item in r.hard_rules:
        lines.append(f"  • {item}")
    lines.append("")
    lines.append("RULE ADHERENCE SCORING (from fill data)")
    lines.append("-" * 40)
    lines.append(
        f"Equity positions: {m['equity_position_count']} "
        f"| Adapted (credit spread/options): {m['adapted_position_count']}"
    )
    lines.append(f"Hard-rule violations detected: {m['hard_rule_violation_count']}")
    if report.journal_mode and m["entry_framework_verifiable"] > 0:
        lines.append(
            f"Entry framework (optional journal): "
            f"{m['entry_framework_passed']}/{m['entry_framework_verifiable']} PASS "
            f"({m['entry_framework_pass_rate']:.0%})"
        )
    else:
        lines.append(
            "Entry framework (VCP/RVOL/ATR): skipped — fill data lacks chart context "
            f"(verifiable criteria: {m['entry_framework_verifiable']})"
        )
    lines.append(f"3-Stop simulations differing from actual: {m['simulation_delta_count']}")
    lines.append(
        f"t3_compliance_rate: {m['t3_compliance_rate']:.0%} ({horizon_label(horizon)})"
    )
    lines.append(f"{confirm_label}: {m['t3_compliance_rate']:.0%}")
    lines.append("")
    lines.append("QUANTITATIVE RESULTS (Think in R)")
    lines.append("-" * 40)
    lines.append(f"Closed positions analyzed: {m['position_count']}")
    lines.append(f"Win rate: {m['win_rate']:.1%} ({m['num_wins']}W / {m['num_losses']}L)")
    lines.append(f"Average win: {m['avg_win_r']:.2f}R (${m['avg_win_dollars']:.2f})")
    lines.append(f"Average loss: {m['avg_loss_r']:.2f}R (${m['avg_loss_dollars']:.2f})")
    lines.append(
        f"3-Stop simulated avg loss: {m['simulated_avg_loss_r']:.2f}R | "
        f"Actual avg loss: {m['avg_loss_r']:.2f}R | "
        f"Target: -{r.target_avg_loss_r}R"
    )
    lines.append(f"Expectancy (actual): {m['expectancy_r']:.2f}R (${m['expectancy_dollars']:.2f})")
    lines.append(f"Expectancy (3-stop simulated): {m['simulated_expectancy_r']:.2f}R")
    lines.append(
        f"Benchmark (Math of Success): {r.benchmark_win_rate:.0%} WR, "
        f"+{r.benchmark_avg_win_r}R avg win, -{r.benchmark_avg_loss_r}R avg loss "
        f"→ {r.math_of_success['benchmark_expectancy_r']:.2f}R expectancy"
    )
    lines.append(f"Profit factor: {m['profit_factor']:.2f}")
    lines.append(f"Largest win: {m['largest_win_r']:.2f}R | Largest loss: {m['largest_loss_r']:.2f}R")
    lines.append("")
    lines.append("PROCESS & DISCIPLINE SCORES")
    lines.append("-" * 40)
    for key, score in report.process_scores.items():
        lines.append(f"  {key}: {score:.1f}/10")
    lines.append(f"Overall process score: {m['overall_process_score']:.1f}/10")
    lines.append("")
    lines.append("SESSION RULE CHECKS")
    lines.append("-" * 40)
    if report.session_violations:
        for v in report.session_violations:
            lines.append(f"  ⚠ {v}")
    else:
        lines.append(
            f"  ✓ No >{r.max_new_positions_per_session} new positions per session violations"
        )
    lines.append("")
    lines.append("POSITION-LEVEL REVIEW (R-multiples + 3-Stop + Rules)")
    lines.append("-" * 40)
    for pos in report.positions:
        outcome = "WIN" if pos.pnl > 0 else "LOSS" if pos.pnl < 0 else "FLAT"
        lines.append(
            f"  [{pos.position_id}] {pos.symbol} ({pos.strategy}/{pos.direction}) "
            f"{outcome} {pos.r_multiple:+.2f}R (${pos.pnl:+.2f}) hold={pos.hold_days}d "
            f"[{pos.rule_checks.validation_tier}]"
        )
        sim = pos.stop_sim
        lines.append(
            f"    3-Stop: {sim.stop_triggered} | actual {sim.actual_r:+.2f}R → "
            f"simulated {sim.hypothetical_r:+.2f}R | "
            f"{pos_confirm_label}: {'OK' if sim.t3_compliant else 'VIOLATION'}"
        )
        if pos.opened_after_open_30min:
            lines.append(
                f"    Hard rule: opened within {r.no_entry_minutes_after_open}min of open "
                "(needs extreme RVOL exception)"
            )
        for v in pos.rule_checks.hard_rule_violations:
            lines.append(f"    ⚠ {v}")
        for k, v in pos.rule_checks.entry_framework.items():
            lines.append(f"    Entry [{v}]: {k}")
        if pos.partial_scale_out:
            lines.append("    ↳ Partial scale-out (ATR% profit-taking proxy)")
        for note in pos.notes:
            lines.append(f"    ↳ {note}")
        for note in sim.notes:
            lines.append(f"    ↳ {note}")
    lines.append("")
    lines.append("COACHING RECOMMENDATIONS")
    lines.append("-" * 40)
    for note in report.coaching_notes:
        lines.append(f"  → {note}")
    lines.append("")
    lines.append(f"Remember: {r.core_philosophy}")
    lines.append("=" * 72)
    return "\n".join(lines)


def generate_report(
    df: pd.DataFrame,
    rules: JeffSunRules | None = None,
    entry_signals: dict | None = None,
    horizon: TradeHorizon = "swing",
) -> str:
    return format_report(analyze_trades(df, rules, entry_signals, horizon=horizon))