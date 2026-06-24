"""Pure trade recommendation: entry, hold, take profit, or cut losses."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entry_framework import EntrySignals, detect_hard_rule_violations
from .rules import JeffSunRules

RECOMMENDATION_LINE_PREFIX = "TRADE RECOMMENDATION:"
VERDICT_SYNTHESIS_HEADER = "VERDICT SYNTHESIS (Relative Strength First):"
_UNREALIZED_LOSS_RE = re.compile(
    r"unrealized loss \$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_UNREALIZED_GAIN_RE = re.compile(
    r"unrealized gain \$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_UNREALIZED_PNL_RE = re.compile(
    r"unrealized p&l \$?(-?[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_SHARES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*shares", re.IGNORECASE)
_AVG_COST_RE = re.compile(
    r"avg\s*cost\s*\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TradeRecommendation:
    action: str  # entry | hold | take profit | cut losses
    headline: str
    reason: str

    def format_line(self) -> str:
        return f"{RECOMMENDATION_LINE_PREFIX} {self.action.upper()} — {self.reason}"


@dataclass(frozen=True)
class RelativeStrengthAssessment:
    """RS-first context from RS line + VARS signals (stock-ticker-analyst pattern)."""

    tier: str  # strong | partial | weak | mixed | unknown
    observations: tuple[str, ...]


@dataclass(frozen=True)
class VerdictSynthesis:
    observations: tuple[str, ...]
    bottom_line: str


@dataclass(frozen=True)
class PositionContext:
    """Open holding context for verdict and P&L-aware recommendations."""

    is_holding: bool
    net_shares: float | None = None
    avg_cost: float | None = None
    current_price: float | None = None

    @property
    def unrealized_pnl(self) -> float | None:
        if (
            not self.is_holding
            or self.net_shares is None
            or self.avg_cost is None
            or self.current_price is None
        ):
            return None
        return self.net_shares * (self.current_price - self.avg_cost)

    @property
    def unrealized_pnl_pct(self) -> float | None:
        if (
            self.avg_cost is None
            or self.current_price is None
            or self.avg_cost <= 0
        ):
            return None
        return (self.current_price / self.avg_cost - 1.0) * 100.0


def _is_existing_holding(description: str) -> bool:
    lower = description.lower()
    return "current holding" in lower or "holding" in lower and "shares" in lower


def parse_unrealized_pnl(description: str) -> float | None:
    """Parse unrealized P&L from coach description text (loss/gain/p&l phrases)."""
    lower = description.lower()
    loss_m = _UNREALIZED_LOSS_RE.search(lower)
    if loss_m:
        return -float(loss_m.group(1).replace(",", ""))
    gain_m = _UNREALIZED_GAIN_RE.search(lower)
    if gain_m:
        return float(gain_m.group(1).replace(",", ""))
    pnl_m = _UNREALIZED_PNL_RE.search(lower)
    if pnl_m:
        return float(pnl_m.group(1).replace(",", ""))
    return None


def parse_position_context(
    description: str,
    *,
    current_price: float | None = None,
) -> PositionContext:
    """Parse shares/avg cost from description; derive P&L vs current price when possible."""
    is_holding = _is_existing_holding(description)
    lower = description.lower()
    shares_m = _SHARES_RE.search(lower)
    net_shares = float(shares_m.group(1)) if shares_m else None
    avg_m = _AVG_COST_RE.search(lower)
    avg_cost = float(avg_m.group(1).replace(",", "")) if avg_m else None
    return PositionContext(
        is_holding=is_holding,
        net_shares=net_shares,
        avg_cost=avg_cost,
        current_price=current_price,
    )


def resolve_unrealized_pnl(
    description: str,
    *,
    position: PositionContext | None = None,
) -> float | None:
    """Text P&L first; else compute from shares × (current price − avg cost)."""
    explicit = parse_unrealized_pnl(description)
    if explicit is not None:
        return explicit
    if position is not None and position.unrealized_pnl is not None:
        return position.unrealized_pnl
    return None


def position_context_observations(position: PositionContext) -> tuple[str, ...]:
    """Verdict synthesis bullets for open holdings."""
    if not position.is_holding:
        return ()
    obs: list[str] = []
    if position.net_shares is not None and position.avg_cost is not None:
        obs.append(
            f"Open position: {position.net_shares:.0f} shares at avg cost "
            f"${position.avg_cost:.2f}."
        )
    elif position.net_shares is not None:
        obs.append(f"Open position: {position.net_shares:.0f} shares.")
    if position.current_price is not None:
        obs.append(f"Current price ${position.current_price:.2f}.")
    pnl_pct = position.unrealized_pnl_pct
    if pnl_pct is not None:
        if pnl_pct > 0:
            obs.append(
                f"Cost basis gain {pnl_pct:+.1f}% — scale-out into strength per plan."
            )
        elif pnl_pct < -2:
            obs.append(
                f"Underwater vs avg cost ({pnl_pct:.1f}%) — honor stops; do not add size."
            )
        else:
            obs.append(
                f"Near breakeven vs avg cost ({pnl_pct:+.1f}%) — manage with break-even stop."
            )
    pnl = position.unrealized_pnl
    if pnl is not None:
        obs.append(f"Unrealized P&L ${pnl:,.0f} (shares × current vs avg cost).")
    return tuple(obs)


def assess_relative_strength(signals: EntrySignals) -> RelativeStrengthAssessment:
    """Summarize RS line + VARS for recommendation weighting (Relative Strength First)."""
    rs_ok = signals.rs_line_new_highs is True
    vars_ok = signals.is_vars is True
    rs_fail = signals.rs_line_new_highs is False
    vars_fail = signals.is_vars is False
    leading = signals.rs_line_leading_price is True
    observations: list[str] = []

    if rs_ok:
        lead = " and leading price" if leading else ""
        observations.append(f"RS line making new highs{lead} — leadership confirmation.")
    elif signals.rs_line_status == "Approaching or Mixed":
        observations.append("RS line approaching recent highs — not yet a clean new-high print.")
    elif rs_fail:
        observations.append("RS line not making new highs — relative strength filter not passed.")

    if vars_ok:
        trend = signals.vars_trend or "rising"
        observations.append(f"VARS confirming strength ({trend}) — volatility-adjusted RS supports the setup.")
    elif vars_fail:
        observations.append("VARS not confirming — wait for positive, rising histogram.")

    if rs_ok and vars_ok:
        tier = "strong"
    elif rs_fail or vars_fail:
        tier = "weak"
    elif rs_ok or vars_ok:
        tier = "partial"
    elif signals.rs_line_status == "Approaching or Mixed" or signals.rs_line_new_highs is None:
        tier = "mixed"
    else:
        tier = "unknown"

    if not observations:
        observations.append("RS line / VARS not stated — apply Relative Strength First before sizing.")

    return RelativeStrengthAssessment(tier=tier, observations=tuple(observations))


def build_verdict_synthesis(
    signals: EntrySignals,
    recommendation: TradeRecommendation,
    *,
    rs_assessment: RelativeStrengthAssessment | None = None,
    position: PositionContext | None = None,
) -> VerdictSynthesis | None:
    """Key observations + bottom line (stock-ticker-analyst Overall Synthesis pattern)."""
    rs = rs_assessment or assess_relative_strength(signals)
    pos_obs = position_context_observations(position) if position else ()
    if not rs.observations and rs.tier == "unknown" and not pos_obs:
        return None

    observations = list(pos_obs) + list(rs.observations)
    action = recommendation.action
    if action == "entry" and rs.tier == "strong":
        bottom = (
            "RS line + VARS both confirm — high-conviction swing entry candidate "
            "with full 3-stop discipline."
        )
    elif action == "entry":
        bottom = (
            "Entry criteria met — execute smaller until RS/VARS fully align "
            "or confirmation prints."
        )
    elif action == "take profit":
        bottom = (
            "Scale out into strength per ATR extensions; "
            "do not give back extended gains on weak RS rollover."
        )
    elif action == "cut losses":
        bottom = (
            "Honor stops and reduce — relative strength or structure no longer "
            "supports holding losers."
        )
    elif rs.tier == "strong" and action == "hold":
        bottom = (
            "RS leadership intact — hold with active trails; "
            "add only on fresh confirmation, not hope."
        )
    elif rs.tier == "weak":
        bottom = (
            "Relative strength not confirming — stand aside for new entries "
            "or tighten risk on open positions."
        )
    else:
        bottom = (
            "Mixed RS/VARS — stay process-driven: stops first, "
            "reassess when RS line prints new highs."
        )

    if position and position.is_holding and position.unrealized_pnl_pct is not None:
        pct = position.unrealized_pnl_pct
        if pct < -3 and action in {"hold", "cut losses"}:
            bottom = (
                f"Underwater holding ({pct:.1f}% vs avg cost) — {bottom}"
            )
        elif pct > 5 and action == "take profit":
            bottom = (
                f"Profitable vs avg cost ({pct:+.1f}%) — {bottom}"
            )
        elif position.avg_cost and position.current_price:
            bottom = (
                f"Holding {position.net_shares or 0:.0f} sh @ ${position.avg_cost:.2f} "
                f"vs ${position.current_price:.2f} now — {bottom}"
            )

    return VerdictSynthesis(observations=tuple(observations), bottom_line=bottom)


def format_verdict_synthesis_lines(synthesis: VerdictSynthesis) -> list[str]:
    """Coach-ready indented lines after TRADE RECOMMENDATION."""
    lines = [
        f"   {VERDICT_SYNTHESIS_HEADER}",
        "   Key Observations",
    ]
    for obs in synthesis.observations:
        lines.append(f"   • {obs}")
    lines.append("   Bottom Line")
    lines.append(f"   {synthesis.bottom_line}")
    return lines


def _rs_context_clause(rs: RelativeStrengthAssessment) -> str:
    if rs.tier == "strong":
        return "RS line new highs + VARS confirming (Relative Strength First)."
    if rs.tier == "partial":
        return "partial RS/VARS confirmation — prioritize leading RS line setups."
    if rs.tier == "weak":
        return "RS/VARS not confirming — Relative Strength First filter failed."
    if rs.tier == "mixed":
        return "RS line approaching highs — await confirming new-high print."
    return ""


def _append_rs_context(reason: str, rs: RelativeStrengthAssessment) -> str:
    clause = _rs_context_clause(rs)
    if not clause or clause.lower() in reason.lower():
        return reason
    return f"{reason} {clause}"


def _cut_losses(reason: str) -> TradeRecommendation:
    return TradeRecommendation(
        "cut losses",
        "Cut losses — exit or reduce",
        f"Cut losses — {reason}",
    )


def _apply_losing_position_override(
    rec: TradeRecommendation,
    *,
    is_holding: bool,
    unrealized_pnl: float | None,
    violations: list[str],
    against_trend: bool,
    failed: int,
) -> TradeRecommendation:
    """Never recommend take profit on an underwater holding; escalate weak losers to cut."""
    if not is_holding or unrealized_pnl is None or unrealized_pnl >= 0:
        return rec

    if rec.action == "take profit":
        detail = rec.reason
        for prefix in ("Take profit — ", "take profit — "):
            if detail.startswith(prefix):
                detail = detail[len(prefix) :]
        return _cut_losses(
            f"position is underwater (${unrealized_pnl:,.0f} unrealized); "
            f"do not scale out — exit or reduce per 3-stop discipline. {detail}"
        )

    if rec.action == "hold" and (violations or against_trend or failed >= 4):
        return _cut_losses(
            f"position is underwater (${unrealized_pnl:,.0f} unrealized) with a weak setup; "
            "honor stops and exit rather than hope-holding."
        )

    return rec


def _apply_rs_strength_adjustment(
    rec: TradeRecommendation,
    *,
    rs: RelativeStrengthAssessment,
    is_holding: bool,
    passed: int,
    failed: int,
    entry_extended: bool,
    too_extended_entry: bool,
    rules: JeffSunRules,
    violations: list[str],
    against_trend: bool,
) -> TradeRecommendation:
    """RS-first weighting: boost conviction when RS+VARS strong; gate weak RS entries."""
    reason = _append_rs_context(rec.reason, rs)
    hard_rule_blocked = bool(violations) or against_trend

    if rs.tier == "weak" and not is_holding and rec.action == "entry":
        return TradeRecommendation(
            "hold",
            "Wait — RS not confirming",
            _append_rs_context(
                "Not suitable for entry — RS line / VARS lack confirmation; "
                "Relative Strength First before setup.",
                rs,
            ),
        )

    if (
        not hard_rule_blocked
        and rs.tier == "strong"
        and not is_holding
        and rec.action == "hold"
        and "insufficient confirmation" in rec.reason.lower()
        and passed >= 3
        and failed < 5
        and not too_extended_entry
        and not entry_extended
    ):
        return TradeRecommendation(
            "entry",
            "Conditional entry — RS leadership",
            _append_rs_context(
                f"Suitable for entry — RS line + VARS confirm strength ({passed} criteria pass); "
                "size for confirmation with 3-stop plan.",
                rs,
            ),
        )

    if (
        not hard_rule_blocked
        and rs.tier == "strong"
        and not is_holding
        and rec.action == "hold"
        and "conditional" not in rec.reason.lower()
        and passed >= 4
        and failed <= 3
        and not entry_extended
    ):
        return TradeRecommendation(
            "entry",
            "Suitable for entry — RS confirmed",
            _append_rs_context(
                f"Suitable for entry — {passed} criteria pass with RS line + VARS confirming; "
                "execute with full 3-stop discipline.",
                rs,
            ),
        )

    if rs.tier == "weak" and is_holding and rec.action == "hold" and failed >= 3:
        return TradeRecommendation(
            "hold",
            "Hold — manage risk tightly",
            _append_rs_context(
                f"Hold — weak RS/VARS ({passed} pass / {failed} fail); "
                "tighten stops — do not add size.",
                rs,
            ),
        )

    return TradeRecommendation(rec.action, rec.headline, reason)


def compute_trade_recommendation(
    *,
    description: str,
    entry_scores: dict[str, str],
    violations: list[str],
    signals: EntrySignals,
    rules: JeffSunRules,
    current_price: float | None = None,
    position: PositionContext | None = None,
) -> TradeRecommendation:
    """Resolve entry / hold / take profit / cut losses from coach signals and P&L context."""
    detected = detect_hard_rule_violations(description, signals, rules)
    effective_violations = list(dict.fromkeys([*violations, *detected]))

    passed = sum(1 for s in entry_scores.values() if s == "PASS")
    failed = sum(1 for s in entry_scores.values() if s == "FAIL")
    pos = position or parse_position_context(description, current_price=current_price)
    is_holding = pos.is_holding
    unrealized_pnl = resolve_unrealized_pnl(description, position=pos)
    atr_ext = signals.atr_from_50ma
    take_profit_6x = atr_ext is not None and atr_ext >= 6.0
    take_profit_4x = atr_ext is not None and atr_ext >= 4.0
    too_extended_entry = (
        atr_ext is not None and atr_ext >= rules.max_atr_from_50ma and not is_holding
    )
    against_trend = signals.trade_against_declining_200ma is True
    entry_extended = atr_ext is not None and atr_ext >= rules.max_atr_from_50ma
    rs = assess_relative_strength(signals)

    if effective_violations or against_trend:
        if is_holding:
            if take_profit_4x or take_profit_6x:
                rec = TradeRecommendation(
                    "take profit",
                    "Take profit — reduce risk",
                    (
                        "Take profit — hard-rule concern while price is extended; "
                        "scale out into strength and tighten stops."
                    ),
                )
            else:
                rec = TradeRecommendation(
                    "hold",
                    "Hold with discipline — do not add",
                    (
                        "Hold — hard-rule flags present; honor stops and avoid new size "
                        "until structure improves."
                    ),
                )
        else:
            rec = TradeRecommendation(
                "hold",
                "Not suitable for entry",
                (
                    "Not suitable for entry — hard-rule violations or declining 200-MA context; "
                    "wait for a cleaner setup."
                ),
            )
    elif is_holding and take_profit_6x:
        rec = TradeRecommendation(
            "take profit",
            "Take profit — extended runner",
            (
                f"Take profit — price is {atr_ext:.1f}x ATR from 50-MA (6x+ zone); "
                "scale out per Jeff Sun profit-taking table."
            ),
        )
    elif is_holding and take_profit_4x:
        rec = TradeRecommendation(
            "take profit",
            "Take profit — scale-out zone",
            (
                f"Take profit — price is {atr_ext:.1f}x ATR from 50-MA (4x+ zone); "
                "sell 20–30% into strength."
            ),
        )
    elif too_extended_entry:
        rec = TradeRecommendation(
            "hold",
            "Not suitable for entry — too extended",
            (
                f"Not suitable for entry — price at or beyond "
                f"{rules.max_atr_from_50ma}x ATR from 50-MA; wait for pullback or base."
            ),
        )
    else:
        rs_boost = rs.tier == "strong"
        strong_entry = passed >= 5 and failed <= 2
        strong_entry_rs = passed >= 4 and failed <= 2 and rs_boost
        if (strong_entry or strong_entry_rs) and not entry_extended:
            if is_holding:
                rec = TradeRecommendation(
                    "hold",
                    "Hold — thesis intact",
                    (
                        f"Hold — {passed} entry criteria pass; trail stops and let the "
                        "position work."
                    ),
                )
            else:
                rec = TradeRecommendation(
                    "entry",
                    "Suitable for entry",
                    (
                        f"Suitable for entry — {passed} entry criteria pass with room to run; "
                        "execute with full 3-stop discipline."
                    ),
                )
        elif is_holding:
            if failed >= 4:
                rec = TradeRecommendation(
                    "hold",
                    "Hold — manage risk tightly",
                    (
                        f"Hold — only {passed} criteria pass; keep stops active and avoid "
                        "adding size."
                    ),
                )
            else:
                rec = TradeRecommendation(
                    "hold",
                    "Hold — monitor confirmation",
                    (
                        f"Hold — mixed setup ({passed} pass / {failed} fail); follow 3-stop plan "
                        "and reassess at T+3."
                    ),
                )
        elif passed >= 4 and failed < 4 and not entry_extended and not rs.tier == "weak":
            rec = TradeRecommendation(
                "entry",
                "Conditional entry",
                (
                    f"Suitable for entry — {passed} criteria pass but not a full checklist; "
                    "size smaller until confirmation."
                ),
            )
        else:
            rec = TradeRecommendation(
                "hold",
                "Wait — setup not ready",
                (
                    f"Hold — insufficient confirmation ({passed} pass / {failed} fail); "
                    "stand aside or keep on watchlist."
                ),
            )

    rec = _apply_rs_strength_adjustment(
        rec,
        rs=rs,
        is_holding=is_holding,
        passed=passed,
        failed=failed,
        entry_extended=entry_extended,
        too_extended_entry=too_extended_entry,
        rules=rules,
        violations=effective_violations,
        against_trend=against_trend,
    )

    return _apply_losing_position_override(
        rec,
        is_holding=is_holding,
        unrealized_pnl=unrealized_pnl,
        violations=effective_violations,
        against_trend=against_trend,
        failed=failed,
    )