# pages/01_history_operator.py
"""
History & Operator page for IIoT Humidity Dashboard.

Filters and controls are placed INSIDE the fragment so changing them only
reruns the fragment (not the whole page).
"""
import streamlit as st
from datetime import datetime, timedelta, time as dt_time
import time
import pandas as pd
import plotly.express as px

from app.ui_components import apply_global_style
from app.data_loader import load_sensor_data
from app.background_updater import get_cached_updater
from app import forecasting

# Page config + style
st.set_page_config(page_title="IIoT Humidity Dashboard - History", layout="wide")
apply_global_style()

# Sidebar operator (keeps small sidebar controls outside fragment)
st.sidebar.header("Operator")
operator_map = {
    "Pankaj Mishra": 1234567890,
    "Hsin Cheng": 1232333923,
    "Praty Padalinathan": 1230987654,
}
operator_names = list(operator_map.keys())
if "operator_name" not in st.session_state:
    st.session_state.operator_name = operator_names[0]
    st.session_state.login_time = datetime.now()
selected_name = st.sidebar.selectbox(
    "Employee Login", operator_names, index=operator_names.index(st.session_state.operator_name)
)
if selected_name != st.session_state.operator_name:
    st.session_state.operator_name = selected_name
    st.session_state.login_time = datetime.now()

# cached updater used by fragment
updater = get_cached_updater(poll_interval=5)

# clear any prior placeholders on full-page rerun
if "history_placeholders" in st.session_state:
    for ph in st.session_state.history_placeholders:
        try:
            ph.empty()
        except Exception:
            pass
st.session_state.history_placeholders = []

st.title("History & Operator info")

# safe wrapper for different forecasting signatures
def safe_add_forecast_lines(fig, df, y_col, **kwargs):
    add_fn = getattr(forecasting, "add_forecast_lines", None)
    if add_fn is None:
        return fig
    try:
        maybe = add_fn(fig, df, y_col, **kwargs)
        if hasattr(maybe, "data"):
            return maybe
    except Exception:
        pass
    try:
        maybe2 = add_fn(df, y_col, **kwargs)
        if hasattr(maybe2, "data"):
            return maybe2
    except Exception:
        pass
    return fig

