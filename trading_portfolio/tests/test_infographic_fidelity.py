"""Fidelity tests: SKILL.md + rules vs infographic JPG manifest (not ad-hoc lists)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jeff_sun_trading_coach import generate_report, load_rules, load_trades_csv
from jeff_sun_trading_coach.infographic_manifest import (
    BENCHMARK_AVG_LOSS_R,
    BENCHMARK_AVG_WIN_R,
    BENCHMARK_WIN_RATE,
    INFOGRAPHIC_JPG,
    INFOGRAPHIC_SHA256,
    INFOGRAPHIC_SIZE_BYTES,
    MIN_ADR_PCT,
    MIN_RVOL,
    PROFIT_10X_ACTION,
    REQUIRED_PROFIT_TABLE_ROWS,
    REQUIRED_SKILL_PHRASES,
    TARGET_AVG_LOSS_R,
    WISDOM_SUPER_TRADERS,
)
from jeff_sun_trading_coach.rules import SKILL_PATH

SKILL_TEXT = SKILL_PATH.read_text(encoding="utf-8")
RULES = load_rules()


def test_infographic_jpg_exists():
    assert INFOGRAPHIC_JPG.exists(), f"Infographic image missing: {INFOGRAPHIC_JPG}"
    assert INFOGRAPHIC_JPG.suffix.lower() in {".jpg", ".jpeg", ".png"}


def test_infographic_jpg_integrity_pinned_to_manifest():
    """Detect accidental JPG swap — manifest SHA256/size must match on-disk file."""
    data = INFOGRAPHIC_JPG.read_bytes()
    assert len(data) == INFOGRAPHIC_SIZE_BYTES
    digest = hashlib.sha256(data).hexdigest()
    assert digest == INFOGRAPHIC_SHA256
    assert data[:2] == b"\xff\xd8", "expected JPEG magic bytes"


@pytest.mark.parametrize("phrase", REQUIRED_SKILL_PHRASES)
def test_skill_contains_manifest_phrase_from_jpg(phrase: str):
    assert phrase in SKILL_TEXT, f"SKILL.md missing JPG manifest phrase: {phrase!r}"


def test_rules_constants_match_infographic_manifest():
    assert RULES.benchmark_win_rate == pytest.approx(BENCHMARK_WIN_RATE)
    assert RULES.benchmark_avg_win_r == pytest.approx(BENCHMARK_AVG_WIN_R)
    assert RULES.benchmark_avg_loss_r == pytest.approx(BENCHMARK_AVG_LOSS_R)
    assert RULES.target_avg_loss_r == pytest.approx(TARGET_AVG_LOSS_R)
    assert RULES.min_rvol == pytest.approx(MIN_RVOL)
    assert RULES.min_adr_pct == pytest.approx(MIN_ADR_PCT)


@pytest.mark.parametrize("extension,action", REQUIRED_PROFIT_TABLE_ROWS)
def test_skill_profit_table_matches_jpg_manifest(extension: str, action: str):
    assert extension in SKILL_TEXT
    assert action in SKILL_TEXT


def test_profit_taking_parsed_from_skill_matches_jpg_10x_action():
    joined = " ".join(RULES.profit_taking_atr)
    assert PROFIT_10X_ACTION in joined
    assert "Sell 20% with trail stops" not in joined


@pytest.mark.parametrize("extension,action", REQUIRED_PROFIT_TABLE_ROWS)
def test_rules_profit_taking_parsed_matches_jpg_manifest(extension: str, action: str):
    joined = " ".join(RULES.profit_taking_atr)
    assert extension in joined
    assert action in joined


def test_entry_framework_parsed_from_skill_not_empty():
    items = RULES.entry_framework
    assert len(items) >= 13
    joined = " ".join(items).lower()
    assert "vars" in joined
    assert "rs line" in joined
    assert "orma" in joined
    assert "pocket pivots" in joined
    assert "institutional accumulation" in joined


def test_wisdom_matches_jpg_in_skill():
    assert WISDOM_SUPER_TRADERS in SKILL_TEXT


def test_three_stop_parsed_from_skill_includes_sell_third_and_trail_tiers():
    joined = " ".join(RULES.three_stop_strategy).lower()
    assert "sell 1/3" in joined
    assert "1r" in joined and "2r" in joined and "3r" in joined


def test_hard_rules_parsed_from_skill_has_eight_rules():
    assert len(RULES.hard_rules) == 8


def test_hard_rules_never_violated_phrase_in_skill_matches_manifest():
    from jeff_sun_trading_coach.infographic_manifest import HARD_RULES_NEVER_VIOLATED

    assert HARD_RULES_NEVER_VIOLATED in SKILL_TEXT
    assert "❌" in SKILL_TEXT  # infographic red-X discipline markers in SKILL §5


def test_compute_blocks_entry_on_signal_hard_violation_without_caller_violations():
    """Infographic hard rules apply from signals even when violations=[] is passed."""
    from jeff_sun_trading_coach.entry_framework import EntrySignals, score_entry
    from jeff_sun_trading_coach.recommendation import compute_trade_recommendation

    sig = EntrySignals(
        rs_line_new_highs=True,
        is_vars=True,
        rvol=2.5,
        adr_pct=6.0,
        vcp=True,
        atr_from_50ma=1.5,
        relative_strength=True,
        lod_atr_pct=75,
        trade_against_declining_200ma=False,
    )
    scores = score_entry(sig, RULES)
    rec = compute_trade_recommendation(
        description="NVDA swing RS new highs VARS confirm",
        entry_scores=scores,
        violations=[],
        signals=sig,
        rules=RULES,
    )
    assert rec.action == "hold"
    assert "hard-rule" in rec.reason.lower() or "violation" in rec.reason.lower()


def test_report_benchmark_and_profit_taking_from_skill():
    stock_events = (
        Path(__file__).resolve().parent.parent / "stock_events_transactions_2026-06-23.csv"
    )
    if not stock_events.exists():
        pytest.skip("stock events fixture missing")
    report = generate_report(load_trades_csv(stock_events), RULES)
    assert "-0.7R avg loss" in report
    assert PROFIT_10X_ACTION in report
    assert WISDOM_SUPER_TRADERS not in report  # wisdom not in fill report path