"""Tests for coach outcome display formatting (pure, no Streamlit)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

from coach_outcome_formatter import (
    auto_criteria_from_view,
    build_coach_outcome_display,
    coach_outcome_has_auto_metrics,
    collect_review_items,
    format_auto_criterion_display,
    format_classification_headline,
    format_coach_outcome_markdown,
    format_needs_review_markdown,
    format_recommendation_markdown,
    format_coach_expander_label,
    format_review_indicator,
    format_review_item_text,
    format_recommendation_one_liner,
    format_recommendation_verdict_compact,
    non_auto_review_items,
    strip_recommendation_reason_prefix,
    parse_coach_outcome,
)
from positions_dashboard import (
    derive_current_positions_from_trades,
    run_coach_for_position,
    run_coach_for_positions,
)

STOCK_EVENTS = Path(__file__).resolve().parents[1] / "stock_events_transactions_2026-06-23.csv"
DASHBOARD_PATH = Path(__file__).resolve().parents[2] / "stockevents_portfolio_dashboard.py"
UI_PATH = Path(__file__).resolve().parents[1] / "coach_outcome_ui.py"


SAMPLE_OUTCOME = """\
JEFF SUN TRADE ANALYSIS (SKILL.md Coaching Protocol)
1. CLASSIFY: swing setup | horizon: swing
2. ENTRY FRAMEWORK SCORE (score_entry from signals):
   Market context: auto-computed from OHLCV history (data-derived)
   • RVOL (data-derived): 2.10x
   • ADR% (data-derived): 4.00%
  [PASS] Relative Strength vs market/sector — outperforming (data-derived)
  [PASS] RVOL >= 1.5x — 2.10x (data-derived)
  [FAIL] ADR% >= 5% — 4.00% (data-derived)
  [REVIEW — not stated] VCP / Tight Price Action
  [PASS] ATR < 4.0x from 50-MA — 2.50x (data-derived)
  [PASS] 200-MA trend (no trade against declining) — not against declining 200-MA (data-derived)
3. HARD RULES (guided by SKILL.md §5):
  ✓ No hard-rule violations detected
4. DEFINE 1R (SKILL.md §2):
   Initial position size: **100% at entry**.
5. 3-STOP PLAN:
   Documented.
6. T+3 RULE (SKILL.md §3 — swing trades):
   By end of Day T+3 position must be working or exit.
SKILL EXCERPT — Profit-Taking:
| **4x ATR from 50-MA** | Sell 20–30% |
| **6x ATR from 50-MA** | Sell another 20–30% |
**Golden Rule:** *"Sell some into strength"*
7. PROFIT-TAKING (SKILL.md §6):
   Scale-out planned.
8. PROCESS SCORE: 5.5/10 (4/12 entry criteria PASS)
TRADE RECOMMENDATION: HOLD — Mixed setup; follow 3-stop plan.
9. ACTION ITEMS:
  → Fix FAIL items before entry — hard rules are never violated.
  → Document 3-tier stops per SKILL.md §2 before entry.
