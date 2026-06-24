"""Pure market-metric computation for EntrySignals from OHLCV history."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .entry_framework import (
    LIQUIDITY_CRITERION,
    LIQUIDITY_MIN_AVG_DOLLAR_VOLUME_M,
    EntrySignals,
    extract_entry_price,
)
from .rules import JeffSunRules

AUTO_COMPUTED_FIELDS: tuple[str, ...] = (
    "is_vars",
    "rs_line_new_highs",
    "rvol",
    "adr_pct",
    "atr_from_50ma",
    "relative_strength",
    "trade_against_declining_200ma",
    "vcp",
    "avg_dollar_volume_m",
)

VARS_DATA_SOURCE_NOTE = (
    "yfinance daily OHLCV vs SPY — VARS proxy (not TradingView jfsrev script)"
)
RS_LINE_DATA_SOURCE_NOTE = (
    "yfinance daily OHLCV vs SPY — IBD-style RS ratio line proxy"
)
LOD_DATA_SOURCE_NOTE = (
    "yfinance daily OHLCV — most recent session LoD proxy (not live intraday)"
)
LAUNCH_ORMA_DATA_SOURCE_NOTE = (
    "yfinance daily OHLCV + 15m intraday — launch/ORMA proxy (not live TradingView)"
)


@dataclass(frozen=True)
class LaunchOrmaCheckResult:
    """Launch Signal (tight + RVOL) and ORMA reclaim entry checks."""

    price_used: float
    price_is_proposed: bool
    tight_label: str  # Yes | Partial | No
    rvol: float | None
    launch_status: str  # Strong Launch Signal | Moderate | Weak or None
    launch_observation: str
    opening_range_label: str
    orma_level: float | None
    orma_status: str  # Reclaimed ... | Not Reclaimed ... | Unavailable
    orma_observation: str
    overall_assessment: str
    entry_recommendation: str  # Favorable | Neutral | Unfavorable
    entry_reason: str
    notes: str

    @property
    def launched_pass(self) -> bool:
        return self.launch_status in {"Strong Launch Signal", "Moderate"}

    @property
    def orma_reclaimed(self) -> bool | None:
        if "Reclaimed" in self.orma_status and "Not" not in self.orma_status:
            return True
        if "Not Reclaimed" in self.orma_status:
            return False
        return None


@dataclass(frozen=True)
class LodCheckResult:
    """Jeff Sun hard rule: distance from LoD to entry must be < 60% of ATR(14)."""

    lod_price: float
    price_used: float
    atr_14: float
    distance: float
    pct_of_atr: float
    max_lod_atr_pct: float = 60.0

    @property
    def violated(self) -> bool:
        return self.pct_of_atr >= self.max_lod_atr_pct

    @property
    def status_label(self) -> str:
        if self.violated:
            return f"Violated (≥{self.max_lod_atr_pct:.0f}% ATR – hard rule)"
        return f"Acceptable (<{self.max_lod_atr_pct:.0f}% ATR)"

def _column_map(df: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for col in df.columns:
        key = str(col).lower()
        if key in {"open", "high", "low", "close", "volume"}:
            mapping[key] = col
    return mapping


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return OHLCV DataFrame with standard lowercase column names."""
    cols = _column_map(df)
    required = ("open", "high", "low", "close", "volume")
    if not all(k in cols for k in required):
        raise ValueError("OHLCV DataFrame must include Open, High, Low, Close, Volume")
    out = pd.DataFrame(
        {
            "Open": df[cols["open"]].astype(float),
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": df[cols["close"]].astype(float),
            "Volume": df[cols["volume"]].astype(float),
        },
        index=df.index,
    )
    return out.dropna(subset=["Close"]).sort_index()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range over `period` bars."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def compute_rvol(df: pd.DataFrame, lookback: int = 20) -> float | None:
    """Relative volume: latest bar volume / average of prior `lookback` bars."""
    if len(df) < lookback + 1:
        return None
    vol = df["Volume"]
    latest = float(vol.iloc[-1])
    avg = float(vol.iloc[-(lookback + 1) : -1].mean())
    if avg <= 0:
        return None
    return latest / avg


def compute_adr_pct(df: pd.DataFrame, lookback: int = 20) -> float | None:
    """Average daily range as percent of close."""
    if len(df) < lookback:
        return None
    window = df.iloc[-lookback:]
    daily_range_pct = (window["High"] - window["Low"]) / window["Close"] * 100.0
    return float(daily_range_pct.mean())


def _effective_lookback(requested: int, bar_count: int) -> int:
    """Shrink lookback windows when history is shorter than the default."""
    if bar_count < 2:
        return 0
    return max(1, min(requested, bar_count - 1))


