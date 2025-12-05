# app/data_fragment.py
"""
Non-blocking data fragment.

This fragment starts the MQTT subscriber (and its small HTTP snapshot server),
then embeds a browser-side live widget that polls the snapshot endpoint and
updates values in-place. Because polling and updates happen in the browser,
the Streamlit Python thread is free to render the rest of the page.
"""

from app.diagnostics import render_sidebar_startup, note
from app.utils import append_diag
import streamlit as st
from app.mqtt_simple import get_mqtt_simple

SENSOR1_DEVICE = "easylog-01"
SENSOR2_DEVICE = "sense_hat"

@st.fragment(run_every=1)
def data_fragment(auto_refresh: bool = True, auto_refresh_interval: int = 3, start_updater: bool = True):
    # ensure we still have the legacy chart helpers (for fallback rendering)
    try:
        from app.ui_components import humidity_gauge, digital_display

    except Exception:
        humidity_gauge = None
        digital_display = None
    # start subscriber once
    sub = get_mqtt_simple(start=True)

    # read averages (30s window)
    s1 = sub.get_avg("easylog-01", window_seconds=30)
    s2 = sub.get_avg("sense_hat", window_seconds=30)

    # Render two-column fallback with gauges (single snapshot)
    col1, col3, col2 = st.columns([2, 1, 2])

    with col1:
        st.markdown("<h3 style='text-align:center;'>Sensor 1 (easy_log)</h3>", unsafe_allow_html=True)
        if s1 is None or (s1["humidity_pct"] is None and s1["temperature_c"] is None):
            if humidity_gauge:
                st.plotly_chart(humidity_gauge(None, "Humidity (%)", "%"), key= "sense_1_hum")
            if digital_display:
                st.plotly_chart(digital_display(None, "Temperature (°C)", "°C"), key=   "sense_1_temp")
        else:
            if humidity_gauge:
                st.plotly_chart(humidity_gauge(s1["humidity_pct"], "Humidity (%)", "%"), key=   "sense_1_hum")
            if digital_display:
                st.plotly_chart(digital_display(s1["temperature_c"], "Temperature (°C)", "°C"), key=    "sense_1_temp")


    with col2:
        st.markdown("<h3 style='text-align:center;'>Sensor 2 (sense_hat)</h3>", unsafe_allow_html=True)
        if s2 is None or (s2.get("humidity_pct") is None and s2.get("temperature_c") is None):
            if humidity_gauge:
                st.plotly_chart(humidity_gauge(None, "Humidity (%)", "%"), key= "sense_2_hum")
            if digital_display:
                st.plotly_chart(digital_display(None, "Temperature (°C)", "°C"), key=   "sense_2_temp")
        else:
            if humidity_gauge:
                st.plotly_chart(humidity_gauge(s2["humidity_pct"], "Humidity (%)", "%"), key=   "sense_2_hum")
            if digital_display:
                st.plotly_chart(digital_display(s2["temperature_c"], "Temperature (°C)", "°C"), key=    "sense_2_temp")


    # done — no loops here, so the rest of the page renders normally.
    with col3:
        # --- center-top analog clock (updates in browser without reruns) ---
        try:
            from app.clock_fragment import render_clock
            render_clock()
        except Exception as e:
            # log the failure via diagnostics helper
            note(f"render_clock failed: {type(e).__name__}: {e}")
