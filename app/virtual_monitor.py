# app/virtual_monitor.py
import streamlit as st
from datetime import datetime, timezone
from app.ui_components import device_icon, sensor_color
from app.data_loader import load_sensor_data
from app.utils import append_diag
from app.device_control import send_device_command
from app.background_updater import get_cached_updater
import requests

PI_URL = "http://192.168.137.22:8000/status"

st.fragment(run_every=60)
def render_virtual_monitor(auto_refresh_interval: int = 3, start_updater: bool = True):
    st.markdown("---")
    st.subheader("Virtual System Monitor")

    if "humidifier_state" not in st.session_state:
        st.session_state.humidifier_state = "Off"
        st.session_state.humidifier_last = None
    if "fan_state" not in st.session_state:
        st.session_state.fan_state = "Off"
        st.session_state.fan_last = None

    col_h, col_s1_icon, col_s2_icon, col_f = st.columns(4)

    with col_h:
        device_icon("Humidifier", "icons/humidifier.png", text_color="#111827", font_size=20)
        hum_choice = st.radio(
            "Humidifier switch",
            ["On", "Off"],
            index=0 if st.session_state.humidifier_state == "On" else 1,
            horizontal=True,
            key="humidifier_radio",
        )
        if hum_choice != st.session_state.humidifier_state:
            st.session_state.humidifier_state = hum_choice
            st.session_state.humidifier_last = datetime.now()
        st.write(f"State: **{st.session_state.humidifier_state}**")
        last = st.session_state.humidifier_last
        st.write("Last switch:", last.strftime("%Y-%m-%d %H:%M:%S") if last else "—")

    # sensor icon colors — try cached updater then fallback to DB
    st.fragment(run_every=1)
    def _get_last_df(sensor_idx=1):
        try:
            if start_updater:

                tmp = get_cached_updater(poll_interval=auto_refresh_interval)
                return tmp.get_latest().get(f"sensor{sensor_idx}_df")
        except Exception:
            pass
        try:
            return load_sensor_data().get(f"sensor{sensor_idx}_df")
        except Exception as e:
            append_diag(f"load_sensor_data in virtual_monitor error: {e}")
            return None

    s1_df = _get_last_df(1)
    color1 = "#9ca3af"
    try:
        if s1_df is not None and not s1_df.empty:

            color1 = sensor_color(s1_df.iloc[-1]["humidity_pct"])
    except Exception:
        pass
    with col_s1_icon:
        device_icon("Sensor 1", "icons/sensor.png", text_color=color1, font_size=20)

    s2_df = _get_last_df(2)
    color2 = "#9ca3af"
    try:
        if s2_df is not None and not s2_df.empty:
            st.balloons()
            color2 = sensor_color(s2_df.iloc[-1]["humidity_pct"])
    except Exception:
        pass
    with col_s2_icon:
        device_icon("Sensor 2", "icons/sensor.png", text_color=color2, font_size=20)

    with col_f:
        device_icon("Fan", "icons/fan.png", text_color="#111827", font_size=20)

        try:
            r = requests.get(PI_URL)
            body = r.json()
            usb_enabled = body["usb_enabled"]
            if usb_enabled:
                st.info("On")
                if st.session_state.fan_state != "On":
                    st.session_state.fan_state = "On"
                    st.session_state.fan_last = datetime.now()
            else:
                st.info("Off")
        except Exception as e:
            st.info("Unknown")

        last = st.session_state.fan_last
        st.write("Last On:", last.strftime("%Y-%m-%d %H:%M:%S") if last else "—")