# -------------------------
# Fragment: contains filters + charts so only it reruns on filter changes
@st.fragment
def history_fragment():
    """
    Fragment that holds:
      - filter widgets (start/end date+time)
      - Apply button
      - Refresh button
      - alpha/beta sliders
      - the four charts (2x2)
    """
    # --- persistent pending/applied keys inside session_state (init if missing) ---
    now_local = datetime.now()
    if "hist_pending_end_date" not in st.session_state:
        st.session_state.hist_pending_end_date = now_local.date()
        st.session_state.hist_pending_end_time = now_local.time().replace(microsecond=0)
    if "hist_pending_start_date" not in st.session_state:
        earlier = now_local - timedelta(days=7)
        st.session_state.hist_pending_start_date = earlier.date()
        st.session_state.hist_pending_start_time = dt_time(0, 0, 0)

    if "hist_applied_start_dt" not in st.session_state:
        st.session_state.hist_applied_start_dt = now_local - timedelta(days=7)
    if "hist_applied_end_dt" not in st.session_state:
        st.session_state.hist_applied_end_dt = now_local

    # -------------------------
    # Controls (inside fragment)
    cols = st.columns([2, 3])
    with cols[0]:
        st.markdown("**Filter range (apply inside fragment)**")
        pd_start = st.date_input("Start date", value=st.session_state.hist_pending_start_date, key="hist_pending_start_date")
        pt_start = st.time_input("Start time", value=st.session_state.hist_pending_start_time, key="hist_pending_start_time")
        pd_end = st.date_input("End date", value=st.session_state.hist_pending_end_date, key="hist_pending_end_date")
        pt_end = st.time_input("End time", value=st.session_state.hist_pending_end_time, key="hist_pending_end_time")
        # Apply button applies pending -> applied (does not rerun whole page; only fragment)
        if st.button("Apply filters"):
            try:
                applied_start = datetime.combine(pd_start, pt_start)
                applied_end = datetime.combine(pd_end, pt_end)
            except Exception:
                applied_start = datetime.now() - timedelta(days=7)
                applied_end = datetime.now()
            if applied_end < applied_start:
                applied_start, applied_end = applied_end, applied_start
            st.session_state.hist_applied_start_dt = applied_start
            st.session_state.hist_applied_end_dt = applied_end
            # fragment will rerun because button click triggers a fragment rerun

        if st.button("Refresh data"):
            # refresh token so fragment readers can notice; no filter change
            st.session_state["history_last_manual_refresh"] = datetime.now().isoformat()
            # button click triggers fragment rerun automatically

    with cols[1]:
        st.markdown("**Forecast settings**")
        # place alpha/beta inside fragment so tuning them won't rerun whole page
        alpha = st.slider("Level smoothing α (SES / DES)", 0.05, 0.95, 0.3, 0.05, key="hist_alpha")
        beta = st.slider("Trend smoothing β (DES)", 0.05, 0.95, 0.2, 0.05, key="hist_beta")

    st.markdown("---")

    # read applied filters (these only change when Apply pressed)
    applied_start = st.session_state.hist_applied_start_dt
    applied_end = st.session_state.hist_applied_end_dt

    # Load data from updater cache, fallback to DB read with the applied range
    bundle = updater.get_latest()
    sensor1_df = bundle.get("sensor1_df")
    sensor2_df = bundle.get("sensor2_df")
    if sensor1_df is None or sensor2_df is None:
        fallback = load_sensor_data(start_dt=applied_start, end_dt=applied_end)
        sensor1_df = sensor1_df or fallback.get("sensor1_df")
        sensor2_df = sensor2_df or fallback.get("sensor2_df")

    # ensure datetime + drop tz so comparisons are valid
    for df in (sensor1_df, sensor2_df):
        if df is not None and "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
            try:
                # if tz-aware, convert to naive LOCAL time
                df["ts"] = df["ts"].dt.tz_convert("America/Phoenix").dt.tz_localize(None)
            except Exception:
                try:
                    # if only tz-localize possible, drop tz
                    df["ts"] = df["ts"].dt.tz_localize(None)
                except Exception:
                    pass

    # convert applied filters to naive as well
    applied_start = applied_start.replace(tzinfo=None)
    applied_end = applied_end.replace(tzinfo=None)

    # apply filters defensively
    try:
        if sensor1_df is not None:
            sensor1_df = sensor1_df.loc[(sensor1_df["ts"] >= applied_start) & (sensor1_df["ts"] <= applied_end)].reset_index(drop=True)
        if sensor2_df is not None:
            sensor2_df = sensor2_df.loc[(sensor2_df["ts"] >= applied_start) & (sensor2_df["ts"] <= applied_end)].reset_index(drop=True)
    except Exception as ex:
        st.error(ex)
        pass

    if (sensor1_df is None or sensor1_df.empty) and (sensor2_df is None or sensor2_df.empty):
        st.info("No data in the selected time range. Use Refresh after new data arrives.")
        return

    # charts (2x2)
    top_row = st.columns(2)
    bottom_row = st.columns(2)

    with top_row[0]:
        st.markdown("**Sensor 1 – Humidity (%)**")
        if sensor1_df is not None and not sensor1_df.empty:
            fig = px.line(sensor1_df, x="ts", y="humidity_pct", labels={"ts": "time", "humidity_pct": "Humidity (%)"})
            fig.update_layout(paper_bgcolor="#f3f4f6", plot_bgcolor="#f3f4f6")
            fig.update_yaxes(range=[0, 100])
            fig = safe_add_forecast_lines(fig, sensor1_df, "humidity_pct", alpha=alpha, beta=beta)
            st.plotly_chart(fig)
        else:
            st.info("Sensor 1: No data for selected range.")

    with top_row[1]:
        st.markdown("**Sensor 2 – Humidity (%)**")
        if sensor2_df is not None and not sensor2_df.empty:
            fig = px.line(sensor2_df, x="ts", y="humidity_pct", labels={"ts": "time", "humidity_pct": "Humidity (%)"})
            fig.update_layout(paper_bgcolor="#f3f4f6", plot_bgcolor="#f3f4f6")
            fig.update_yaxes(range=[0, 100])
            fig = safe_add_forecast_lines(fig, sensor2_df, "humidity_pct", alpha=alpha, beta=beta)
            st.plotly_chart(fig)
        else:
            st.info("Sensor 2: No data for selected range.")

    with bottom_row[0]:
        st.markdown("**Sensor 1 – Temperature (°C)**")
        if sensor1_df is not None and not sensor1_df.empty:
            fig = px.line(sensor1_df, x="ts", y="temperature_c", labels={"ts": "time", "temperature_c": "Temperature (°C)"})
            fig.update_layout(paper_bgcolor="#f3f4f6", plot_bgcolor="#f3f4f6")
            fig = safe_add_forecast_lines(fig, sensor1_df, "temperature_c", alpha=alpha, beta=beta)
            st.plotly_chart(fig)
        else:
            st.info("Sensor 1: No data for selected range.")

    with bottom_row[1]:
        st.markdown("**Sensor 2 – Temperature (°C)**")
        if sensor2_df is not None and not sensor2_df.empty:
            fig = px.line(sensor2_df, x="ts", y="temperature_c", labels={"ts": "time", "temperature_c": "Temperature (°C)"})
            fig.update_layout(paper_bgcolor="#f3f4f6", plot_bgcolor="#f3f4f6")
            fig = safe_add_forecast_lines(fig, sensor2_df, "temperature_c", alpha=alpha, beta=beta)
            st.plotly_chart(fig)
        else:
            st.info("Sensor 2: No data for selected range.")

    # small cooperative pause
    time.sleep(0.02)

# call fragment
history_fragment()

# Operator info (outside fragment)
st.markdown("---")
st.subheader("Operator information")
operator_name = st.session_state.get("operator_name", "Unknown")
login_time = st.session_state.get("login_time", datetime.now())
st.write("Employee ID:", f"**{operator_map.get(operator_name, '—')}**")
st.write("Employee name:", f"**{operator_name}**")
st.write("Login time:", login_time.strftime("%Y-%m-%d %H:%M:%S"))

# Footer: show applied filters & last load
ph_footer = st.empty()
st.session_state.history_placeholders.append(ph_footer)
with ph_footer.container():
    st.markdown("---")
    applied_start = st.session_state.get("hist_applied_start_dt", datetime.now() - timedelta(days=7))
    applied_end = st.session_state.get("hist_applied_end_dt", datetime.now())
    last_loaded = updater.get_latest().get("last_updated")
    st.write("Data last loaded:", last_loaded.strftime("%Y-%m-%d %H:%M:%S") if last_loaded else "unknown")
    st.write("Applied filters:", f"{applied_start.strftime('%Y-%m-%d %H:%M:%S')} → {applied_end.strftime('%Y-%m-%d %H:%M:%S')}")

time.sleep(0.02)