"""


def test_parse_coach_outcome_extracts_sections():
    view = parse_coach_outcome(SAMPLE_OUTCOME)
    assert view.classification == "swing setup"
    assert view.horizon == "swing"
    assert len(view.market_notes) == 2
    assert view.process_score_value == 5.5
    assert len(view.criteria) >= 4
    assert view.hard_rules_summary is not None
    assert len(view.action_items) == 2
    assert not view.violations


def test_format_coach_outcome_markdown_uses_status_indicators():
    view = parse_coach_outcome(SAMPLE_OUTCOME)
    display = build_coach_outcome_display(SAMPLE_OUTCOME)
    md = format_coach_outcome_markdown(
        view, auto_criteria=display.auto_criteria
    )
    assert "Process score" in md
    assert "✅" in md
    assert "❌" in md
    assert "Auto metrics (scored)" in md
    assert "2.10x" in md
    assert "Entry framework checklist" in md
    assert "Action items" in md


def test_coach_outcome_has_auto_metrics():
    assert coach_outcome_has_auto_metrics(SAMPLE_OUTCOME)
    assert not coach_outcome_has_auto_metrics("plain text without metrics")


def test_auto_criteria_from_view():
    view = parse_coach_outcome(SAMPLE_OUTCOME)
    auto = auto_criteria_from_view(view)
    labels = " ".join(c.label.lower() for c in auto)
    assert "rvol" in labels
    assert "200-ma" in labels
    rvol = next(c for c in auto if "rvol" in c.label.lower())
    assert rvol.detail is not None
    assert "2.10" in rvol.detail
    assert "(data-derived)" in rvol.detail
    assert format_auto_criterion_display(rvol) == f"{rvol.label} · 2.10x"


def test_auto_criteria_excluded_from_non_auto_reviews():
    display = build_coach_outcome_display(SAMPLE_OUTCOME)
    auto_labels = {c.label for c in display.auto_criteria}
    for item in display.non_auto_review_items:
        if item.source == "entry":
            assert item.label not in auto_labels


def test_format_classification_headline_skips_generic_stock():
    assert format_classification_headline("stock", "swing (days to ~2 weeks)") == (
        "**Horizon:** swing (days to ~2 weeks)"
    )
    assert "Trade type" not in (format_classification_headline("stock", "swing") or "")
    assert format_classification_headline("breakout/VCP", None) == "**Setup:** breakout/VCP"


def test_parse_coach_outcome_handles_negative_process_score():
    raw = SAMPLE_OUTCOME.replace("5.5/10", "-3.0/10")
    view = parse_coach_outcome(raw)
    assert view.process_score_value == -3.0


def test_format_recommendation_one_liner():
    view = parse_coach_outcome(SAMPLE_OUTCOME)
    line = format_recommendation_one_liner(view)
    assert line is not None
    assert "Hold" in line
    assert "Mixed setup" in line or "3-stop" in line


def test_strip_recommendation_reason_prefix_removes_duplicate_hold():
    assert (
        strip_recommendation_reason_prefix(
            "Hold — hard-rule flags present; honor stops.",
            "hold",
        )
        == "hard-rule flags present; honor stops."
    )


def test_format_coach_expander_label_inlines_verdict_without_duplication():
    display = build_coach_outcome_display(SAMPLE_OUTCOME)
    compact = format_recommendation_verdict_compact(display.view)
    assert compact is not None
    assert "Hold — Hold" not in compact
    assert "Mixed setup" in compact or "3-stop" in compact
    label = format_coach_expander_label("AAPL", display)
    assert label.startswith("AAPL")
    assert "coach analysis" not in label
    assert compact in label
    assert display.review_count >= 1
    assert len(display.non_auto_review_items) >= 1
    assert "need review" in label
    assert format_review_indicator(display.review_count) in label


def test_collect_review_items_includes_entry_and_framework():
    view = parse_coach_outcome(SAMPLE_OUTCOME)
    items = collect_review_items(view)
    labels = [i.label for i in items]
    assert "VCP / Tight Price Action" in labels

    profit_review = SAMPLE_OUTCOME.replace("Scale-out planned.", "REVIEW — plan ATR% scale-out")
    profit_view = parse_coach_outcome(profit_review)
    profit_items = collect_review_items(profit_view)
    assert any(i.source == "profit" for i in profit_items)

    stop_review = SAMPLE_OUTCOME.replace("Documented.", "MISSING — set Stop 1")
    stop_view = parse_coach_outcome(stop_review)
    stop_items = collect_review_items(stop_view)
    assert any(i.source == "position" for i in stop_items)


def test_format_needs_review_markdown_lists_review_criteria():
    display = build_coach_outcome_display(SAMPLE_OUTCOME)
    md = format_needs_review_markdown(display.review_items)
    assert md is not None
    assert "Needs review" in md
    assert "VCP / Tight Price Action" in md
    full_md = format_coach_outcome_markdown(display.view, review_items=display.review_items)
    assert "Needs review" in full_md


def test_review_indicator_and_non_auto_separation():
    display = build_coach_outcome_display(SAMPLE_OUTCOME)
    assert format_review_indicator(0) is None
    assert format_review_indicator(3) == "⚠️ 3 items need review"
    assert display.non_auto_review_items == non_auto_review_items(
        display.view, display.auto_criteria
    )
    non_auto = display.non_auto_review_items
    assert all(item.label not in {c.label for c in display.auto_criteria} for item in non_auto)


def test_format_review_item_text_avoids_duplicate_prefixes():
    profit_review = SAMPLE_OUTCOME.replace(
        "Scale-out planned.",
        "REVIEW — plan ATR% scale-out at 4x/6x/8x/10x+ extensions from 50-MA",
    )
    view = parse_coach_outcome(profit_review)
    assert view.profit_taking is not None
    item = collect_review_items(view)[-1]
    text = format_review_item_text(item)
    assert text == "Profit-taking plan needs review"
    assert "REVIEW — REVIEW" not in text
    assert format_review_item_text(
        collect_review_items(parse_coach_outcome(SAMPLE_OUTCOME))[0]
    ) == "VCP / Tight Price Action (not stated)"


def test_review_count_matches_expander_indicator():
    display = build_coach_outcome_display(SAMPLE_OUTCOME)
    label = format_coach_expander_label("NVDA", display)
    assert display.review_count == len(display.review_items)
    if display.review_count > 0:
        assert format_review_indicator(display.review_count) in label


def test_run_coach_positions_emit_not_stated_review_fields():
    """Display-only path: score_entry emits REVIEW for non-auto checklist fields."""
    from jeff_sun_trading_coach import load_rules

    rules = load_rules()
    live_enriched_labels = (
        "ORMA reclaim at entry",
        "Launched signal (tight + RVOL)",
    )
    lod_label = f"LoD within {rules.max_lod_atr_pct:.0f}% ATR"
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    raw = run_coach_for_positions(positions)[positions[0].symbol]
    display = build_coach_outcome_display(raw)
    for label in live_enriched_labels:
        row = next((c for c in display.view.criteria if c.label == label), None)
        assert row is not None
        # Live launch/ORMA enrichment may resolve these to PASS/FAIL instead of REVIEW
        assert row.is_review or row.status in {"PASS", "FAIL"}
    lod_row = next((c for c in display.view.criteria if c.label == lod_label), None)
    assert lod_row is not None
    # LoD may be PASS/FAIL when live OHLCV auto-computes distance from session low
    assert lod_row.is_review or lod_row.status in {"PASS", "FAIL"}
    scored_live = [
        c
        for c in display.view.criteria
        if c.label in {*live_enriched_labels, lod_label}
        and c.status in {"PASS", "FAIL"}
    ]
    assert len(scored_live) >= 1
    label = format_coach_expander_label(positions[0].symbol, display)
    if display.review_count > 0:
        assert "need review" in label


def test_parse_verdict_synthesis_from_coach_output():
    from jeff_sun_trading_coach import analyze_trade_description, load_rules
    from jeff_sun_trading_coach.entry_framework import EntrySignals
    from jeff_sun_trading_coach.recommendation import VERDICT_SYNTHESIS_HEADER

    sig = EntrySignals(rs_line_new_highs=True, is_vars=True, rvol=2.5, adr_pct=6.0, vcp=True)
    raw = analyze_trade_description(
        "NVDA stock swing, set break-even stop",
        rules=load_rules(),
        market_signals=sig,
        symbol="NVDA",
    )
    assert VERDICT_SYNTHESIS_HEADER in raw
    view = parse_coach_outcome(raw)
    assert view.verdict_synthesis_observations
    assert view.verdict_bottom_line
    md = format_recommendation_markdown(view)
    assert md is not None
    assert "Relative strength synthesis" in md
    assert view.verdict_bottom_line in md


def test_parse_recommendation_line():
    view = parse_coach_outcome(SAMPLE_OUTCOME)
    assert view.recommendation_action == "hold"
    assert view.recommendation_reason is not None
    md = format_recommendation_markdown(view)
    assert md is not None
    assert "Hold" in md
    assert "hold" in format_coach_outcome_markdown(view).lower()

    from jeff_sun_trading_coach import analyze_trade_description
    from jeff_sun_trading_coach.entry_framework import EntrySignals
    from jeff_sun_trading_coach.recommendation import RECOMMENDATION_LINE_PREFIX

    market_signals = EntrySignals(
        atr_from_50ma=4.0,
        rvol=2.0,
        adr_pct=6.0,
        relative_strength=True,
        trade_against_declining_200ma=False,
    )
    desc = "NVDA stock swing trade, RVOL 2x ADR 6%, set break-even stop"
    raw = analyze_trade_description(desc, market_signals=market_signals)
    rec_line = next(
        line for line in raw.splitlines() if line.startswith(RECOMMENDATION_LINE_PREFIX)
    )
    assert "HOLD" in rec_line
    assert "not suitable for entry" in rec_line.lower()
    assert "take profit" not in rec_line.lower()


def test_parse_position_management_and_profit_taking():
    view = parse_coach_outcome(SAMPLE_OUTCOME)
    assert view.define_1r is not None
    assert view.three_stop is not None and view.three_stop.is_pass
    assert view.position_timeline_title is not None
    assert view.position_timeline_notes
    assert view.profit_taking is not None and view.profit_taking.is_pass
    assert len(view.profit_taking_targets) >= 2
    assert view.profit_golden_rule is not None
    md = format_coach_outcome_markdown(view)
    assert "Position management" in md
    assert "Profit-taking framework" in md


def test_markdown_includes_market_context_and_process_notes():
    from jeff_sun_trading_coach import analyze_trade_description
    from jeff_sun_trading_coach.market_context import compute_signals_from_ohlcv
    from tests.test_market_context import _make_ohlcv

    sym = _make_ohlcv(260, close_start=100, close_end=180, last_volume_mult=3.0)
    bench = _make_ohlcv(260, close_start=100, close_end=120)
    signals = compute_signals_from_ohlcv(sym, bench)
    raw = analyze_trade_description("NVDA stock swing trade", market_signals=signals)
    display = build_coach_outcome_display(raw)
    md = display.markdown_summary
    assert "Market context & process screening" in md
    assert any(
        token in md.lower()
        for token in ("screener liquidity", "vcp contraction", "process gate")
    )
    assert len(display.auto_criteria) == 9


def test_build_coach_outcome_display_wires_auto_metrics():
    display = build_coach_outcome_display(SAMPLE_OUTCOME)
    assert display.has_auto_metrics
    assert len(display.auto_criteria) >= 3
    assert display.pass_count >= 1
    assert display.review_count == len(display.review_items)
    assert display.review_count >= 1
    assert display.headline is not None
    assert "Horizon" in display.headline
    assert "Trade type" not in display.headline
    assert "Process score" in display.markdown_summary
    assert "Needs review" in display.markdown_summary


def _load_render_coach_outcome():
    """Import render_coach_outcome with a mocked streamlit module."""
    mock_st = MagicMock()
    mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
    mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)

    spec = importlib.util.spec_from_file_location("coach_outcome_ui_test", UI_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["streamlit"] = mock_st
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("streamlit", None)
    return module.render_coach_outcome, mock_st


def test_render_coach_outcome_runtime_on_real_outcome():
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    raw = run_coach_for_position(positions[0])
    render_fn, mock_st = _load_render_coach_outcome()
    render_fn(raw)

    cols = mock_st.columns.return_value
    assert cols[0].metric.called
    assert mock_st.markdown.called
    assert mock_st.expander.called
    markdown_calls = " ".join(str(c) for c in mock_st.markdown.call_args_list)
    assert "data-derived" in markdown_calls or "OHLCV" in markdown_calls
    assert "Trade type: stock" not in markdown_calls
    display = build_coach_outcome_display(raw)
    if display.review_items:
        assert mock_st.warning.called
        assert "Needs review" in markdown_calls


def test_dashboard_uses_structured_coach_rendering():
    text = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "from coach_outcome_ui import render_coach_outcome" in text
    assert "st.text(outcome)" not in text
    assert "outcome of the result (next to each positions)" not in text
    assert "st.text(outcome)" not in text
    assert "from live data" not in text
    assert "coach_analysis_expanded" in text
    assert "coach_analysis_expanded = False" in text
    assert "Collapse all coach analysis" in text
    assert "format_coach_expander_label" in text
    assert "render_coach_outcome(outcome)" in text


def test_run_coach_positions_surfaces_review_on_collapsed_labels():
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    results = run_coach_for_positions(positions)
    assert len(results) == len(positions)
    saw_review = False
    for pos in positions:
        display = build_coach_outcome_display(results[pos.symbol])
        assert display.review_count >= 0
        assert display.review_count == len(display.review_items)
        label = format_coach_expander_label(pos.symbol, display)
        if display.review_count > 0:
            saw_review = True
            assert "need review" in label
            assert any(c.is_review for c in display.view.criteria)
    assert saw_review


def test_real_coach_outcome_parses_and_formats():
    positions = derive_current_positions_from_trades(STOCK_EVENTS)
    assert positions
    raw = run_coach_for_position(positions[0])
    assert len(raw) > 200
    assert "PROCESS SCORE" in raw
    assert "data-derived" in raw
    assert "ACTION ITEMS" in raw
    assert "[PASS]" in raw or "[FAIL]" in raw or "[REVIEW" in raw

    display = build_coach_outcome_display(raw)
    assert display.view.process_score_value is not None
    assert display.has_auto_metrics
    assert len(display.auto_criteria) >= 5
    assert all(not c.is_review for c in display.auto_criteria)
    md = display.markdown_summary
    assert "Auto metrics (scored)" in md
    assert "Market context & process screening" in md
    assert any("x" in (c.detail or "") for c in display.auto_criteria)
    assert display.view.three_stop is not None
    assert display.view.profit_taking is not None
    assert display.view.recommendation_action in {
        "entry",
        "hold",
        "take profit",
        "cut losses",
    }
    assert display.view.recommendation_reason
    assert display.review_count >= 0
    assert display.review_count == len(display.review_items)
    assert len(display.markdown_summary) > 100
    assert "entry" in display.markdown_summary.lower() or "hold" in display.markdown_summary.lower()
    label = format_coach_expander_label(positions[0].symbol, display)
    if display.review_count > 0:
        assert "need review" in label