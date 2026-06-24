"""Canonical infographic text extracted from Jeff Sun's Complete Trading Guide.jpg.

This module is the audit reference for fidelity tests. Phrases were transcribed
from the project infographic image (not invented in tests).
"""

from __future__ import annotations

from pathlib import Path

INFOGRAPHIC_JPG = (
    Path(__file__).resolve().parent.parent / "Jeff Sun's Complete Trading Guide.jpg"
)

# Pin infographic bytes so manifest/tests detect accidental image replacement.
INFOGRAPHIC_SIZE_BYTES = 158_616
INFOGRAPHIC_SHA256 = (
    "b393d271265a7a5c09d9e4cc7d274589c3b593ad23ae01545766a1d8e7177f46"
)

# --- Profit-taking (infographic §7) ---
PROFIT_4X_ACTION = "Sell 20–30%"
PROFIT_6X_ACTION = "Sell another 20–30%"
PROFIT_8X_ACTION = "Sell another 20%"
PROFIT_10X_ACTION = "Let winners run with trail stops"
GOLDEN_RULE_PHRASE = "Sell some into strength"

# --- Wisdom (infographic §10) ---
WISDOM_SUPER_TRADERS = "Super traders are made because you lose a lot and still win"
WISDOM_FISHERMEN = "When fishermen come to the sea, they repair nets"

# --- Entry framework (infographic §1) ---
ENTRY_RELATIVE_STRENGTH_FIRST = "Relative Strength First"
ENTRY_VARS = "**VARs** confirming strength"
ENTRY_RS_LINE = "RS line making new highs"
ENTRY_ORMA = "ORMA reclaim"

# --- Execution discipline (infographic §5) ---
HARD_RULES_NEVER_VIOLATED = "Hard Rules (NEVER VIOLATED)"

# --- 3-stop benefit (infographic §2, expressed in R in SKILL) ---
THREE_STOP_BENEFIT_LOSS = "-0.7R"

# --- Math / constants aligned with infographic + 3-stop benefit ---
BENCHMARK_WIN_RATE = 0.35
BENCHMARK_AVG_WIN_R = 6.0
BENCHMARK_AVG_LOSS_R = 0.7
TARGET_AVG_LOSS_R = 0.7
MIN_RVOL = 1.5
MIN_ADR_PCT = 5.0

REQUIRED_SKILL_PHRASES: tuple[str, ...] = (
    "Trade Tight, Think in R, Focus on Process",
    ENTRY_RELATIVE_STRENGTH_FIRST,
    HARD_RULES_NEVER_VIOLATED,
    ENTRY_VARS,
    ENTRY_RS_LINE,
    ENTRY_ORMA,
    "Pocket pivots",
    "Institutional accumulation",
    "spring coil",
    '"Launched"',
    "5%+",
    "sell 1/3",
    "1R → 2R → 3R",
    "-1R to -0.7R",
    "Day T+3 (Critical)",
    "LoD exceeds **60% ATR**",
    "declining 200-MA",
    "gap resistance",
    PROFIT_10X_ACTION,
    GOLDEN_RULE_PHRASE,
    "0.7R average loss",
    ">6R average win",
    "13+",
    "5% monthly",
    WISDOM_SUPER_TRADERS,
    WISDOM_FISHERMEN,
    "Think in 10s of trades",
)

REQUIRED_PROFIT_TABLE_ROWS: tuple[tuple[str, str], ...] = (
    ("4x ATR from 50-MA", PROFIT_4X_ACTION),
    ("6x ATR from 50-MA", PROFIT_6X_ACTION),
    ("8x ATR from 50-MA", PROFIT_8X_ACTION),
    ("10x+ ATR from 50-MA", PROFIT_10X_ACTION),
)