"""Apply Jeff Sun SKILL.md coaching protocol to trade descriptions."""

from __future__ import annotations

import re
from pathlib import Path

from .entry_framework import (
    EntrySignals,
    detect_hard_rule_violations,
    guide_context_notes,
    parse_description_to_signals,
    score_entry,
)
from .market_context import (
    analyze_launch_orma_for_symbol,
    analyze_lod_for_symbol,
    auto_signal_summary,
    data_derived_criterion_values,
    enrich_market_signals_launch_orma,
    entry_signals_has_auto_data,
    format_rs_line_live_analysis,
    format_vars_live_analysis,
    merge_entry_signals,
    resolve_price_for_check,
    website_process_notes,
)
from .recommendation import parse_position_context
from .horizon import detect_trade_horizon, horizon_label, t3_guidance_for_horizon
from .recommendation import (
    build_verdict_synthesis,
    compute_trade_recommendation,
    format_verdict_synthesis_lines,
)
from .rules import SKILL_PATH, JeffSunRules, load_rules

_COACHING_PROTOCOL_RE = re.compile(
    r"## Coaching Protocol\s*\n(.*?)\n---",
    re.DOTALL,
)
_SECTION_RE = re.compile(
    r"##\s+(\d+\.\s+)?(.+?)\s*\n(.*?)(?=\n---|\n##\s+\d+\.|\n##\s+[A-Z]|\Z)",
    re.DOTALL,
)


def load_skill_prompt(skill_path: Path | None = None) -> str:
    path = skill_path or SKILL_PATH
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3 :].lstrip()
    text = re.sub(
        r"\n## Machine-Readable Constants.*",
        "",
        text,
        flags=re.DOTALL,
    ).strip()
    return text


def extract_skill_section(title_fragment: str, skill_path: Path | None = None) -> str:
    text = load_skill_prompt(skill_path)
    for match in _SECTION_RE.finditer(text):
        title = match.group(2).strip()
        if title_fragment.lower() in title.lower():
            return match.group(3).strip()
    return ""


def load_coaching_protocol_steps(skill_path: Path | None = None) -> list[str]:
    path = skill_path or SKILL_PATH
    text = path.read_text(encoding="utf-8")
    match = _COACHING_PROTOCOL_RE.search(text)
    if not match:
        raise ValueError("Coaching Protocol section not found in SKILL.md")
    steps: list[str] = []
    for line in match.group(1).splitlines():
        m = re.match(r"\d+\.\s+\*\*(.+?)\*\*", line.strip())
        if m:
            steps.append(m.group(1))
    return steps


def _classify_trade(text: str) -> str:
    lower = text.lower()
    if "credit spread" in lower or "spread" in lower:
        return "credit spread"
    if "vcp" in lower or "breakout" in lower:
        return "breakout/VCP"
    if "option" in lower:
        return "option"
    if "stock" in lower:
        return "stock"
    return "unknown"


