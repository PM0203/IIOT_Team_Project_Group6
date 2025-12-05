# main_streamlit.py
import streamlit as st

st.set_page_config(page_title="IIoT Humidity Dashboard - Monitor", layout="wide")
st.session_state["live_start"] = 0
from app.main_components import render_main
from datetime import datetime, timedelta, timezone

ARIZONA_TZ = timezone(timedelta(hours=-7))
now_az = datetime.now()

st.caption(now_az)
render_main()
