"""3-stop + T+3 simulation proxy (hold_days from fill data)."""

from __future__ import annotations

from .horizon import TradeHorizon, confirmation_days, is_t3_compliant
from .models import StopSimulation
from .rules import JeffSunRules


def simulate_three_stop(
    pnl: float,
    risk_r: float,
    hold_days: int,
    rules: JeffSunRules,
    is_winner: bool,
    horizon: TradeHorizon = "swing",
) -> StopSimulation:
    actual_r = pnl / risk_r if risk_r else 0.0
    notes: list[str] = []
    target_loss = -rules.target_avg_loss_r

    t3_compliant = is_t3_compliant(hold_days, is_winner, horizon)
    confirm_days = confirmation_days(horizon)
    if not t3_compliant and confirm_days is not None:
        if horizon == "swing":
            notes.append(
                "T+3: losing position held past critical confirmation day — should exit"
            )
        else:
            notes.append(
                f"Mid-term: losing position held past {confirm_days}-day confirmation "
                "window — thesis should be re-evaluated or exit"
            )
    elif horizon == "long_term" and not is_winner and hold_days >= 90:
        notes.append(
            "Long-term: quarterly thesis review recommended for extended loser"
        )

    if hold_days <= 1 and actual_r < 0:
        return StopSimulation(
            stop_triggered="Stop 1 (Break-Even)",
            actual_r=actual_r,
            hypothetical_r=0.0,
            t3_compliant=t3_compliant,
            notes=notes + ["Stop 1: same-day failure → exit at breakeven (0R)"],
        )

    if actual_r >= 1.0:
        hyp = max(1.0, actual_r * 0.85)
        return StopSimulation(
            stop_triggered="Stop 2 (Break-Even +1R)",
            actual_r=actual_r,
            hypothetical_r=hyp,
            t3_compliant=t3_compliant,
            notes=notes + ["Stop 2: lock +1R minimum on initial move"],
        )

    if not t3_compliant:
        hyp = target_loss
        label = "T+3 Exit" if horizon == "swing" else f"{confirm_days}-day confirmation exit"
        notes.append(
            f"{label} simulation: disciplined max loss {target_loss:.2f}R "
            f"(vs actual {actual_r:+.2f}R after extended hold)"
        )
        return StopSimulation(
            stop_triggered=f"{label} + Stop 3",
            actual_r=actual_r,
            hypothetical_r=hyp,
            t3_compliant=False,
            notes=notes,
        )

    if actual_r < 0 and hold_days == 2:
        hyp = target_loss * 0.5
        return StopSimulation(
            stop_triggered="Stop 1/2 (interim)",
            actual_r=actual_r,
            hypothetical_r=hyp,
            t3_compliant=t3_compliant,
            notes=notes + [f"Stop 1/2: early loss capped at {hyp:.2f}R"],
        )

    if is_winner and actual_r < 1.0 and hold_days >= 3:
        hyp = actual_r * 0.9
        return StopSimulation(
            stop_triggered="Stop 3 (Trail)",
            actual_r=actual_r,
            hypothetical_r=hyp,
            t3_compliant=t3_compliant,
            notes=notes + ["Stop 3: trail locks 90% of open profit"],
        )

    if actual_r < 0:
        hyp = target_loss * 0.5 if actual_r >= target_loss else target_loss
        return StopSimulation(
            stop_triggered="Stop 3 (Trail)",
            actual_r=actual_r,
            hypothetical_r=hyp,
            t3_compliant=t3_compliant,
            notes=notes,
        )

    return StopSimulation(
        stop_triggered="No stop adjustment",
        actual_r=actual_r,
        hypothetical_r=actual_r,
        t3_compliant=t3_compliant,
        notes=notes,
    )