# app/main_components.py
import streamlit as st
from app.diagnostics import render_sidebar_startup, note
from app.data_fragment import data_fragment
from app.virtual_monitor import render_virtual_monitor


def render_main():
    # show diagnostics (no startup errors in normal run)
    render_sidebar_startup(startup_errors="")







    # Call the data fragment (auto_refresh and interval are read from st.session_state)
    auto_refresh = st.session_state.get("auto_refresh", True)
    auto_refresh_interval = st.session_state.get("auto_refresh_interval", 3)
    start_updater = True  # you can control via env var externally if desired
    data_fragment(auto_refresh=auto_refresh, auto_refresh_interval=auto_refresh_interval, start_updater=start_updater)


    # Virtual monitor outside the fragment
    render_virtual_monitor(auto_refresh_interval=auto_refresh_interval, start_updater=start_updater)

    # footer basic placeholder (kept minimal here)
    st.markdown("---")
    st.write("IIoT Humidity Dashboard — Monitor")
    note("Rendered main page")