def analyze_trade_description(
    description: str,
    rules: JeffSunRules | None = None,
    skill_path: Path | None = None,
    market_signals: EntrySignals | None = None,
    *,
    symbol: str | None = None,
) -> str:
    """Run SKILL.md Coaching Protocol using shared entry_framework.score_entry."""
    path = skill_path or SKILL_PATH
    rules = rules or load_rules()
    skill_prompt = load_skill_prompt(path)
    protocol_steps = load_coaching_protocol_steps(path)
    text = description.lower()

    entry_section = extract_skill_section("Entry Framework", path)
    hard_rules_section = extract_skill_section("Execution Discipline", path)
    three_stop_section = extract_skill_section("3-Stop", path)
    profit_section = extract_skill_section("Profit-Taking", path)

    text_signals = parse_description_to_signals(description)
    if symbol:
        market_signals = enrich_market_signals_launch_orma(
            symbol,
            market_signals,
            description=description,
            min_rvol=rules.min_rvol,
        )
    signals = merge_entry_signals(text_signals, market_signals)
    entry_scores = score_entry(signals, rules)

    lines: list[str] = [
        "JEFF SUN TRADE ANALYSIS (SKILL.md Coaching Protocol)",
        f"Skill source: {path.name} ({len(skill_prompt)} chars loaded)",
        f"Core Philosophy: {rules.core_philosophy}",
        "",
        "SKILL EXCERPT — Entry Framework:",
        entry_section or "(section not found)",
        "",
        "SKILL EXCERPT — Execution Discipline:",
        hard_rules_section or "(section not found)",
        "",
        "COACHING PROTOCOL STEPS:",
    ]
    for i, step in enumerate(protocol_steps, 1):
        lines.append(f"  {i}. {step}")
    lines.append("")

    horizon = detect_trade_horizon(description)
    lines.append(
        f"1. CLASSIFY: {_classify_trade(description)} | "
        f"horizon: {horizon_label(horizon)}"
    )
    lines.append("2. ENTRY FRAMEWORK SCORE (score_entry from signals):")
    has_auto_block = entry_signals_has_auto_data(market_signals)
    if has_auto_block:
        lines.append("   Market context: auto-computed from OHLCV history (data-derived)")
        for note in auto_signal_summary(market_signals, text_signals):
            lines.append(f"   • {note}")
        for note in website_process_notes(market_signals, text_signals):
            lines.append(f"   • {note}")
    data_derived_values = (
        data_derived_criterion_values(market_signals, text_signals, rules)
        if has_auto_block
        else {}
    )
    for criterion, status in entry_scores.items():
        if criterion in data_derived_values:
            lines.append(
                f"  [{status}] {criterion} — {data_derived_values[criterion]} (data-derived)"
            )
        else:
            lines.append(f"  [{status}] {criterion}")

    context_notes = guide_context_notes(signals)
    if context_notes:
        lines.append("")
        lines.append("   Guide signals detected:")
        for note in context_notes:
            lines.append(f"   • {note}")

    if (
        symbol
        and market_signals is not None
        and text_signals.is_vars is None
        and market_signals.is_vars is not None
    ):
        lines.append("")
        lines.append("   VARS Analysis (live OHLCV):")
        vars_block = format_vars_live_analysis(
            symbol,
            market_signals,
            traditional_rs=market_signals.relative_strength,
            rvol=market_signals.rvol,
            atr_from_50ma=market_signals.atr_from_50ma,
        )
        for vars_line in vars_block.splitlines():
            lines.append(f"   {vars_line}")

    if (
        symbol
        and market_signals is not None
        and text_signals.rs_line_new_highs is None
        and (
            market_signals.rs_line_new_highs is not None
            or market_signals.rs_line_status
        )
    ):
        lines.append("")
        lines.append("   RS Line Analysis (live OHLCV):")
        rs_block = format_rs_line_live_analysis(symbol, market_signals)
        for rs_line in rs_block.splitlines():
            lines.append(f"   {rs_line}")

    current_price: float | None = None
    if symbol:
        current_price, _ = resolve_price_for_check(symbol, description=description)
    position = parse_position_context(description, current_price=current_price)

    if symbol and (
        text_signals.launched is None or text_signals.orma_reclaim is None
    ):
        launch_orma_block = analyze_launch_orma_for_symbol(
            symbol,
            description=description,
            min_rvol=rules.min_rvol,
        )
        if launch_orma_block:
            lines.append("")
            lines.append("   Launch & ORMA Analysis (live OHLCV):")
            for lo_line in launch_orma_block.splitlines():
                lines.append(f"   {lo_line}")

    if symbol and text_signals.lod_atr_pct is None:
        lod_block = analyze_lod_for_symbol(
            symbol,
            description=description,
            max_lod_atr_pct=rules.max_lod_atr_pct,
            holding_avg_cost=position.avg_cost,
            holding_shares=position.net_shares,
        )
        if lod_block:
            lines.append("")
            lines.append("   LoD Check (live OHLCV):")
            for lod_line in lod_block.splitlines():
                lines.append(f"   {lod_line}")

    lines.append("")
    lines.append("3. HARD RULES (guided by SKILL.md §5):")
    violations = detect_hard_rule_violations(description, signals, rules)

    if violations:
        for v in violations:
            lines.append(f"  ⚠ VIOLATION: {v}")
    else:
        lines.append("  ✓ No hard-rule violations detected")

    lines.append("")
    lines.append("4. DEFINE 1R (SKILL.md §2):")
    lines.append(
        f"   {three_stop_section.splitlines()[0] if three_stop_section else 'Define 1R before entry.'}"
    )

    has_stop = any(k in text for k in ("stop", "break-even", "breakeven", "trail"))
    lines.append("5. 3-STOP PLAN:")
    lines.append(
        "   Documented."
        if has_stop
        else "   MISSING — set Stop 1 (breakeven), Stop 2 (+1R), Stop 3 (trail) on Day T"
    )

    lines.extend(t3_guidance_for_horizon(horizon))

    lines.append("")
    lines.append("SKILL EXCERPT — Profit-Taking:")
    lines.append(profit_section or "(section not found)")
    lines.append("")

    has_scale = any(k in text for k in ("scale", "partial", "sell into strength"))
    lines.append("7. PROFIT-TAKING (SKILL.md §6):")
    lines.append(
        "   Scale-out planned."
        if has_scale
        else "   REVIEW — plan ATR% scale-out at 4x/6x/8x/10x+ extensions from 50-MA"
    )

    passed = sum(1 for s in entry_scores.values() if s == "PASS")
    failed = sum(1 for s in entry_scores.values() if s == "FAIL")
    process_score = min(10.0, 4.0 + passed * 1.5 - failed * 2.0 - len(violations) * 2.0)
    lines.append(f"8. PROCESS SCORE: {process_score:.1f}/10 ({passed}/{len(entry_scores)} entry criteria PASS)")

    recommendation = compute_trade_recommendation(
        description=description,
        entry_scores=entry_scores,
        violations=violations,
        signals=signals,
        rules=rules,
        current_price=current_price,
        position=position,
    )
    lines.append(recommendation.format_line())

    synthesis = build_verdict_synthesis(signals, recommendation, position=position)
    if synthesis is not None:
        lines.extend(format_verdict_synthesis_lines(synthesis))

    lines.append("9. ACTION ITEMS:")
    if failed:
        lines.append("  → Fix FAIL items before entry — hard rules are never violated.")
    if not has_stop:
        lines.append("  → Document 3-tier stops per SKILL.md §2 before entry.")
    if passed >= 5 and not violations:
        lines.append("  → Setup meets core checklist; execute with full 3-stop discipline.")

    lines.append("")
    lines.append(f"Remember: {rules.core_philosophy}")
    return "\n".join(lines)