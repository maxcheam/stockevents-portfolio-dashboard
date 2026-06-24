"""Streamlit rendering for coach outcomes (display layer only)."""

from __future__ import annotations

import streamlit as st

from coach_outcome_formatter import (
    FrameworkStatus,
    ReviewItem,
    build_coach_outcome_display,
    format_auto_criterion_display,
    format_review_item_text,
    recommendation_display_title,
)


def _strip_timeline_title(title: str) -> str:
    return title.split(":", 1)[-1].strip() if ":" in title else title


def _show_framework_status(item: FrameworkStatus) -> None:
    if item.is_pass:
        st.success(f"PASS — {item.label}")
    elif item.is_fail:
        st.error(f"FAIL — {item.label}")
    elif item.is_review:
        st.warning(
            format_review_item_text(
                ReviewItem(label=item.label, detail=item.detail, source="framework")
            )
        )
    else:
        st.info(f"{item.label}" + (f" — {item.detail}" if item.detail else ""))


def _render_recommendation_banner(view) -> None:
    if not view.recommendation_action:
        return
    title = recommendation_display_title(view.recommendation_action)
    reason = view.recommendation_reason or ""
    action = view.recommendation_action
    st.markdown(f"### Coach verdict: **{title}**")
    if action == "entry":
        st.success(reason)
    elif action == "take profit":
        st.warning(reason)
    elif action == "cut losses":
        st.error(reason)
    else:
        st.info(reason)


def render_coach_outcome(outcome: str, *, show_verdict_banner: bool = True) -> None:
    """Present coach analysis with structured, human-readable formatting."""
    display = build_coach_outcome_display(outcome)
    view = display.view

    if show_verdict_banner:
        _render_recommendation_banner(view)

    if display.non_auto_review_items:
        st.markdown("**Needs review**")
        for item in display.non_auto_review_items:
            st.warning(format_review_item_text(item))

    if view.process_score_value is not None or view.criteria:
        score_col, pass_col, fail_col, review_col = st.columns(4)
        if view.process_score_value is not None:
            score_col.metric("Process score", f"{view.process_score_value:.1f} / 10")
        else:
            score_col.metric("Process score", "—")
        pass_col.metric("Passed", display.pass_count)
        fail_col.metric("Failed", display.fail_count)
        review_col.metric("Needs review", display.review_count)

    if display.headline:
        st.markdown(display.headline)

    if display.has_auto_metrics and view.market_notes:
        st.markdown("**Market context & process screening**")
        for note in view.market_notes:
            st.markdown(f"- {note}")

    if display.has_auto_metrics and display.auto_criteria:
        st.markdown("**Auto metrics (scored)**")
        for crit in display.auto_criteria:
            line = format_auto_criterion_display(crit)
            if crit.is_pass:
                st.success(f"PASS — {line}")
            elif crit.is_fail:
                st.error(f"FAIL — {line}")
            else:
                detail = f" ({crit.detail})" if crit.detail else ""
                st.warning(f"REVIEW{detail} — {line}")

    auto_labels = {c.label for c in display.auto_criteria}
    other_criteria = (
        [c for c in view.criteria if c.label not in auto_labels]
        if auto_labels
        else list(view.criteria)
    )
    if other_criteria:
        st.markdown("**Entry framework checklist**")
        for crit in other_criteria:
            if crit.is_pass:
                st.success(f"PASS — {crit.label}")
            elif crit.is_fail:
                st.error(f"FAIL — {crit.label}")
            else:
                detail = f" ({crit.detail})" if crit.detail else ""
                st.warning(f"REVIEW{detail} — {crit.label}")

    if view.define_1r or view.three_stop or view.position_timeline_notes:
        st.markdown("**Position management framework**")
        if view.define_1r:
            st.markdown(f"- **Define 1R:** {view.define_1r}")
        if view.three_stop:
            _show_framework_status(view.three_stop)
        if view.position_timeline_title:
            st.markdown(f"**{_strip_timeline_title(view.position_timeline_title)}**")
        for note in view.position_timeline_notes:
            st.markdown(f"- {note}")

    if view.profit_taking or view.profit_taking_targets:
        st.markdown("**Profit-taking framework (ATR extensions from 50-MA)**")
        if view.profit_taking:
            _show_framework_status(view.profit_taking)
        for target in view.profit_taking_targets:
            st.markdown(f"- {target}")
        if view.profit_golden_rule:
            st.caption(view.profit_golden_rule)

    if view.violations:
        st.markdown("**Hard rule violations**")
        for violation in view.violations:
            st.error(violation)
    elif view.hard_rules_summary:
        st.success(view.hard_rules_summary)

    if view.action_items:
        st.markdown("**Recommended next steps**")
        for item in view.action_items:
            st.markdown(f"- {item}")

    with st.expander("View full coach report", expanded=False):
        st.markdown(display.markdown_summary)
        st.text_area(
            "Complete analysis (raw)",
            value=outcome,
            height=280,
            label_visibility="collapsed",
        )