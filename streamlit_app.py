"""
stockevents-portfolio-dashboard
- Upload StockEvents transaction history and view current holdings
- Run the Jeff Sun trading coach on one position or all at once (swing horizon)
- Coach analysis shown in a readable, structured format beside each row
- Live prices via Moomoo OpenD (preferred) or yfinance (fallback)

Run with: python -m streamlit run streamlit_app.py
(Windows: double-click run_dashboard.bat or use the same command in PowerShell)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

_ROOT = Path(__file__).resolve().parent
_TRADING_PORTFOLIO = _ROOT / "trading_portfolio"
if str(_TRADING_PORTFOLIO) not in sys.path:
    sys.path.insert(0, str(_TRADING_PORTFOLIO))

from coach_outcome_formatter import build_coach_outcome_display, format_coach_expander_label  # noqa: E402
from coach_outcome_ui import render_coach_outcome  # noqa: E402
from positions_dashboard import (  # noqa: E402
    current_positions_from_holdings_df,
    current_positions_to_dataframe,
    derive_current_positions_from_trades,
    run_coach_for_position,
    run_coach_for_positions,
)


SAMPLE_STOCK_EVENTS_CSV = _TRADING_PORTFOLIO / "stock_events_transactions_2026-06-23.csv"

st.set_page_config(page_title="stockevents-portfolio-dashboard", layout="wide")

# ============================================================
# MOOMOO HELPERS (defined before use; moomoo-api >= 9.x API)
# ============================================================
def _silence_moomoo_console_logs():
    """Best-effort log quieting — newer moomoo-api removed set_log_level/FTLogLevel."""
    try:
        import logging
        import moomoo as ft

        if hasattr(ft, "set_log_level") and hasattr(ft, "FTLogLevel"):
            ft.set_log_level(ft.FTLogLevel.ERROR)
            return
        if hasattr(ft, "FTLog"):
            log = ft.FTLog()
            log._console_level = logging.ERROR
            if hasattr(log, "consoleHandler"):
                log.consoleHandler.setLevel(logging.ERROR)
    except Exception:
        pass


def get_prices_from_moomoo(tickers):
    """Fetch current prices via Moomoo OpenD."""
    prices = {}
    quote_ctx = None
    try:
        import moomoo as ft

        _silence_moomoo_console_logs()
        quote_ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
        moomoo_tickers = [f"US.{t}" for t in tickers]

        # API rate limit: up to 200 symbols per get_market_snapshot call.
        for i in range(0, len(moomoo_tickers), 200):
            batch = moomoo_tickers[i : i + 200]
            ret, data = quote_ctx.get_market_snapshot(batch)
            if ret != ft.RET_OK:
                raise RuntimeError(data if isinstance(data, str) else f"get_market_snapshot failed (ret={ret})")
            if data is None or data.empty:
                continue
            for _, row in data.iterrows():
                code = str(row.get("code", ""))
                if code.startswith("US."):
                    ticker = code.replace("US.", "")
                    price = row.get("last_price") or row.get("cur_price") or row.get("close_price")
                    if price and float(price) > 0:
                        prices[ticker] = round(float(price), 2)
    except Exception as e:
        st.warning(f"Moomoo prices failed: {e}. Using yfinance fallback.")
    finally:
        if quote_ctx is not None:
            quote_ctx.close()
    return prices


def get_positions_from_moomoo():
    """Fetch live positions from Moomoo account."""
    positions = []
    trade_ctx = None
    try:
        import moomoo as ft

        _silence_moomoo_console_logs()
        trade_ctx = ft.OpenSecTradeContext(
            filter_trdmarket=ft.TrdMarket.US,
            host="127.0.0.1",
            port=11111,
            security_firm=ft.SecurityFirm.FUTUINC,
        )
        ret, data = trade_ctx.position_list_query()
        if ret != ft.RET_OK:
            raise RuntimeError(data if isinstance(data, str) else f"position_list_query failed (ret={ret})")
        if data is not None and not data.empty:
            for _, row in data.iterrows():
                code = str(row.get("code", ""))
                if code.startswith("US."):
                    ticker = code.replace("US.", "")
                    qty = row.get("qty") or row.get("position_qty") or 0
                    market_val = row.get("market_val") or row.get("market_value") or 0
                    cost_price = row.get("cost_price") or row.get("avg_cost") or 0
                    positions.append(
                        {
                            "Ticker": ticker,
                            "Net Shares": float(qty) if qty else 0,
                            "Live Price": None,
                            "Live Market Value": float(market_val) if market_val else 0,
                            "Moomoo Cost Price": float(cost_price) if cost_price else None,
                            "Source": "Moomoo Live",
                        }
                    )
    except Exception as e:
        st.error(f"Failed to pull positions from Moomoo: {e}")
        st.info("Make sure OpenD is running and you are logged into your real account.")
    finally:
        if trade_ctx is not None:
            trade_ctx.close()
    return positions


@st.cache_data(ttl=300)
def get_live_prices(tickers, use_moomoo=False):
    prices = {}
    if use_moomoo:
        prices = get_prices_from_moomoo(tickers)
        missing = [t for t in tickers if t not in prices or prices.get(t) is None]
        if missing:
            yf_prices = get_yfinance_prices(missing)
            prices.update(yf_prices)
    else:
        prices = get_yfinance_prices(tickers)
    return prices


def get_yfinance_prices(tickers):
    prices = {}
    for ticker in tickers:
        try:
            data = yf.Ticker(ticker)
            price = data.info.get("regularMarketPrice") or data.info.get("currentPrice")
            if price is None:
                hist = data.history(period="1d")
                price = hist["Close"].iloc[-1] if not hist.empty else None
            prices[ticker] = round(float(price), 2) if price else None
        except Exception:
            prices[ticker] = None
    return prices


st.title("📊 StockEvents Portfolio Dashboard")
st.caption("StockEvents History + Live Prices from Moomoo (or yfinance fallback)")

# ============================================================
# SIDEBAR - Data Sources & Settings
# ============================================================
st.sidebar.header("Data Sources")

csv_file = st.sidebar.file_uploader(
    "Upload StockEvents transaction history CSV",
    type=["csv"],
    help="Export your latest StockEvents transactions and upload here. "
    "Falls back to bundled sample data when none uploaded.",
)

use_moomoo_prices = st.sidebar.checkbox(
    "Use Moomoo for live prices (requires OpenD)",
    value=False,
    help="Pull current prices directly from your Moomoo account via OpenD."
)

use_moomoo_positions = st.sidebar.checkbox(
    "Pull live positions from Moomoo (requires OpenD)",
    value=False,
    help="Use actual positions from your Moomoo account instead of calculated net shares from CSV."
)

refresh_prices = st.sidebar.button("🔄 Refresh Live Prices")

# ============================================================
# LOAD & PROCESS TRANSACTIONS (StockEvents)
# ============================================================
@st.cache_data
def load_current_positions_from_csv(csv_bytes: bytes | None, use_sample: bool) -> pd.DataFrame:
    """Derive dashboard holdings from StockEvents history via load_trades_csv path."""
    if csv_bytes is not None:
        df = pd.read_csv(pd.io.common.BytesIO(csv_bytes))
    elif use_sample and SAMPLE_STOCK_EVENTS_CSV.exists():
        df = pd.read_csv(SAMPLE_STOCK_EVENTS_CSV)
    else:
        return pd.DataFrame()

    positions = derive_current_positions_from_trades(df)
    return current_positions_to_dataframe(positions)


_csv_bytes = csv_file.getvalue() if csv_file is not None else None
holdings_df = load_current_positions_from_csv(_csv_bytes, use_sample=csv_file is None)

if holdings_df.empty:
    st.error("No CSV uploaded and sample StockEvents file not found.")
    st.stop()

# If user wants live positions from Moomoo, override with real account data
if use_moomoo_positions:
    moomoo_pos = get_positions_from_moomoo()
    if moomoo_pos:
        moomoo_df = pd.DataFrame(moomoo_pos)
        # Merge with historical cost basis where possible
        if not holdings_df.empty:
            moomoo_df = moomoo_df.merge(
                holdings_df[['Ticker', 'Avg Cost (approx)', 'Total Invested (approx)']],
                on='Ticker', how='left'
            )
        holdings_df = moomoo_df
        st.success(f"Loaded {len(holdings_df)} live positions from Moomoo account.")
    else:
        st.warning("Could not load positions from Moomoo. Using StockEvents data instead.")

if holdings_df.empty:
    st.stop()

# Coach dashboard always reflects the active holdings table (CSV or Moomoo).
current_positions = current_positions_from_holdings_df(holdings_df)

tickers = holdings_df["Ticker"].tolist()

if refresh_prices:
    st.cache_data.clear()

live_prices = get_live_prices(tickers, use_moomoo=use_moomoo_prices)
holdings_df['Live Price'] = holdings_df['Ticker'].map(live_prices)

# If we pulled positions from Moomoo, fill Live Price if missing
if 'Live Price' in holdings_df.columns:
    missing_price = holdings_df['Live Price'].isna()
    if missing_price.any() and live_prices:
        holdings_df.loc[missing_price, 'Live Price'] = holdings_df.loc[missing_price, 'Ticker'].map(live_prices)

# Calculate live market value
holdings_df['Live Market Value'] = holdings_df['Net Shares'] * holdings_df['Live Price'].fillna(0)
holdings_df['Unrealized P&L (approx)'] = holdings_df['Live Market Value'] - holdings_df['Total Invested (approx)']

# ============================================================
# MOOMOO API SECTION (Optional - for live account positions)
# ============================================================
moomoo_positions = None

if use_moomoo_prices:
    st.sidebar.success("Moomoo price source enabled. OpenD must be running and logged in.")
    st.sidebar.info("If prices fail, it will automatically fall back to yfinance.")

# ============================================================
# MAIN DASHBOARD
# ============================================================

# Summary Metrics
col1, col2, col3, col4 = st.columns(4)

total_invested = holdings_df['Total Invested (approx)'].sum()
total_market_value = holdings_df['Live Market Value'].sum()
total_unrealized = holdings_df['Unrealized P&L (approx)'].sum()
num_positions = len(holdings_df)

col1.metric("Est. Total Invested", f"${total_invested:,.0f}")
col2.metric("Live Market Value", f"${total_market_value:,.0f}")
col3.metric("Unrealized P&L", f"${total_unrealized:,.0f}", 
            delta=f"{(total_unrealized/total_invested*100):.1f}%" if total_invested > 0 else "")
col4.metric("Open Positions", num_positions)

st.divider()

# ============================================================
# CURRENT POSITIONS + TRADING COACH
# ============================================================
st.subheader("📋 Current positions & trading coach")
st.caption(
    "Run the Jeff Sun trading coach on one position or all at once. "
    "Results appear beside each row with pass/fail indicators and action items."
)

if "coach_results" not in st.session_state:
    st.session_state.coach_results = {}
if "coach_analysis_expanded" not in st.session_state:
    st.session_state.coach_analysis_expanded = False

coach_header = st.columns([1.2, 1, 1.2, 1.5, 4])
coach_header[0].markdown("**Symbol**")
coach_header[1].markdown("**Shares**")
coach_header[2].markdown("**Avg Cost**")
coach_header[3].markdown("**Run coach**")
coach_header[4].markdown("**Coach analysis**")

def _unrealized_pnl_map(df: pd.DataFrame) -> dict[str, float]:
    if "Unrealized P&L (approx)" not in df.columns:
        return {}
    out: dict[str, float] = {}
    for _, row in df.iterrows():
        pnl = row.get("Unrealized P&L (approx)")
        if pnl is not None and pd.notna(pnl):
            out[str(row["Ticker"])] = float(pnl)
    return out


_pnl_by_symbol = _unrealized_pnl_map(holdings_df)

run_all_col, expand_col, _ = st.columns([2, 2, 4])
if run_all_col.button("Run coach on all positions", type="primary"):
    st.session_state.coach_results = run_coach_for_positions(
        current_positions, unrealized_pnl_by_symbol=_pnl_by_symbol
    )
    st.session_state.coach_analysis_expanded = False
if expand_col.button(
    "Collapse all coach analysis"
    if st.session_state.coach_analysis_expanded
    else "Expand all coach analysis",
):
    st.session_state.coach_analysis_expanded = not st.session_state.coach_analysis_expanded
    st.rerun()

for pos in sorted(current_positions, key=lambda p: p.symbol):
    live_row = holdings_df[holdings_df["Ticker"] == pos.symbol]
    live_price = (
        float(live_row["Live Price"].iloc[0])
        if not live_row.empty and pd.notna(live_row["Live Price"].iloc[0])
        else None
    )
    row = st.columns([1.2, 1, 1.2, 1.5, 4])
    row[0].write(f"**{pos.symbol}**")
    row[1].write(f"{pos.net_shares:,.0f}")
    row[2].write(f"${pos.avg_cost:,.2f}")
    if live_price is not None:
        row[2].caption(f"Live ${live_price:,.2f}")

    if row[3].button("Run coach", key=f"run_coach_{pos.symbol}"):
        st.session_state.coach_results[pos.symbol] = run_coach_for_position(
            pos, unrealized_pnl=_pnl_by_symbol.get(pos.symbol)
        )

    outcome = st.session_state.coach_results.get(pos.symbol)
    if outcome:
        coach_display = build_coach_outcome_display(outcome)
        with row[4].expander(
            format_coach_expander_label(pos.symbol, coach_display),
            expanded=st.session_state.coach_analysis_expanded,
        ):
            render_coach_outcome(outcome)
    else:
        row[4].caption("No analysis yet — run coach for this symbol or use **Run coach on all positions**.")

st.divider()

# Holdings Table (live values)
st.subheader("📋 Merged Holdings (History + Live)")

display_cols = [
    "Ticker",
    "Net Shares",
    "Avg Cost (approx)",
    "Total Invested (approx)",
    "Live Price",
    "Live Market Value",
    "Unrealized P&L (approx)",
]
display_df = holdings_df[[c for c in display_cols if c in holdings_df.columns]].copy()
display_df = display_df.sort_values(
    "Live Market Value" if "Live Market Value" in display_df.columns else "Ticker",
    ascending=False,
)

st.dataframe(
    display_df.style.format(
        {
            "Avg Cost (approx)": "${:,.2f}",
            "Total Invested (approx)": "${:,.0f}",
            "Live Price": "${:,.2f}",
            "Live Market Value": "${:,.0f}",
            "Unrealized P&L (approx)": "${:,.0f}",
        }
    ).background_gradient(subset=["Unrealized P&L (approx)"], cmap="RdYlGn"),
    use_container_width=True,
    hide_index=True,
)

# Theme Allocation Pie (using previous grouping)
st.subheader("📈 Allocation by Theme")

# Simple theme mapping (expand as needed)
theme_map = {
    'AAPL': 'AI / Big Tech', 'MSFT': 'AI / Big Tech', 'NVDA': 'AI / Semiconductor',
    'AVGO': 'AI / Semiconductor', 'TSM': 'Semiconductor', 'SOXX': 'Semi ETF',
    'TSLA': 'EV / Growth', 'HOOD': 'Fintech / Growth',
    'MSTR': 'Bitcoin Proxy',
    'RXRX': 'AI Biotech / Spec', 'ACHR': 'eVTOL / Spec', 'RGTI': 'Quantum / Spec',
    'QBTS': 'Quantum / Spec', 'RUN': 'Solar / Spec', 'MP': 'Rare Earth / Spec',
    'GEVO': 'Biofuel / Spec', 'AGNC': 'REIT / Dividend', 'NFLX': 'Streaming / Other',
    'SPCX': 'Custom / Space', 'ULTY': 'Spec / Other', 'DRAM': 'Spec / Other',
    'CAVA': 'Growth / Consumer', 'CLS': 'Tech Supply', 'CRWV': 'Spec / Other',
    'ARM': 'AI / Semiconductor', 'MU': 'Semiconductor', 'SNDK': 'Legacy'
}

holdings_df['Theme'] = holdings_df['Ticker'].map(theme_map).fillna('Other')

theme_value = holdings_df.groupby('Theme')['Live Market Value'].sum().reset_index()
fig = px.pie(theme_value, values='Live Market Value', names='Theme', 
             title="Portfolio Allocation by Theme (Live Market Value)")
st.plotly_chart(fig, use_container_width=True)

# Recommendations
st.subheader("💡 Quick Recommendations")

st.markdown("""
**Based on current merged data:**
- Strong AI/Semiconductor concentration — good secular exposure but watch for sector rotation.
- Several high-beta speculative positions (RXRX, ACHR, quantum names) — size risk appropriately.
- Consider starting covered calls on liquid names (AAPL, TSLA, NVDA, MSFT, AVGO, HOOD) for income.
- Clean up 1-share remnant positions for simplicity.
- **Next step for true liveness**: Enable Moomoo API connection above (requires OpenD).
""")

# Footer
st.caption(f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Data: StockEvents CSV + yfinance | Moomoo integration ready to activate")

# ============================================================
# MOOMOO INTEGRATION NOTES (at bottom)
# ============================================================
with st.expander("🔌 Moomoo Integration (Prices + Live Positions)"):
    st.markdown("""
    **To enable full Moomoo integration:**

    1. Download & run **OpenD** from https://www.moomoo.com/download/OpenAPI
    2. Log in to OpenD with your **real** Moomoo account.
    3. `pip install moomoo-api`
    4. Check one or both boxes in the sidebar:
       - "Use Moomoo for live prices"
       - "Pull live positions from Moomoo"

    When "Pull live positions from Moomoo" is enabled, the dashboard will use your **actual account positions** instead of calculated net shares from the CSV. It will still try to enrich with historical cost basis where possible.

    **Tip**: Start with the prices checkbox first. Once that works reliably, enable the positions checkbox.
    """)