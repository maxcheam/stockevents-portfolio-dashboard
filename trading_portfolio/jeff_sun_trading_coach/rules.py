"""Load Jeff Sun trading rules from SKILL.md (single source of truth)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parent / "SKILL.md"


@dataclass(frozen=True)
class JeffSunRules:
    core_philosophy: str
    min_rvol: float
    min_adr_pct: float
    max_atr_from_50ma: float
    max_lod_atr_pct: float
    max_new_positions_per_session: int
    no_entry_minutes_after_open: int
    target_avg_loss_r: float
    benchmark_win_rate: float
    benchmark_avg_win_r: float
    benchmark_avg_loss_r: float
    profit_take_4x_atr_pct: float
    profit_take_8x_atr_pct: float
    scale_out_min_pct: float
    scale_out_max_pct: float
    _skill_text: str = ""

    @property
    def hard_rules(self) -> list[str]:
        section = _extract_section(self._skill_text, "Execution Discipline")
        rules: list[str] = []
        for line in section.splitlines():
            if "❌" not in line:
                continue
            rule = re.sub(r"^-\s*❌\s*", "", line.strip())
            rules.append(rule)
        if rules:
            return rules
        return _fallback_hard_rules(self)

    @property
    def entry_framework(self) -> list[str]:
        items = _parse_entry_framework_bullets(self._skill_text)
        if items:
            return items
        return _fallback_entry_framework(self)

    @property
    def three_stop_strategy(self) -> list[str]:
        section = _extract_section(self._skill_text, "Risk Management")
        rows = _parse_markdown_table(section, min_cols=3)
        items: list[str] = []
        for row in rows:
            if len(row) < 3:
                continue
            stop, trigger, action = row[0], row[1], row[2]
            if "stop" not in stop.lower():
                continue
            items.append(f"{_strip_md(stop)}: {_strip_md(trigger)} — {_strip_md(action)}")
        items.append(
            f"Target average loss: -{self.target_avg_loss_r}R (vs -1R without 3-stop)"
        )
        return items if len(items) > 1 else _fallback_three_stop(self)

    @property
    def profit_taking_atr(self) -> list[str]:
        section = _extract_section(self._skill_text, "Profit-Taking")
        rows = _parse_markdown_table(section, min_cols=2)
        items: list[str] = []
        for row in rows:
            ext, action = row[0], row[1]
            if "atr" not in ext.lower() and "x" not in ext.lower():
                continue
            items.append(f"{_strip_md(ext)}: {_strip_md(action)}")
        golden = _extract_golden_rule(section)
        if golden:
            items.append(golden)
        return items if items else _fallback_profit_taking(self)

    @property
    def math_of_success(self) -> dict[str, float]:
        return {
            "benchmark_win_rate": self.benchmark_win_rate,
            "benchmark_avg_win_r": self.benchmark_avg_win_r,
            "benchmark_avg_loss_r": self.benchmark_avg_loss_r,
            "benchmark_expectancy_r": (
                self.benchmark_win_rate * self.benchmark_avg_win_r
                - (1 - self.benchmark_win_rate) * self.benchmark_avg_loss_r
            ),
        }


def _strip_md(text: str) -> str:
    return re.sub(r"\*\*", "", text).strip()


def _extract_section(text: str, heading_fragment: str) -> str:
    pattern = rf"##\s+[\d.]+\s+[^\n]*{re.escape(heading_fragment)}[^\n]*\n(.*?)(?=\n---|\n##\s)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else ""


def _parse_markdown_table(section_text: str, min_cols: int = 2) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    in_table = False
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and re.search(r"\-{3,}", stripped):
            in_table = True
            continue
        if not in_table or not stripped.startswith("|"):
            if in_table:
                break
            continue
        cols = tuple(c.strip() for c in stripped.split("|")[1:-1])
        if len(cols) < min_cols:
            continue
        if cols[0].lower().startswith("stop") or cols[0].lower().startswith("extension"):
            continue
        if cols[0].startswith("**Day") or cols[0].startswith("Day"):
            continue
        rows.append(cols)
    return rows


def _parse_entry_framework_bullets(text: str) -> list[str]:
    section = _extract_section(text, "Entry Framework")
    items: list[str] = []
    heading = ""
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            heading = stripped.replace("### ", "").strip()
            continue
        if not stripped.startswith("- "):
            continue
        bullet = _strip_md(stripped[2:])
        if heading:
            items.append(f"{heading}: {bullet}")
        else:
            items.append(bullet)
    return items


def _extract_golden_rule(section_text: str) -> str:
    match = re.search(r"\*\*Golden Rule:\*\*\s*\*(.+?)\*", section_text, re.DOTALL)
    if match:
        return f"Golden Rule: {match.group(1).strip()}"
    return ""


def _fallback_entry_framework(rules: JeffSunRules) -> list[str]:
    return [
        f"Relative Strength First: VARs confirming strength",
        f"Volume Confirmation: RVOL >= {rules.min_rvol}x",
        f"Optimal Positioning: LoD within {rules.max_lod_atr_pct:.0f}% ATR",
    ]


def _fallback_hard_rules(rules: JeffSunRules) -> list[str]:
    return [
        f"No entry if LoD exceeds {rules.max_lod_atr_pct:.0f}% ATR",
        f"No entry if >{rules.max_atr_from_50ma:.0f}x ATR from 50-MA",
        f"No entry without substantial RVOL (minimum {rules.min_rvol}x)",
        "No chasing — wait for optimal setup",
        "No trading against declining 200-MA",
        f"No more than {rules.max_new_positions_per_session} new positions per session",
        f"No entry {rules.no_entry_minutes_after_open} mins after open (unless extreme RVOL)",
        "No trading into immediate gap resistance",
    ]


def _fallback_three_stop(rules: JeffSunRules) -> list[str]:
    return [
        "Stop 1 (Break-Even): failed hold within 1-2 hours or 1-2 days — move to break-even, sell 1/3",
        "Stop 2 (Break-Even +1R): key support break — lock +1R, sell 1/3 at 1R trail tier",
        "Stop 3 (Trail): trail at 1R → 2R → 3R tiers using ATR or moving-average support",
        f"Target average loss: -{rules.target_avg_loss_r}R (vs -1R without 3-stop)",
    ]


def _fallback_profit_taking(rules: JeffSunRules) -> list[str]:
    scale = f"{rules.scale_out_min_pct:.0f}-{rules.scale_out_max_pct:.0f}%"
    return [
        f"4x ATR from 50-MA: Sell {scale}",
        f"6x ATR from 50-MA: Sell another {scale}",
        f"8x ATR from 50-MA: Sell another {scale}",
        "10x+ ATR from 50-MA: Let winners run with trail stops",
        "Golden Rule: Sell some into strength, or never lose two weeks' gains in a day",
    ]


def _parse_constants_block(text: str) -> dict[str, str]:
    match = re.search(
        r"## Machine-Readable Constants.*?```\s*(.*?)```",
        text,
        re.DOTALL,
    )
    if not match:
        raise ValueError("Machine-Readable Constants block not found in SKILL.md")
    constants: dict[str, str] = {}
    for line in match.group(1).strip().splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        constants[key.strip()] = value.strip()
    return constants


def load_rules(skill_path: Path | None = None) -> JeffSunRules:
    path = skill_path or SKILL_PATH
    text = path.read_text(encoding="utf-8")
    c = _parse_constants_block(text)
    return JeffSunRules(
        core_philosophy=c["CORE_PHILOSOPHY"],
        min_rvol=float(c["MIN_RVOL"]),
        min_adr_pct=float(c["MIN_ADR_PCT"]),
        max_atr_from_50ma=float(c["MAX_ATR_FROM_50MA"]),
        max_lod_atr_pct=float(c["MAX_LOD_ATR_PCT"]),
        max_new_positions_per_session=int(c["MAX_NEW_POSITIONS_PER_SESSION"]),
        no_entry_minutes_after_open=int(c["NO_ENTRY_MINUTES_AFTER_OPEN"]),
        target_avg_loss_r=float(c["TARGET_AVG_LOSS_R"]),
        benchmark_win_rate=float(c["BENCHMARK_WIN_RATE"]),
        benchmark_avg_win_r=float(c["BENCHMARK_AVG_WIN_R"]),
        benchmark_avg_loss_r=float(c["BENCHMARK_AVG_LOSS_R"]),
        profit_take_4x_atr_pct=float(c["PROFIT_TAKE_4X_ATR_PCT"]),
        profit_take_8x_atr_pct=float(c["PROFIT_TAKE_8X_ATR_PCT"]),
        scale_out_min_pct=float(c["SCALE_OUT_MIN_PCT"]),
        scale_out_max_pct=float(c["SCALE_OUT_MAX_PCT"]),
        _skill_text=text,
    )