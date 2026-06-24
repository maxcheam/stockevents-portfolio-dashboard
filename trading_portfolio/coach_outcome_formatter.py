"""Pure formatting helpers for Jeff Sun coach outcome strings (display layer only)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_STATUS_RE = re.compile(
    r"^\s*\[(PASS|FAIL|REVIEW(?:\s*[—-]\s*[^]]+)?)\]\s*(.+?)\s*$"
)
_CLASSIFY_RE = re.compile(
    r"^1\.\s*CLASSIFY:\s*(.+?)(?:\s*\|\s*horizon:\s*(.+))?\s*$",
    re.IGNORECASE,
)
_PROCESS_SCORE_RE = re.compile(
    r"^8\.\s*PROCESS SCORE:\s*(-?[0-9]+(?:\.[0-9]+)?)/10\s*(?:\((.+)\))?\s*$",
    re.IGNORECASE,
)
_PROCESS_SCORE_FALLBACK_RE = re.compile(
    r"PROCESS SCORE:\s*(-?[0-9]+(?:\.[0-9]+)?)/10\s*(?:\((.+)\))?",
    re.IGNORECASE,
)
_DATA_DERIVED_MARKERS = ("data-derived", "Market context: auto-computed")
_RECOMMENDATION_RE = re.compile(
    r"^TRADE RECOMMENDATION:\s*(ENTRY|HOLD|TAKE PROFIT|CUT LOSSES)\s*[—-]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITALIC_RE = re.compile(r"\*([^*]+)\*")


@dataclass(frozen=True)
class FrameworkStatus:
    status: str
    label: str
    detail: str | None = None

    @property
    def is_pass(self) -> bool:
        return self.status == "PASS"

    @property
    def is_fail(self) -> bool:
        return self.status == "FAIL"

    @property
    def is_review(self) -> bool:
        return self.status.startswith("REVIEW")


@dataclass(frozen=True)
class CoachCriterion:
    status: str
    label: str
    detail: str | None = None

    @property
    def is_pass(self) -> bool:
        return self.status == "PASS"

    @property
    def is_fail(self) -> bool:
        return self.status == "FAIL"

    @property
    def is_review(self) -> bool:
        return self.status.startswith("REVIEW")


@dataclass(frozen=True)
class CoachOutcomeView:
    raw: str
    classification: str | None = None
    horizon: str | None = None
    market_notes: tuple[str, ...] = ()
    criteria: tuple[CoachCriterion, ...] = ()
    hard_rules_summary: str | None = None
    violations: tuple[str, ...] = ()
    process_score: str | None = None
    process_score_value: float | None = None
    process_score_detail: str | None = None
    action_items: tuple[str, ...] = ()
    define_1r: str | None = None
    three_stop: FrameworkStatus | None = None
    position_timeline_title: str | None = None
    position_timeline_notes: tuple[str, ...] = ()
    profit_taking: FrameworkStatus | None = None
    profit_taking_targets: tuple[str, ...] = ()
    profit_golden_rule: str | None = None
    recommendation_action: str | None = None
    recommendation_reason: str | None = None
    verdict_synthesis_observations: tuple[str, ...] = ()
    verdict_bottom_line: str | None = None


def _strip_markdown(text: str) -> str:
    text = _MD_BOLD_RE.sub(r"\1", text)
    return _MD_ITALIC_RE.sub(r"\1", text).strip()


def _parse_three_stop_status(detail: str) -> FrameworkStatus:
    if "documented" in detail.lower():
        return FrameworkStatus("PASS", "3-stop plan documented", detail)
    if "missing" in detail.lower():
        return FrameworkStatus("REVIEW", "3-stop plan missing", detail)
    return FrameworkStatus("INFO", "3-stop plan", detail)


def _parse_profit_taking_status(detail: str) -> FrameworkStatus:
    if "scale-out planned" in detail.lower():
        return FrameworkStatus("PASS", "Profit-taking scale-out planned", detail)
    if "review" in detail.lower():
        return FrameworkStatus("REVIEW", "Profit-taking plan needs review", detail)
    return FrameworkStatus("INFO", "Profit-taking", detail)


def _parse_position_management_and_profit_taking(
    lines: list[str],
) -> dict[str, object]:
    define_1r: str | None = None
    three_stop: FrameworkStatus | None = None
    timeline_title: str | None = None
    timeline_notes: list[str] = []
    profit_taking: FrameworkStatus | None = None
    profit_targets: list[str] = []
    golden_rule: str | None = None
    section: str | None = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("4. DEFINE 1R"):
            section = "define_1r"
            continue
        if stripped.startswith("5. 3-STOP PLAN"):
            section = "three_stop"
            continue
        if stripped.startswith("6."):
            section = "timeline"
            timeline_title = stripped
            continue
        if stripped.startswith("SKILL EXCERPT — Profit-Taking"):
            section = "profit_excerpt"
            continue
        if stripped.startswith("7. PROFIT-TAKING"):
            section = "profit_status"
            continue
        if stripped.startswith("8. PROCESS SCORE"):
            section = None
            continue

        if section == "define_1r" and stripped and not stripped.startswith("5."):
            define_1r = _strip_markdown(stripped)
        elif section == "three_stop" and stripped:
            three_stop = _parse_three_stop_status(_strip_markdown(stripped))
        elif section == "timeline" and stripped:
            timeline_notes.append(_strip_markdown(stripped))
        elif section == "profit_excerpt" and stripped:
            if stripped.startswith("|") and "ATR" in stripped and "---" not in stripped:
                cells = [_strip_markdown(c) for c in stripped.split("|") if c.strip()]
                if len(cells) >= 2 and cells[0].lower() != "extension":
                    profit_targets.append(f"{cells[0]} → {cells[1]}")
            elif "Golden Rule" in stripped:
                golden_rule = _strip_markdown(stripped)
        elif section == "profit_status" and stripped:
            profit_taking = _parse_profit_taking_status(_strip_markdown(stripped))

    return {
        "define_1r": define_1r,
        "three_stop": three_stop,
        "position_timeline_title": timeline_title,
        "position_timeline_notes": tuple(timeline_notes),
        "profit_taking": profit_taking,
        "profit_taking_targets": tuple(profit_targets),
        "profit_golden_rule": golden_rule,
    }


def _split_criterion_label_detail(text: str) -> tuple[str, str | None]:
    """Split 'RVOL >= 1.5x — 2.10x (data-derived)' into label and value detail."""
    if " — " not in text:
        return text.strip(), None
    label, detail = text.split(" — ", 1)
    return label.strip(), detail.strip() or None


def _normalize_status(raw_status: str) -> tuple[str, str | None]:
    if raw_status == "PASS":
        return "PASS", None
    if raw_status == "FAIL":
        return "FAIL", None
    if raw_status.startswith("REVIEW"):
        detail: str | None = None
        for sep in ("—", "-"):
            if sep in raw_status:
                detail = raw_status.split(sep, 1)[-1].strip() or None
                break
        if detail and detail.startswith("not stated"):
            return "REVIEW", detail
        return "REVIEW", detail or "not stated"
    return raw_status, None


def parse_coach_outcome(raw: str) -> CoachOutcomeView:
    """Parse a raw analyze_trade_description string into structured display fields."""
    if not raw or not raw.strip():
        return CoachOutcomeView(raw=raw or "")

    lines = raw.splitlines()
    market_notes: list[str] = []
    criteria: list[CoachCriterion] = []
    violations: list[str] = []
    action_items: list[str] = []
    classification: str | None = None
    horizon: str | None = None
    hard_rules_summary: str | None = None
    process_score: str | None = None
    process_score_value: float | None = None
    process_score_detail: str | None = None
    recommendation_action: str | None = None
    recommendation_reason: str | None = None
    verdict_observations: list[str] = []
    verdict_bottom_line: str | None = None

    section: str | None = None
    in_market_context = False

    for line in lines:
        stripped = line.strip()

        classify_match = _CLASSIFY_RE.match(stripped)
        if classify_match:
            classification = classify_match.group(1).strip()
            horizon = (classify_match.group(2) or "").strip() or None
            section = "classify"
            continue

        if "Market context: auto-computed" in line:
            in_market_context = True
            section = "market"
            continue

        if in_market_context and stripped.startswith("•"):
            market_notes.append(stripped.lstrip("•").strip())
            continue
        if in_market_context and not stripped:
            continue
        if in_market_context:
            in_market_context = False

        status_match = _STATUS_RE.match(line)
        if status_match:
            status, review_detail = _normalize_status(status_match.group(1).strip())
            label, value_detail = _split_criterion_label_detail(
                status_match.group(2).strip()
            )
            criteria.append(
                CoachCriterion(
                    status=status,
                    label=label,
                    detail=value_detail or review_detail,
                )
            )
            continue

        if stripped.startswith("3. HARD RULES"):
            section = "hard_rules"
            continue

        process_match = _PROCESS_SCORE_RE.match(stripped)
        if process_match:
            process_score = stripped.split(":", 1)[-1].strip()
            process_score_value = float(process_match.group(1))
            process_score_detail = (process_match.group(2) or "").strip() or None
            section = "process"
            continue

        rec_match = _RECOMMENDATION_RE.match(stripped)
        if rec_match:
            action_raw = rec_match.group(1).strip().lower()
            recommendation_action = (
                "take profit" if action_raw == "take profit" else action_raw
            )
            recommendation_reason = rec_match.group(2).strip()
            section = None
            continue

        if stripped.startswith("VERDICT SYNTHESIS"):
            section = "verdict_synthesis"
            continue
        if section == "verdict_synthesis":
            if stripped == "Key Observations":
                continue
            if stripped == "Bottom Line":
                section = "verdict_bottom"
                continue
            if stripped.startswith("•"):
                verdict_observations.append(stripped.lstrip("•").strip())
                continue
            if stripped.startswith("9. ACTION ITEMS"):
                section = "actions"
            else:
                continue
            if section != "actions":
                continue
        if section == "verdict_bottom":
            if stripped.startswith("9. ACTION ITEMS"):
                section = "actions"
            elif stripped:
                verdict_bottom_line = stripped
                section = None
                continue
            else:
                continue

        if stripped.startswith("9. ACTION ITEMS"):
            section = "actions"
            continue

        if section == "hard_rules":
            if stripped.startswith("⚠") or "VIOLATION:" in stripped:
                violations.append(
                    stripped.replace("⚠", "").replace("VIOLATION:", "Violation:").strip()
                )
                continue
            if stripped.startswith("✓"):
                hard_rules_summary = stripped.lstrip("✓").strip()
                continue

        if section == "actions" and stripped.startswith("→"):
            action_items.append(stripped.lstrip("→").strip())

    if process_score_value is None:
        for line in lines:
            fallback = _PROCESS_SCORE_FALLBACK_RE.search(line)
            if fallback:
                process_score_value = float(fallback.group(1))
                process_score_detail = (fallback.group(2) or "").strip() or None
                process_score = line.strip().split(":", 1)[-1].strip()
                break

    mgmt = _parse_position_management_and_profit_taking(lines)

    return CoachOutcomeView(
        raw=raw,
        classification=classification,
        horizon=horizon,
        market_notes=tuple(market_notes),
        criteria=tuple(criteria),
        hard_rules_summary=hard_rules_summary,
        violations=tuple(violations),
        process_score=process_score,
        process_score_value=process_score_value,
        process_score_detail=process_score_detail,
        action_items=tuple(action_items),
        define_1r=mgmt["define_1r"],  # type: ignore[arg-type]
        three_stop=mgmt["three_stop"],  # type: ignore[arg-type]
        position_timeline_title=mgmt["position_timeline_title"],  # type: ignore[arg-type]
        position_timeline_notes=mgmt["position_timeline_notes"],  # type: ignore[arg-type]
        profit_taking=mgmt["profit_taking"],  # type: ignore[arg-type]
        profit_taking_targets=mgmt["profit_taking_targets"],  # type: ignore[arg-type]
        profit_golden_rule=mgmt["profit_golden_rule"],  # type: ignore[arg-type]
        recommendation_action=recommendation_action,
        recommendation_reason=recommendation_reason,
        verdict_synthesis_observations=tuple(verdict_observations),
        verdict_bottom_line=verdict_bottom_line,
    )


def _status_icon(status: str) -> str:
    if status == "PASS":
        return "✅"
    if status == "FAIL":
        return "❌"
    if status == "INFO":
        return "ℹ️"
    return "⚠️"


def _render_framework_status(item: FrameworkStatus) -> str:
    detail = f" — {item.detail}" if item.detail else ""
    return f"{_status_icon(item.status)} {item.status} — {item.label}{detail}"


def _status_badge(status: str) -> str:
    if status == "PASS":
        return "**PASS**"
    if status == "FAIL":
        return "**FAIL**"
    return "**REVIEW**"


@dataclass(frozen=True)
class ReviewItem:
    """A single criterion or framework element that needs user clarification."""

    label: str
    detail: str | None = None
    source: str = "entry"  # entry | position | profit


def collect_review_items(view: CoachOutcomeView) -> tuple[ReviewItem, ...]:
    """Gather all REVIEW-status items from entry criteria and position frameworks."""
    items: list[ReviewItem] = []
    for crit in view.criteria:
        if crit.is_review:
            items.append(
                ReviewItem(label=crit.label, detail=crit.detail, source="entry")
            )
    if view.three_stop is not None and view.three_stop.is_review:
        items.append(
            ReviewItem(
                label=view.three_stop.label,
                detail=view.three_stop.detail,
                source="position",
            )
        )
    if view.profit_taking is not None and view.profit_taking.is_review:
        items.append(
            ReviewItem(
                label=view.profit_taking.label,
                detail=view.profit_taking.detail,
                source="profit",
            )
        )
    return tuple(items)


def non_auto_review_items(
    view: CoachOutcomeView,
    auto_criteria: tuple[CoachCriterion, ...],
) -> tuple[ReviewItem, ...]:
    """REVIEW items excluding auto-computed market metrics."""
    auto_labels = {c.label for c in auto_criteria}
    return tuple(
        item
        for item in collect_review_items(view)
        if item.source != "entry" or item.label not in auto_labels
    )


def format_review_item_text(item: ReviewItem) -> str:
    """Single-line review text without duplicated REVIEW/MISSING prefixes."""
    detail = (item.detail or "").strip()
    if not detail or detail.lower() == "not stated":
        return f"{item.label} (not stated)" if detail else item.label
    lowered = detail.lower()
    if lowered.startswith(("review —", "review -", "missing —", "missing -")):
        return item.label
    if detail.lower() in item.label.lower():
        return item.label
    return f"{item.label} — {detail}"


def format_review_indicator(review_count: int) -> str | None:
    """Compact review flag for collapsed coach card headers."""
    if review_count <= 0:
        return None
    noun = "item" if review_count == 1 else "items"
    return f"⚠️ {review_count} {noun} need review"


@dataclass(frozen=True)
class CoachOutcomeDisplay:
    """Structured, human-readable coach outcome for UI rendering."""

    view: CoachOutcomeView
    has_auto_metrics: bool
    auto_criteria: tuple[CoachCriterion, ...]
    headline: str | None
    pass_count: int
    fail_count: int
    review_count: int
    review_items: tuple[ReviewItem, ...]
    non_auto_review_items: tuple[ReviewItem, ...]
    markdown_summary: str


def recommendation_display_title(action: str | None) -> str | None:
    if not action:
        return None
    labels = {
        "entry": "Suitable for entry",
        "hold": "Hold",
        "take profit": "Take profit",
        "cut losses": "Cut losses",
    }
    return labels.get(action, action.title())


def recommendation_icon(action: str | None) -> str:
    if action == "entry":
        return "🟢"
    if action == "take profit":
        return "🟡"
    if action == "cut losses":
        return "🔴"
    if action == "hold":
        return "🔵"
    return "⚪"


_REASON_PREFIXES_BY_ACTION: dict[str, tuple[str, ...]] = {
    "hold": ("hold —", "hold -"),
    "take profit": ("take profit —", "take profit -"),
    "cut losses": ("cut losses —", "cut losses -"),
    "entry": (
        "suitable for entry —",
        "suitable for entry -",
        "conditional entry —",
        "conditional entry -",
    ),
}

_SPECIFIC_REASON_OPENERS: tuple[str, ...] = (
    "not suitable for entry",
    "suitable for entry",
    "conditional entry",
    "wait — setup not ready",
)


def strip_recommendation_reason_prefix(reason: str, action: str | None) -> str:
    """Remove a leading action phrase duplicated in TRADE RECOMMENDATION reasons."""
    text = reason.strip()
    if not text or not action:
        return text
    lower = text.lower()
    for prefix in _REASON_PREFIXES_BY_ACTION.get(action, ()):
        if lower.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return text


def format_recommendation_markdown(view: CoachOutcomeView) -> str | None:
    if not view.recommendation_action:
        return None
    title = recommendation_display_title(view.recommendation_action)
    icon = recommendation_icon(view.recommendation_action)
    reason = view.recommendation_reason or ""
    parts = [f"## {icon} {title}", "", reason]
    if view.verdict_synthesis_observations or view.verdict_bottom_line:
        parts.append("")
        parts.append("#### Relative strength synthesis")
        for obs in view.verdict_synthesis_observations:
            parts.append(f"- {obs}")
        if view.verdict_bottom_line:
            parts.append("")
            parts.append(f"**Bottom line:** {view.verdict_bottom_line}")
    return "\n".join(parts)


def format_recommendation_verdict_compact(
    view: CoachOutcomeView,
    *,
    max_reason: int = 72,
) -> str | None:
    """Plain-text verdict snippet for inline UI (e.g. expander label)."""
    if not view.recommendation_action:
        return None
    icon = recommendation_icon(view.recommendation_action)
    raw = (view.recommendation_reason or "").strip()
    if not raw:
        title = recommendation_display_title(view.recommendation_action)
        return f"{icon} {title}" if title else None

    raw_lower = raw.lower()
    if any(raw_lower.startswith(opener) for opener in _SPECIFIC_REASON_OPENERS):
        display = raw
    else:
        title = recommendation_display_title(view.recommendation_action)
        detail = strip_recommendation_reason_prefix(raw, view.recommendation_action)
        display = f"{title} — {detail}" if detail else (title or raw)

    if len(display) > max_reason:
        display = display[: max_reason - 1].rstrip() + "…"
    return f"{icon} {display}"


def format_recommendation_one_liner(
    view: CoachOutcomeView,
    *,
    max_reason: int = 100,
) -> str | None:
    """Compact markdown verdict line."""
    compact = format_recommendation_verdict_compact(view, max_reason=max_reason)
    if not compact:
        return None
    icon = recommendation_icon(view.recommendation_action)
    display = compact[len(icon) :].lstrip() if compact.startswith(icon) else compact
    return f"**{icon} {display}**"


def format_coach_expander_label(
    symbol: str,
    display: CoachOutcomeDisplay,
) -> str:
    """Expander title with verdict and review indicator visible while collapsed."""
    view = display.view
    verdict = format_recommendation_verdict_compact(view)
    review = format_review_indicator(display.review_count)
    parts: list[str] = [symbol]
    if review:
        parts.append(review)
    if verdict:
        parts.append(verdict)
    if len(parts) == 1:
        return symbol
    return " · ".join(parts)


def format_classification_headline(
    classification: str | None,
    horizon: str | None,
) -> str | None:
    """Return a useful headline; omit generic 'stock' / 'unknown' classifications."""
    if horizon:
        return f"**Horizon:** {horizon}"
    if classification and classification.lower() not in {"stock", "unknown"}:
        return f"**Setup:** {classification}"
    return None


def format_needs_review_markdown(review_items: tuple[ReviewItem, ...]) -> str | None:
    """Render a concise list of items awaiting clarification."""
    if not review_items:
        return None
    lines = ["#### Needs review"]
    for item in review_items:
        lines.append(f"- ⚠️ {format_review_item_text(item)}")
    return "\n\n".join(lines)


def build_coach_outcome_display(raw: str) -> CoachOutcomeDisplay:
    """Parse raw coach text into a structured display model for dashboard rendering."""
    view = parse_coach_outcome(raw)
    has_auto = coach_outcome_has_auto_metrics(raw)
    auto_crit = auto_criteria_from_view(view) if has_auto else ()
    review_items = collect_review_items(view)
    manual_reviews = non_auto_review_items(view, auto_crit)
    return CoachOutcomeDisplay(
        view=view,
        has_auto_metrics=has_auto,
        auto_criteria=auto_crit,
        headline=format_classification_headline(view.classification, view.horizon),
        pass_count=sum(1 for c in view.criteria if c.is_pass),
        fail_count=sum(1 for c in view.criteria if c.is_fail),
        review_count=len(review_items),
        review_items=review_items,
        non_auto_review_items=manual_reviews,
        markdown_summary=format_coach_outcome_markdown(
            view,
            review_items=manual_reviews,
            auto_criteria=auto_crit,
        ),
    )


def format_coach_outcome_markdown(
    view: CoachOutcomeView,
    *,
    review_items: tuple[ReviewItem, ...] | None = None,
    auto_criteria: tuple[CoachCriterion, ...] | None = None,
) -> str:
    """Render a human-readable markdown summary from a parsed coach outcome."""
    if not view.raw.strip():
        return "_No coach analysis available._"

    parts: list[str] = []

    rec_md = format_recommendation_markdown(view)
    if rec_md:
        parts.append(rec_md)

    items = review_items if review_items is not None else collect_review_items(view)
    needs_review = format_needs_review_markdown(items)
    if needs_review:
        parts.append(needs_review)

    if view.process_score_value is not None:
        parts.append(f"### Process score: **{view.process_score_value:.1f}/10**")
        if view.process_score_detail:
            parts.append(f"_{view.process_score_detail}_")
    elif view.process_score:
        parts.append(f"### Process score: **{view.process_score}**")

    headline = format_classification_headline(view.classification, view.horizon)
    if headline:
        parts.append(headline)

    has_auto_block = coach_outcome_has_auto_metrics(view.raw)
    if has_auto_block and view.market_notes:
        parts.append("#### Market context & process screening")
        for note in view.market_notes:
            parts.append(f"- {note}")

    auto_crit = (
        auto_criteria
        if auto_criteria is not None
        else (auto_criteria_from_view(view) if has_auto_block else ())
    )
    auto_labels = {c.label for c in auto_crit}
    if auto_crit:
        parts.append("#### Auto metrics (scored)")
        for crit in auto_crit:
            parts.append(
                f"- {_status_icon(crit.status)} {_status_badge(crit.status)} · "
                f"{format_auto_criterion_display(crit)}"
            )

    other_criteria = [c for c in view.criteria if c.label not in auto_labels]
    if other_criteria:
        parts.append("#### Entry framework checklist")
        for crit in other_criteria:
            suffix = f" — _{crit.detail}_" if crit.detail else ""
            parts.append(
                f"- {_status_icon(crit.status)} {_status_badge(crit.status)} · {crit.label}{suffix}"
            )

    if view.violations:
        parts.append("#### Hard rule violations")
        for violation in view.violations:
            parts.append(f"- ❌ {violation}")
    elif view.hard_rules_summary:
        parts.append(f"#### Hard rules\n- ✅ {view.hard_rules_summary}")

    if view.define_1r or view.three_stop or view.position_timeline_notes:
        parts.append("#### Position management")
        if view.define_1r:
            parts.append(f"- Define 1R: {view.define_1r}")
        if view.three_stop:
            parts.append(
                f"- {_status_icon(view.three_stop.status)} {_status_badge(view.three_stop.status)} · "
                f"{view.three_stop.label}"
            )
        if view.position_timeline_title:
            parts.append(f"- {_strip_markdown(view.position_timeline_title)}")
        for note in view.position_timeline_notes:
            parts.append(f"  - {note}")

    if view.profit_taking or view.profit_taking_targets:
        parts.append("#### Profit-taking framework")
        if view.profit_taking:
            parts.append(
                f"- {_status_icon(view.profit_taking.status)} {_status_badge(view.profit_taking.status)} · "
                f"{view.profit_taking.label}"
            )
        for target in view.profit_taking_targets:
            parts.append(f"- {target}")
        if view.profit_golden_rule:
            parts.append(f"- _{view.profit_golden_rule}_")

    if view.action_items:
        parts.append("#### Action items")
        for item in view.action_items:
            parts.append(f"- {item}")

    return "\n\n".join(parts)


def coach_outcome_has_auto_metrics(raw: str) -> bool:
    """True when the raw outcome includes auto-computed market context."""
    return any(marker in raw for marker in _DATA_DERIVED_MARKERS)


_AUTO_CRITERION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^vars?\s+confirming", re.IGNORECASE),
    re.compile(r"^rs\s+line\s+making", re.IGNORECASE),
    re.compile(r"^rvol\s*>=", re.IGNORECASE),
    re.compile(r"^adr%\s*>=", re.IGNORECASE),
    re.compile(r"^atr\s*<", re.IGNORECASE),
    re.compile(r"^relative strength", re.IGNORECASE),
    re.compile(r"^200-ma trend", re.IGNORECASE),
    re.compile(r"^vcp\s*/", re.IGNORECASE),
    re.compile(r"^avg\s*\$\s*volume", re.IGNORECASE),
)

def _is_auto_criterion_label(label: str) -> bool:
    return any(pat.search(label) for pat in _AUTO_CRITERION_PATTERNS)


def _auto_criterion_sort_key(label: str) -> int:
    for idx, pat in enumerate(_AUTO_CRITERION_PATTERNS):
        if pat.search(label):
            return idx
    return len(_AUTO_CRITERION_PATTERNS)


def _strip_data_derived_suffix(detail: str | None) -> str | None:
    if not detail:
        return None
    text = detail.strip()
    if text.endswith("(data-derived)"):
        text = text[: -len("(data-derived)")].strip()
    return text or None


def format_auto_criterion_display(crit: CoachCriterion) -> str:
    """Render auto metric label with its computed value."""
    detail = _strip_data_derived_suffix(crit.detail)
    if detail:
        return f"{crit.label} · {detail}"
    return crit.label


def enrich_auto_criteria(
    criteria: tuple[CoachCriterion, ...],
    market_notes: tuple[str, ...],
) -> tuple[CoachCriterion, ...]:
    """Return parsed auto criteria; values come from inline (data-derived) lines only."""
    _ = market_notes
    return criteria


def _criterion_has_data_derived_detail(crit: CoachCriterion) -> bool:
    return bool(crit.detail and "(data-derived)" in crit.detail.lower())


def auto_criteria_from_view(view: CoachOutcomeView) -> tuple[CoachCriterion, ...]:
    """Return scored auto metric criteria (data-derived values or text-sourced PASS/FAIL)."""
    matched = [
        c
        for c in view.criteria
        if _is_auto_criterion_label(c.label)
        and (_criterion_has_data_derived_detail(c) or c.is_pass or c.is_fail)
    ]
    ordered = sorted(matched, key=lambda c: _auto_criterion_sort_key(c.label))
    return enrich_auto_criteria(tuple(ordered), view.market_notes)