def _adaptive_windows(
    n: int,
    *,
    rvol_lookback: int = 20,
    adr_lookback: int = 20,
    rs_lookback: int = 63,
    atr_ma_lookback: int = 50,
    atr_period_default: int = 14,
    trend_ma_lookback: int = 200,
    slope_lookback_default: int = 20,
) -> dict[str, int] | None:
    """Shared adaptive lookbacks for all auto metrics; None when history is too short."""
    if n < 5:
        return None
    slope_lb = max(1, min(slope_lookback_default, (n - 1) // 3))
    trend_ma_lb = max(slope_lb + 1, min(trend_ma_lookback, n - slope_lb))
    atr_period = max(1, min(atr_period_default, n))
    atr_ma_lb = max(atr_period, min(atr_ma_lookback, n))
    return {
        "rvol_lb": _effective_lookback(rvol_lookback, n),
        "adr_lb": min(adr_lookback, n),
        "rs_lb": _effective_lookback(rs_lookback, n),
        "atr_ma_lb": atr_ma_lb,
        "atr_period": atr_period,
        "trend_ma_lb": trend_ma_lb,
        "slope_lb": slope_lb,
    }


def compute_atr_extension_from_50ma(
    df: pd.DataFrame,
    ma_window: int,
    atr_period: int,
) -> float | None:
    """Distance from moving average expressed in ATR units (absolute)."""
    if ma_window < 1 or atr_period < 1 or len(df) < max(ma_window, atr_period):
        return None
    atr = compute_atr(df, atr_period)
    if atr.iloc[-1] is None or pd.isna(atr.iloc[-1]) or float(atr.iloc[-1]) <= 0:
        return None
    sma = df["Close"].rolling(ma_window, min_periods=ma_window).mean()
    if pd.isna(sma.iloc[-1]):
        return None
    extension = abs(float(df["Close"].iloc[-1]) - float(sma.iloc[-1])) / float(atr.iloc[-1])
    return extension


def align_benchmark_to_symbol(
    symbol_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    *,
    min_bars: int = 1,
) -> pd.DataFrame | None:
    """Reindex benchmark OHLCV to symbol trading dates (forward-fill gaps)."""
    if benchmark_df is None or benchmark_df.empty:
        return None
    bench = normalize_ohlcv(benchmark_df)
    sym_index = symbol_df.index
    aligned = bench.reindex(sym_index, method="ffill").dropna(subset=["Close"])
    if len(aligned) < min_bars:
        return None
    return aligned


def entry_signals_has_auto_data(signals: EntrySignals | None) -> bool:
    """True when at least one auto-computed numeric field is populated."""
    if signals is None:
        return False
    return any(getattr(signals, name) is not None for name in AUTO_COMPUTED_FIELDS)


def compute_vars_series(
    symbol_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    *,
    rs_period: int,
    atr_period: int,
) -> pd.Series | None:
    """
    OHLCV proxy for jfsrev VARS histogram: ATR-normalized momentum vs benchmark.

    vars = (sym_close - sym_close[n]) / sym_ATR - (bench_close - bench_close[n]) / bench_ATR
    """
    if rs_period < 1 or atr_period < 1:
        return None
    min_bars = rs_period + atr_period + 1
    if benchmark_df is None or len(symbol_df) < min_bars:
        return None
    sym = symbol_df
    bench = align_benchmark_to_symbol(sym, benchmark_df, min_bars=min_bars)
    if bench is None:
        return None
    sym_atr = compute_atr(sym, atr_period)
    bench_atr = compute_atr(bench, atr_period)
    sym_close = sym["Close"]
    bench_close = bench["Close"]
    sym_mom = (sym_close - sym_close.shift(rs_period)) / sym_atr
    bench_mom = (bench_close - bench_close.shift(rs_period)) / bench_atr
    series = (sym_mom - bench_mom).replace([np.inf, -np.inf], np.nan).dropna()
    return series if not series.empty else None


def _vars_trend_label(current: float, prior: float, *, flat_threshold: float = 0.05) -> str:
    delta = current - prior
    if abs(delta) <= flat_threshold:
        return "flat"
    return "rising" if delta > 0 else "falling"


def compute_vars_from_ohlcv(
    symbol_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    *,
    rs_period: int,
    atr_period: int,
    trend_lookback: int = 5,
) -> tuple[float | None, str | None, bool | None]:
    """
    Return (latest reading, trend, confirming) from VARS proxy series.

    Confirming strength: positive reading and rising trend (per SKILL VARS rules).
    """
    trend_lb = max(1, trend_lookback)
    series = compute_vars_series(
        symbol_df, benchmark_df, rs_period=rs_period, atr_period=atr_period
    )
    if series is None or len(series) < trend_lb + 1:
        return None, None, None
    current = float(series.iloc[-1])
    prior = float(series.iloc[-(trend_lb + 1)])
    trend = _vars_trend_label(current, prior)
    short_mean = float(series.iloc[-trend_lb:].mean())
    rising = current > prior and current >= short_mean
    if current < 0:
        confirming = False
    elif current > 0 or rising:
        confirming = True
    else:
        confirming = None
    return current, trend, confirming


def format_vars_live_analysis(
    symbol: str,
    signals: EntrySignals,
    *,
    benchmark_symbol: str = "SPY",
    traditional_rs: bool | None = None,
    rvol: float | None = None,
    atr_from_50ma: float | None = None,
    analysis_time: datetime | None = None,
) -> str:
    """Structured VARS report (SKILL output format) from live-computed signals."""
    when = (analysis_time or datetime.now()).strftime("%Y-%m-%d %H:%M")
    if signals.is_vars is True:
        status = "Confirming Strength"
    elif signals.is_vars is False:
        status = "Not Confirming"
    else:
        status = "Mixed"
    reading = signals.vars_reading
    trend = signals.vars_trend or "n/a"
    hist_note = (
        f"proxy histogram {reading:+.2f} ({trend})"
        if reading is not None
        else "histogram unavailable"
    )
    trad_rs = (
        "outperforming"
        if traditional_rs is True
        else "lagging" if traditional_rs is False else "not computed"
    )
    verdict = (
        "VARS is confirming strength — positive volatility-adjusted RS with a rising trend."
        if signals.is_vars is True
        else (
            "VARS is not confirming strength — negative or falling volatility-adjusted RS."
            if signals.is_vars is False
            else "VARS is mixed — insufficient volatility-adjusted RS confirmation."
        )
    )
    risk_bits: list[str] = []
    if atr_from_50ma is not None and atr_from_50ma > 4.0:
        risk_bits.append(f"extended {atr_from_50ma:.1f}x ATR from 50-MA")
    if rvol is not None and rvol < 1.5:
        risk_bits.append(f"low RVOL ({rvol:.2f}x)")
    risk_note = "; ".join(risk_bits) if risk_bits else "none flagged from live metrics"
    bottom = (
        f"VARS confirming strength on {symbol} — prioritize for focus-list upgrade."
        if signals.is_vars is True
        else (
            f"VARS failing to confirm on {symbol} — avoid new longs until histogram turns up."
            if signals.is_vars is False
            else f"VARS mixed on {symbol} — wait for clearer volatility-adjusted RS."
        )
    )
    lines = [
        f"Ticker: {symbol.upper()}",
        f"Analysis Date / Time: {when}",
        f"VARS Status: {status}",
        "",
        "Key Observations",
        f"- Current VARS reading and trend: {hist_note}",
        f"- Histogram behavior: {trend} over lookback (daily OHLCV proxy)",
        f"- Comparison to traditional RS: {trad_rs}",
        "- Alignment with price action and key levels: see RVOL/ADR/ATR auto metrics above",
        "",
        "Strength Confirmation Verdict",
        verdict,
        "",
        "Supporting Context (if relevant)",
        f"- Data source: {VARS_DATA_SOURCE_NOTE} vs {benchmark_symbol}",
        f"- Risk note: {risk_note}",
        "",
        "Bottom Line",
        bottom,
    ]
    return "\n".join(lines)


def analyze_vars_for_symbol(
    symbol: str,
    benchmark_symbol: str = "SPY",
    period: str = "2y",
) -> str | None:
    """Fetch live OHLCV and return formatted VARS analysis for one ticker."""
    sym_df = fetch_ohlcv_history(symbol, period=period)
    if sym_df is None:
        return None
    bench_df = fetch_ohlcv_history(benchmark_symbol, period=period)
    signals = compute_signals_from_ohlcv(sym_df, bench_df)
    if signals.is_vars is None and signals.vars_reading is None:
        return None
    return format_vars_live_analysis(
        symbol,
        signals,
        benchmark_symbol=benchmark_symbol,
        traditional_rs=signals.relative_strength,
        rvol=signals.rvol,
        atr_from_50ma=signals.atr_from_50ma,
    )


def compute_rs_line_ratio_series(
    symbol_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
) -> pd.Series | None:
    """IBD-style RS line: relative price performance vs benchmark (rebased to 1.0 at start)."""
    if benchmark_df is None or len(symbol_df) < 2:
        return None
    bench = align_benchmark_to_symbol(symbol_df, benchmark_df, min_bars=2)
    if bench is None:
        return None
    sym_close = symbol_df["Close"].astype(float)
    bench_close = bench["Close"].astype(float)
    sym_base = float(sym_close.iloc[0])
    bench_base = float(bench_close.iloc[0])
    if sym_base <= 0 or bench_base <= 0:
        return None
    sym_rel = sym_close / sym_base
    bench_rel = bench_close / bench_base
    series = (sym_rel / bench_rel).replace([np.inf, -np.inf], np.nan).dropna()
    return series if not series.empty else None


def compute_rs_line_new_highs_from_ohlcv(
    symbol_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    *,
    lookback: int = 252,
    new_high_tolerance: float = 0.995,
    approaching_floor: float = 0.97,
) -> tuple[bool | None, bool | None, str | None]:
    """
    Return (confirming, leading_price, status_label) for RS line new-high analysis.

    confirming True = at new highs; False = not confirming; None = approaching/mixed.
    """
    series = compute_rs_line_ratio_series(symbol_df, benchmark_df)
    if series is None or len(series) < 3:
        return None, None, None
    lb = max(5, min(lookback, len(series) - 1))
    current = float(series.iloc[-1])
    window = series.iloc[-lb:]
    recent_high = float(window.max())
    if recent_high <= 0:
        return None, None, None
    pct_of_high = current / recent_high
    rising = len(series) >= 6 and current > float(series.iloc[-6])
    at_new_high = pct_of_high >= new_high_tolerance
    approaching = approaching_floor <= pct_of_high < new_high_tolerance and rising
    sym_close = symbol_df["Close"]
    price_lb = max(5, min(lb, len(sym_close) - 1))
    price_at_high = float(sym_close.iloc[-1]) >= float(sym_close.iloc[-price_lb:].max()) * new_high_tolerance
    leading = at_new_high and not price_at_high
    if at_new_high:
        return True, leading, "Confirming Strength"
    if approaching:
        return None, False, "Approaching or Mixed"
    return False, False, "Not Confirming"


def format_rs_line_live_analysis(
    symbol: str,
    signals: EntrySignals,
    *,
    benchmark_symbol: str = "SPY",
    analysis_time: datetime | None = None,
) -> str:
    """Structured RS line report (SKILL output format) from live-computed signals."""
    when = (analysis_time or datetime.now()).strftime("%Y-%m-%d %H:%M")
    status = signals.rs_line_status or (
        "Confirming Strength"
        if signals.rs_line_new_highs is True
        else (
            "Not Confirming"
            if signals.rs_line_new_highs is False
            else "Approaching or Mixed"
        )
    )
    leading = signals.rs_line_leading_price
    leading_note = (
        "RS line leading price (new high before price breakout)"
        if leading
        else (
            "RS line not leading price"
            if leading is False
            else "leading-price status unavailable"
        )
    )
    verdict = (
        "RS line making new highs confirms relative strength and supports setup consideration."
        if signals.rs_line_new_highs is True
        else (
            "RS line is not making new highs — lacks relative strength confirmation for new longs."
            if signals.rs_line_new_highs is False
            else "RS line is approaching recent highs but not yet confirming — stand by for a clear new-high print."
        )
    )
    bottom = (
        f"RS line making new highs{' and leading price' if leading else ''} — strong leadership confirmation for swing longs."
        if signals.rs_line_new_highs is True
        else (
            "RS line failing to make new highs — lacks relative strength confirmation."
            if signals.rs_line_new_highs is False
            else f"RS line on {symbol.upper()} approaching highs — wait for confirming new-high print."
        )
    )
    lines = [
        f"Ticker: {symbol.upper()}",
        f"Analysis Date / Time: {when}",
        f"RS Line New Highs Status: {status}",
        "",
        "Key Observations",
        f"- RS line position vs recent highs: {status}",
        f"- New highs / leading price: {leading_note}",
        "- Alignment with price action: see live OHLCV metrics above",
        f"- Data source: {RS_LINE_DATA_SOURCE_NOTE} vs {benchmark_symbol}",
        "",
        "Strength Confirmation Verdict",
        verdict,
        "",
        "Bottom Line",
        bottom,
    ]
    return "\n".join(lines)


def analyze_rs_line_for_symbol(
    symbol: str,
    benchmark_symbol: str = "SPY",
    period: str = "2y",
) -> str | None:
    """Fetch live OHLCV and return formatted RS line new-highs analysis."""
    sym_df = fetch_ohlcv_history(symbol, period=period)
    if sym_df is None:
        return None
    bench_df = fetch_ohlcv_history(benchmark_symbol, period=period)
    signals = compute_signals_from_ohlcv(sym_df, bench_df)
    if signals.rs_line_new_highs is None and signals.rs_line_status is None:
        return None
    return format_rs_line_live_analysis(symbol, signals, benchmark_symbol=benchmark_symbol)


def compute_lod_check_from_ohlcv(
    df: pd.DataFrame,
    *,
    entry_price: float | None = None,
    atr_period: int = 14,
    max_lod_atr_pct: float = 60.0,
) -> LodCheckResult | None:
    """
    Distance from most recent session LoD to entry/current price as % of ATR(14).

    Violated when distance >= max_lod_atr_pct% of ATR (Jeff Sun hard execution rule).
    """
    sym = normalize_ohlcv(df)
    if len(sym) < atr_period:
        return None
    atr_series = compute_atr(sym, atr_period)
    atr_val = atr_series.iloc[-1]
    if pd.isna(atr_val) or float(atr_val) <= 0:
        return None
    atr_14 = float(atr_val)
    lod_price = float(sym["Low"].iloc[-1])
    if entry_price is not None:
        price_used = float(entry_price)
    else:
        fallback = current_price_from_ohlcv(sym)
        if fallback is None:
            return None
        price_used = fallback
    distance = max(0.0, price_used - lod_price)
    pct_of_atr = (distance / atr_14) * 100.0
    return LodCheckResult(
        lod_price=lod_price,
        price_used=price_used,
        atr_14=atr_14,
        distance=distance,
        pct_of_atr=pct_of_atr,
        max_lod_atr_pct=max_lod_atr_pct,
    )


def format_lod_live_analysis(
    symbol: str,
    check: LodCheckResult,
    *,
    entry_price_is_proposed: bool = False,
    analysis_time: datetime | None = None,
    data_source: str = LOD_DATA_SOURCE_NOTE,
    notes: str | None = None,
    holding_avg_cost: float | None = None,
    holding_shares: float | None = None,
) -> str:
    """Structured LoD distance report per Jeff Sun hard-rule check protocol."""
    when = (analysis_time or datetime.now()).strftime("%Y-%m-%d %H:%M")
    price_label = "proposed entry" if entry_price_is_proposed else "current/last price"
    verdict = (
        f"The {price_label} respects the LoD distance rule — within "
        f"{check.max_lod_atr_pct:.0f}% of ATR; suitable for execution consideration."
        if not check.violated
        else (
            f"The {price_label} violates the LoD distance rule "
            f"({check.pct_of_atr:.1f}% of ATR ≥ {check.max_lod_atr_pct:.0f}%) — "
            "hard rule blocks new entry until price tightens toward LoD."
        )
    )
    base_note = (
        "Daily bar LoD proxy; intraday LoD may differ — confirm on live chart before entry."
    )
    if holding_avg_cost is not None:
        sh = f"{holding_shares:.0f} shares, " if holding_shares else ""
        base_note += (
            f" Open holding ({sh}avg cost ${holding_avg_cost:.2f}); "
            "LoD rule applies to current price for add/trim decisions."
        )
    note_lines = notes or base_note
    lines = [
        f"**Ticker:** {symbol.upper()}",
        f"**Analysis Time:** {when}",
        f"**Data Source:** {data_source}",
        "",
        "**LoD Check**:",
        f"- Most Recent LoD: {check.lod_price:.2f}",
        f"- Price Used for Check: {check.price_used:.2f} ({price_label})",
        f"- ATR(14): {check.atr_14:.2f}",
        (
            f"- Distance from LoD: {check.distance:.2f} "
            f"({check.pct_of_atr:.1f}% of ATR)"
        ),
        f"- **Status**: {check.status_label}",
        "",
        "**Verdict**:",
        verdict,
        "",
        "**Notes** (if any):",
        f"- {note_lines}",
    ]
    return "\n".join(lines)


def current_price_from_ohlcv(df: pd.DataFrame) -> float | None:
    """Last close from OHLCV history (current/last traded price proxy)."""
    sym = normalize_ohlcv(df)
    if sym.empty:
        return None
    return float(sym["Close"].iloc[-1])


def fetch_current_price_for_symbol(symbol: str, *, period: str = "5d") -> float | None:
    """Current/last price via OHLCV close, then yfinance quote fields."""
    sym_df = fetch_ohlcv_history(symbol, period=period)
    if sym_df is not None:
        price = current_price_from_ohlcv(sym_df)
        if price is not None:
            return price
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        for key in ("currentPrice", "regularMarketPrice", "previousClose"):
            val = info.get(key)
            if val is not None:
                return float(val)
    except Exception:
        return None
    return None


def resolve_price_for_check(
    symbol: str,
    *,
    description: str | None = None,
    ohlcv_df: pd.DataFrame | None = None,
    explicit_price: float | None = None,
) -> tuple[float | None, bool]:
    """
    Price for entry-style checks (LoD distance, etc.).

    Priority: explicit_price → parsed proposed entry from description →
    current/last stock price (OHLCV close or live quote).
    Returns (price, is_proposed_entry).
    """
    if explicit_price is not None:
        return explicit_price, True
    if description:
        parsed = extract_entry_price(description)
        if parsed is not None:
            return parsed, True
    if ohlcv_df is not None:
        current = current_price_from_ohlcv(ohlcv_df)
        if current is not None:
            return current, False
    current = fetch_current_price_for_symbol(symbol)
    if current is not None:
        return current, False
    return None, False


def fetch_intraday_ohlcv(
    symbol: str,
    *,
    period: str = "5d",
    interval: str = "15m",
) -> pd.DataFrame | None:
    """Intraday OHLCV for opening-range / ORMA proxy."""
    try:
        import yfinance as yf

        df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def _latest_session_slice(intraday: pd.DataFrame) -> pd.DataFrame:
    """Bars belonging to the most recent session in an intraday frame."""
    if intraday.empty:
        return intraday
    idx = intraday.index
    last_ts = pd.Timestamp(idx[-1])
    last_date = last_ts.date()
    mask = [pd.Timestamp(t).date() == last_date for t in idx]
    return intraday.loc[mask]


def assess_tight_price_action(daily_df: pd.DataFrame) -> str:
    """Yes / Partial / No tight-action label from daily contraction proxy."""
    if compute_vcp_contraction(daily_df) is True:
        return "Yes"
    sym = normalize_ohlcv(daily_df)
    if len(sym) < 15:
        return "No"
    recent = sym.iloc[-5:]
    prior = sym.iloc[-20:-5]
    recent_rng = float(((recent["High"] - recent["Low"]) / recent["Close"]).mean())
    prior_rng = float(((prior["High"] - prior["Low"]) / prior["Close"]).mean())
    if prior_rng > 0 and recent_rng < prior_rng * 0.85:
        return "Partial"
    return "No"


def compute_orma_reclaim(
    intraday_df: pd.DataFrame | None,
    price: float,
    *,
    opening_range_minutes: int = 15,
    bar_minutes: int = 15,
) -> tuple[float | None, bool | None, str]:
    """
    Return (orma_level, reclaimed, opening_range_label).

    reclaimed None when intraday data unavailable.
    """
    label = f"First {opening_range_minutes} minutes"
    if intraday_df is None or intraday_df.empty:
        return None, None, label
    session = _latest_session_slice(intraday_df)
    if session.empty:
        return None, None, label
    n_bars = max(1, opening_range_minutes // bar_minutes)
    or_bars = session.iloc[: min(n_bars, len(session))]
    cols = _column_map(or_bars)
    if "high" not in cols or "low" not in cols:
        return None, None, label
    orh = float(or_bars[cols["high"]].max())
    orl = float(or_bars[cols["low"]].min())
    orma = (orh + orl) / 2.0
    reclaimed = price > orma
    return orma, reclaimed, label


def compute_launch_orma_check(
    symbol: str,
    *,
    daily_df: pd.DataFrame | None = None,
    intraday_df: pd.DataFrame | None = None,
    description: str | None = None,
    explicit_price: float | None = None,
    min_rvol: float = 1.5,
) -> LaunchOrmaCheckResult | None:
    """Compute launch + ORMA checks from OHLCV; fetch data when frames omitted."""
    sym_df = daily_df if daily_df is not None else fetch_ohlcv_history(symbol, period="3mo")
    if sym_df is None:
        return None
    sym = normalize_ohlcv(sym_df)
    if len(sym) < 10:
        return None
    price_used, is_proposed = resolve_price_for_check(
        symbol,
        description=description,
        ohlcv_df=sym_df,
        explicit_price=explicit_price,
    )
    if price_used is None:
        return None

    tight = assess_tight_price_action(sym_df)
    rvol_50 = compute_rvol(sym, lookback=min(50, len(sym) - 1))
    rvol_20 = compute_rvol(sym, lookback=min(20, len(sym) - 1))
    rvol = rvol_50 if rvol_50 is not None else rvol_20

    if tight == "Yes" and rvol is not None and rvol >= 2.0:
        launch_status = "Strong Launch Signal"
        launch_obs = (
            "Clean contraction/tight base with expanding volume — "
            "spring-coil launch conditions aligned."
        )
    elif tight in {"Yes", "Partial"} and rvol is not None and rvol >= min_rvol:
        launch_status = "Moderate"
        launch_obs = (
            f"Tight action is {tight.lower()} with RVOL {rvol:.1f}x — "
            "partial launch confirmation; watch for follow-through."
        )
    else:
        launch_status = "Weak or None"
        rvol_txt = f"{rvol:.1f}x" if rvol is not None else "n/a"
        launch_obs = (
            f"Tight action {tight.lower()} and RVOL {rvol_txt} — "
            "lack full tight + volume launch combo."
        )

    intra = intraday_df if intraday_df is not None else fetch_intraday_ohlcv(symbol)
    orma_level, reclaimed, or_label = compute_orma_reclaim(intra, price_used)
    price_lbl = "proposed entry" if is_proposed else "current/last price"
    if reclaimed is True:
        orma_status = "Reclaimed (price above ORMA)"
        orma_obs = (
            f"{price_lbl.capitalize()} ${price_used:.2f} is above ORMA ${orma_level:.2f} — "
            "opening-range acceptance for longs."
        )
    elif reclaimed is False and orma_level is not None:
        orma_status = "Not Reclaimed (price below ORMA)"
        orma_obs = (
            f"{price_lbl.capitalize()} ${price_used:.2f} is below ORMA ${orma_level:.2f} — "
            "wait for reclaim before entry."
        )
    else:
        orma_status = "Unavailable (intraday OR data limited)"
        orma_obs = (
            "Intraday opening-range data unavailable — confirm ORMA reclaim on live chart."
        )

    launch_ok = launch_status in {"Strong Launch Signal", "Moderate"}
    orma_ok = reclaimed is True
    if launch_ok and orma_ok:
        overall = (
            "Strong Launch Signal with ORMA reclaim — high-quality entry timing alignment."
        )
        entry_rec = "Favorable"
        entry_reason = "Tight + RVOL launch and price above ORMA confirm entry discipline."
    elif launch_ok or orma_ok:
        overall = (
            "One of launch or ORMA confirms — setup is usable but not fully aligned."
        )
        entry_rec = "Neutral"
        entry_reason = (
            "Partial confirmation — size smaller until both launch volume and ORMA reclaim align."
        )
    else:
        overall = "Neither launch nor ORMA confirms — stand aside or wait for better entry."
        entry_rec = "Unfavorable"
        entry_reason = "Weak launch and no ORMA reclaim — poor entry timing."

    notes = (
        "Daily VCP/range proxy for tight action; RVOL vs recent average volume; "
        "ORMA from latest session 15m bars when available."
    )
    if reclaimed is None:
        notes += " Intraday OR limited — verify ORMA on TradingView before entry."

    return LaunchOrmaCheckResult(
        price_used=price_used,
        price_is_proposed=is_proposed,
        tight_label=tight,
        rvol=rvol,
        launch_status=launch_status,
        launch_observation=launch_obs,
        opening_range_label=or_label,
        orma_level=orma_level,
        orma_status=orma_status,
        orma_observation=orma_obs,
        overall_assessment=overall,
        entry_recommendation=entry_rec,
        entry_reason=entry_reason,
        notes=notes,
    )


def format_launch_orma_live_analysis(
    symbol: str,
    check: LaunchOrmaCheckResult,
    *,
    analysis_time: datetime | None = None,
    data_source: str = LAUNCH_ORMA_DATA_SOURCE_NOTE,
) -> str:
    """Structured Launch + ORMA report per Jeff Sun entry protocol."""
    when = (analysis_time or datetime.now()).strftime("%Y-%m-%d %H:%M")
    price_lbl = "Proposed Entry" if check.price_is_proposed else "Current / Proposed Entry"
    rvol_txt = f"{check.rvol:.1f}x" if check.rvol is not None else "n/a"
    orma_txt = f"{check.orma_level:.2f}" if check.orma_level is not None else "n/a"
    lines = [
        f"**Ticker:** {symbol.upper()}",
        f"**Analysis Time:** {when}",
        f"**Data Source:** {data_source}",
        "",
        "**1. Launch Signal Check (Tight + RVOL)**",
        f"- Tight Price Action: {check.tight_label}",
        f"- RVOL: {rvol_txt}",
        f"- **Status**: {check.launch_status}",
        f"- Observation: {check.launch_observation}",
        "",
        "**2. ORMA Reclaim Check**",
        f"- Opening Range Used: {check.opening_range_label}",
        f"- ORMA Level: {orma_txt}",
        f"- {price_lbl}: {check.price_used:.2f}",
        f"- **Status**: {check.orma_status}",
        f"- Observation: {check.orma_observation}",
        "",
        "**Combined Entry Quality**",
        f"- Overall Assessment: {check.overall_assessment}",
        (
            f"- Recommendation for Entry: {check.entry_recommendation} "
            f"({check.entry_reason})"
        ),
        "",
        "**Notes** (if any):",
        f"- {check.notes}",
    ]
    return "\n".join(lines)


def analyze_launch_orma_for_symbol(
    symbol: str,
    *,
    description: str | None = None,
    entry_price: float | None = None,
    min_rvol: float = 1.5,
) -> str | None:
    """Fetch data and return formatted Launch + ORMA analysis."""
    check = compute_launch_orma_check(
        symbol,
        description=description,
        explicit_price=entry_price,
        min_rvol=min_rvol,
    )
    if check is None:
        return None
    return format_launch_orma_live_analysis(symbol, check)


def enrich_market_signals_launch_orma(
    symbol: str,
    signals: EntrySignals | None,
    *,
    description: str | None = None,
    min_rvol: float = 1.5,
) -> EntrySignals | None:
    """Set launched / orma_reclaim on market signals when not already populated."""
    check = compute_launch_orma_check(
        symbol, description=description, min_rvol=min_rvol
    )
    if check is None:
        return signals
    base = signals or EntrySignals()
    updates: dict[str, Any] = {}
    if base.launched is None:
        updates["launched"] = check.launched_pass
    if base.orma_reclaim is None:
        reclaimed = check.orma_reclaimed
        if reclaimed is not None:
            updates["orma_reclaim"] = reclaimed
    if not updates:
        return signals
    return replace(base, **updates)


def analyze_lod_for_symbol(
    symbol: str,
    *,
    entry_price: float | None = None,
    description: str | None = None,
    period: str = "3mo",
    max_lod_atr_pct: float = 60.0,
    holding_avg_cost: float | None = None,
    holding_shares: float | None = None,
) -> str | None:
    """Fetch OHLCV and return formatted LoD distance hard-rule analysis."""
    sym_df = fetch_ohlcv_history(symbol, period=period)
    if sym_df is None:
        return None
    price_used, is_proposed = resolve_price_for_check(
        symbol,
        description=description,
        ohlcv_df=sym_df,
        explicit_price=entry_price,
    )
    if price_used is None:
        return None
    check = compute_lod_check_from_ohlcv(
        sym_df, entry_price=price_used, max_lod_atr_pct=max_lod_atr_pct
    )
    if check is None:
        return None
    return format_lod_live_analysis(
        symbol,
        check,
        entry_price_is_proposed=is_proposed,
        holding_avg_cost=holding_avg_cost,
        holding_shares=holding_shares,
    )


def compute_relative_strength_vs_benchmark(
    symbol_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    lookback: int = 63,
) -> bool | None:
    """True when symbol return over `lookback` bars exceeds benchmark return."""
    if benchmark_df is None or len(symbol_df) < lookback + 1:
        return None
    bench = align_benchmark_to_symbol(symbol_df, benchmark_df, min_bars=lookback + 1)
    if bench is None:
        return None
    sym_close = symbol_df["Close"]
    bench_close = bench["Close"]
    start_idx = -(lookback + 1)
    sym_ret = float(sym_close.iloc[-1]) / float(sym_close.iloc[start_idx]) - 1.0
    bench_ret = float(bench_close.iloc[-1]) / float(bench_close.iloc[start_idx]) - 1.0
    return sym_ret > bench_ret


def compute_vcp_contraction(
    df: pd.DataFrame,
    lookback: int = 60,
    segments: int = 3,
    contraction_ratio: float = 0.85,
) -> bool | None:
    """True when recent daily ranges tighten in successive segments (VCP proxy)."""
    if len(df) < 7:
        return None
    n = min(lookback, len(df))
    window = df.iloc[-n:]
    use_segments = segments if n >= 15 else 2
    seg_size = max(2, n // use_segments)
    if seg_size * use_segments > n:
        seg_size = n // use_segments
    if seg_size < 2:
        return None
    range_pcts: list[float] = []
    for i in range(use_segments):
        start = i * seg_size
        end = (i + 1) * seg_size if i < use_segments - 1 else n
        chunk = window.iloc[start:end]
        if len(chunk) < 2:
            return None
        range_pcts.append(
            float(((chunk["High"] - chunk["Low"]) / chunk["Close"] * 100).mean())
        )
    if len(range_pcts) < 2 or range_pcts[0] <= 0:
        return None
    tightening = all(range_pcts[i] >= range_pcts[i + 1] for i in range(len(range_pcts) - 1))
    material = range_pcts[-1] < range_pcts[0] * contraction_ratio
    return tightening and material


def compute_avg_dollar_volume_m(df: pd.DataFrame, lookback: int = 20) -> float | None:
    """Average daily dollar volume in millions (close × volume)."""
    if len(df) < lookback:
        return None
    window = df.iloc[-lookback:]
    dollar_vol = window["Close"] * window["Volume"]
    avg = float(dollar_vol.mean())
    if avg <= 0:
        return None
    return avg / 1e6


def fetch_avg_dollar_volume_m_from_info(symbol: str) -> float | None:
    """Supplemental liquidity from yfinance Ticker.info (avg volume × price)."""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        avg_vol = info.get("averageVolume") or info.get("averageVolume10days")
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        if avg_vol and price:
            return float(avg_vol) * float(price) / 1e6
    except Exception:
        return None
    return None


def website_process_notes(
    market_signals: EntrySignals | None,
    text_signals: EntrySignals | None = None,
) -> list[str]:
    """Coach notes from Jeff Sun process routine (focus list / screening context)."""
    if market_signals is None:
        return []
    text = text_signals or EntrySignals()
    notes: list[str] = []
    if text.is_vars is None and market_signals.is_vars is True:
        notes.append(
            "VARS live: volatility-adjusted RS confirming — "
            "focus-list upgrade candidate per Jeff Sun routine"
        )
    elif text.is_vars is None and market_signals.is_vars is False:
        notes.append(
            "VARS gate: volatility-adjusted RS not confirming — wait for positive, "
            "rising histogram before focus-list upgrade"
        )
    if text.rs_line_new_highs is None and market_signals.rs_line_new_highs is True:
        lead = (
            " (leading price)"
            if market_signals.rs_line_leading_price
            else ""
        )
        notes.append(
            f"RS line live: making new highs{lead} — relative strength first filter passed"
        )
    elif text.rs_line_new_highs is None and market_signals.rs_line_new_highs is False:
        notes.append(
            "RS line gate: not making new highs — lacks leadership confirmation"
        )
    elif (
        text.rs_line_new_highs is None
        and market_signals.rs_line_new_highs is None
        and market_signals.rs_line_status == "Approaching or Mixed"
    ):
        notes.append(
            "RS line watch: approaching recent highs — wait for confirming new-high print"
        )
    if text.vcp is None:
        if market_signals.vcp is True:
            notes.append(
                "Process (watchlist → focus): VCP-style contraction detected — "
                "upgrade candidate per Jeff Sun routine"
            )
        elif market_signals.vcp is False:
            notes.append(
                "Process gate: no VCP contraction — avoid loose price action before "
                "focus-list upgrade"
            )
    if text.avg_dollar_volume_m is None and market_signals.avg_dollar_volume_m is not None:
        meets = market_signals.avg_dollar_volume_m >= LIQUIDITY_MIN_AVG_DOLLAR_VOLUME_M
        notes.append(
            f"Screener liquidity: ${market_signals.avg_dollar_volume_m:.1f}M avg daily $ volume — "
            f"{'meets' if meets else 'below'} ${LIQUIDITY_MIN_AVG_DOLLAR_VOLUME_M:.0f}M "
            "swing threshold (Finviz/TradingView workflow)"
        )
    return notes


def compute_trade_against_declining_200ma(
    df: pd.DataFrame,
    ma_window: int,
    slope_lookback: int,
) -> bool | None:
    """True when price is below a declining long MA (hard-rule violation condition)."""
    if ma_window < 1 or slope_lookback < 1 or len(df) < ma_window + slope_lookback:
        return None
    close = df["Close"]
    ma = close.rolling(ma_window, min_periods=ma_window).mean()
    if pd.isna(ma.iloc[-1]) or pd.isna(ma.iloc[-(slope_lookback + 1)]):
        return None
    declining = float(ma.iloc[-1]) < float(ma.iloc[-(slope_lookback + 1)])
    below = float(close.iloc[-1]) < float(ma.iloc[-1])
    return declining and below


def compute_signals_from_ohlcv(
    symbol_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None = None,
    *,
    rvol_lookback: int = 20,
    adr_lookback: int = 20,
    rs_lookback: int = 63,
    atr_ma_lookback: int = 50,
    atr_period: int = 14,
    trend_ma_lookback: int = 200,
    slope_lookback: int = 20,
) -> EntrySignals:
    """Derive auto-computable EntrySignals from symbol (+ optional benchmark) OHLCV."""
    sym = normalize_ohlcv(symbol_df)
    bench_raw = normalize_ohlcv(benchmark_df) if benchmark_df is not None else None
    n = len(sym)
    windows = _adaptive_windows(
        n,
        rvol_lookback=rvol_lookback,
        adr_lookback=adr_lookback,
        rs_lookback=rs_lookback,
        atr_ma_lookback=atr_ma_lookback,
        atr_period_default=atr_period,
        trend_ma_lookback=trend_ma_lookback,
        slope_lookback_default=slope_lookback,
    )
    if windows is None:
        return EntrySignals()

    vcp_lb = min(60, n)
    liq_lb = min(20, n)
    rs_cap = max(1, (n - 2) // 2)
    vars_rs = (
        max(1, min(windows["rs_lb"], rs_cap))
        if windows["rs_lb"]
        else max(1, min(n // 3, rs_cap))
    )
    vars_atr = max(1, min(windows["atr_period"], n - vars_rs - 1))
    if vars_rs + vars_atr + 1 > n:
        vars_rs = max(1, (n - 2) // 2)
        vars_atr = max(1, n - vars_rs - 1)
    vars_trend_lb = max(1, min(5, max(1, n // 5)))
    vars_reading, vars_trend, is_vars = compute_vars_from_ohlcv(
        sym,
        bench_raw,
        rs_period=vars_rs,
        atr_period=vars_atr,
        trend_lookback=vars_trend_lb,
    )
    rs_lb = max(5, min(252, n - 1))
    rs_line_new_highs, rs_line_leading, rs_line_status = compute_rs_line_new_highs_from_ohlcv(
        sym, bench_raw, lookback=rs_lb
    )
    lod_check = compute_lod_check_from_ohlcv(sym, atr_period=windows["atr_period"])
    lod_atr_pct = lod_check.pct_of_atr if lod_check is not None else None

    return EntrySignals(
        is_vars=is_vars,
        vars_reading=vars_reading,
        vars_trend=vars_trend,
        rs_line_new_highs=rs_line_new_highs,
        rs_line_leading_price=rs_line_leading,
        rs_line_status=rs_line_status,
        rvol=compute_rvol(sym, windows["rvol_lb"]) if windows["rvol_lb"] else None,
        adr_pct=compute_adr_pct(sym, windows["adr_lb"]) if windows["adr_lb"] else None,
        atr_from_50ma=compute_atr_extension_from_50ma(
            sym, windows["atr_ma_lb"], windows["atr_period"]
        ),
        relative_strength=(
            compute_relative_strength_vs_benchmark(sym, bench_raw, windows["rs_lb"])
            if windows["rs_lb"]
            else None
        ),
        trade_against_declining_200ma=compute_trade_against_declining_200ma(
            sym, windows["trend_ma_lb"], windows["slope_lb"]
        ),
        vcp=compute_vcp_contraction(sym, lookback=vcp_lb),
        avg_dollar_volume_m=compute_avg_dollar_volume_m(sym, lookback=liq_lb),
        lod_atr_pct=lod_atr_pct,
    )


def merge_entry_signals(
    text_signals: EntrySignals,
    market_signals: EntrySignals | None,
) -> EntrySignals:
    """Merge text-parsed signals with auto-computed; explicit text values win."""
    if market_signals is None:
        return text_signals
    merged: dict[str, Any] = {}
    for f in fields(EntrySignals):
        text_val = getattr(text_signals, f.name)
        market_val = getattr(market_signals, f.name)
        merged[f.name] = text_val if text_val is not None else market_val
    return EntrySignals(**merged)


def auto_field_criterion_labels(rules: JeffSunRules) -> dict[str, str]:
    """Map AUTO_COMPUTED_FIELDS names to score_entry criterion labels."""
    return {
        "is_vars": "VARs confirming strength",
        "rs_line_new_highs": "RS line making new highs",
        "rvol": f"RVOL >= {rules.min_rvol}x",
        "adr_pct": f"ADR% >= {rules.min_adr_pct:.0f}%",
        "atr_from_50ma": f"ATR < {rules.max_atr_from_50ma}x from 50-MA",
        "relative_strength": "Relative Strength vs market/sector",
        "trade_against_declining_200ma": "200-MA trend (no trade against declining)",
        "vcp": "VCP / Tight Price Action",
        "avg_dollar_volume_m": LIQUIDITY_CRITERION,
    }


def auto_criterion_values(signals: EntrySignals, rules: JeffSunRules) -> dict[str, str]:
    """Map score_entry auto criterion labels to compact computed value strings."""
    values: dict[str, str] = {}
    if signals.is_vars is not None:
        label = "confirming strength" if signals.is_vars else "not confirming"
        if signals.vars_reading is not None:
            trend = signals.vars_trend or "n/a"
            label = f"{label} ({signals.vars_reading:+.2f}, {trend})"
        values["VARs confirming strength"] = label
    if signals.rs_line_new_highs is not None:
        detail = "new highs"
        if signals.rs_line_leading_price:
            detail += ", leading price"
        if not signals.rs_line_new_highs:
            detail = "not at new highs"
        values["RS line making new highs"] = detail
    elif signals.rs_line_status == "Approaching or Mixed":
        values["RS line making new highs"] = "approaching recent highs"
    if signals.rvol is not None:
        values[f"RVOL >= {rules.min_rvol}x"] = f"{signals.rvol:.2f}x"
    if signals.adr_pct is not None:
        values[f"ADR% >= {rules.min_adr_pct:.0f}%"] = f"{signals.adr_pct:.2f}%"
    if signals.atr_from_50ma is not None:
        values[f"ATR < {rules.max_atr_from_50ma}x from 50-MA"] = (
            f"{signals.atr_from_50ma:.2f}x"
        )
    if signals.relative_strength is not None:
        values["Relative Strength vs market/sector"] = (
            "outperforming" if signals.relative_strength else "lagging"
        )
    if signals.trade_against_declining_200ma is not None:
        values["200-MA trend (no trade against declining)"] = (
            "against declining 200-MA"
            if signals.trade_against_declining_200ma
            else "not against declining 200-MA"
        )
    if signals.vcp is not None:
        values["VCP / Tight Price Action"] = (
            "contraction detected" if signals.vcp else "loose/expanded"
        )
    if signals.avg_dollar_volume_m is not None:
        values[LIQUIDITY_CRITERION] = f"${signals.avg_dollar_volume_m:.1f}M"
    return values


def data_derived_criterion_values(
    market_signals: EntrySignals | None,
    text_signals: EntrySignals,
    rules: JeffSunRules,
) -> dict[str, str]:
    """Criterion values to emit with (data-derived) — OHLCV only, excluding text overrides."""
    if market_signals is None or not entry_signals_has_auto_data(market_signals):
        return {}
    market_values = auto_criterion_values(market_signals, rules)
    labels = auto_field_criterion_labels(rules)
    derived: dict[str, str] = {}
    for field in AUTO_COMPUTED_FIELDS:
        if getattr(text_signals, field) is not None:
            continue
        label = labels[field]
        if label not in market_values:
            continue
        market_val = getattr(market_signals, field)
        if market_val is not None:
            derived[label] = market_values[label]
        elif field == "rs_line_new_highs" and market_signals.rs_line_status:
            derived[label] = market_values[label]
    return derived


def auto_signal_summary(
    signals: EntrySignals,
    text_signals: EntrySignals | None = None,
) -> list[str]:
    """Human-readable data-derived metric lines for coach output (non-overridden fields only)."""
    text = text_signals or EntrySignals()
    lines: list[str] = []
    if text.is_vars is None and signals.is_vars is not None:
        trend = signals.vars_trend or "n/a"
        reading = (
            f"{signals.vars_reading:+.2f}, {trend}"
            if signals.vars_reading is not None
            else trend
        )
        state = "confirming" if signals.is_vars else "not confirming"
        lines.append(f"VARS (data-derived): {state} ({reading})")
    if text.rs_line_new_highs is None and (
        signals.rs_line_new_highs is not None or signals.rs_line_status
    ):
        if signals.rs_line_new_highs is True:
            lead = ", leading price" if signals.rs_line_leading_price else ""
            lines.append(f"RS line (data-derived): making new highs{lead}")
        elif signals.rs_line_new_highs is False:
            lines.append("RS line (data-derived): not making new highs")
        elif signals.rs_line_status:
            lines.append(f"RS line (data-derived): {signals.rs_line_status.lower()}")
    if text.rvol is None and signals.rvol is not None:
        lines.append(f"RVOL (data-derived): {signals.rvol:.2f}x")
    if text.adr_pct is None and signals.adr_pct is not None:
        lines.append(f"ADR% (data-derived): {signals.adr_pct:.2f}%")
    if text.atr_from_50ma is None and signals.atr_from_50ma is not None:
        lines.append(f"ATR from 50-MA (data-derived): {signals.atr_from_50ma:.2f}x")
    if text.relative_strength is None and signals.relative_strength is not None:
        lines.append(
            "Relative strength vs SPY (data-derived): "
            + ("outperforming" if signals.relative_strength else "lagging")
        )
    if (
        text.trade_against_declining_200ma is None
        and signals.trade_against_declining_200ma is not None
    ):
        lines.append(
            "200-MA context (data-derived): "
            + (
                "trading against declining 200-MA"
                if signals.trade_against_declining_200ma
                else "not against declining 200-MA"
            )
        )
    if text.vcp is None and signals.vcp is not None:
        lines.append(
            "VCP contraction (data-derived): "
            + ("detected" if signals.vcp else "not detected")
        )
    if text.avg_dollar_volume_m is None and signals.avg_dollar_volume_m is not None:
        lines.append(
            f"Avg $ volume (data-derived): ${signals.avg_dollar_volume_m:.1f}M"
        )
    if text.lod_atr_pct is None and signals.lod_atr_pct is not None:
        state = "acceptable" if signals.lod_atr_pct < 60.0 else "violated (hard rule)"
        lines.append(
            f"LoD distance (data-derived): {signals.lod_atr_pct:.1f}% of ATR — {state}"
        )
    return lines


def fetch_ohlcv_history(symbol: str, period: str = "1y") -> pd.DataFrame | None:
    """Thin yfinance fetcher; returns None on failure."""
    try:
        import yfinance as yf

        df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def build_auto_signals_for_symbol(
    symbol: str,
    benchmark_symbol: str = "SPY",
    period: str = "2y",
) -> EntrySignals | None:
    """Fetch history and compute auto EntrySignals; partial fields OK on short history."""
    sym_df = fetch_ohlcv_history(symbol, period=period)
    if sym_df is None:
        return None
    sym = normalize_ohlcv(sym_df)
    if len(sym) < 5:
        return None
    bench_df = fetch_ohlcv_history(benchmark_symbol, period=period)
    signals = compute_signals_from_ohlcv(sym_df, bench_df)
    if signals.avg_dollar_volume_m is None:
        supplemental = fetch_avg_dollar_volume_m_from_info(symbol)
        if supplemental is not None:
            signals = replace(signals, avg_dollar_volume_m=supplemental)
    if not entry_signals_has_auto_data(signals):
        return None
    return signals