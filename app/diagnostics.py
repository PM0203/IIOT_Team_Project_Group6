# app/diagnostics.py
import streamlit as st
from pathlib import Path
from .utils import DIAG_LOG, append_diag

def render_sidebar_startup(startup_errors: str = ""):


    st.sidebar.header("Diagnostics")
    st.sidebar.markdown("Use this panel to see startup/import or worker errors.")
    if startup_errors:
        st.sidebar.error("Startup/import errors")
        st.sidebar.code(startup_errors[:4000])
    # show recent diag log tail
    try:
        if DIAG_LOG.exists():
            tail = "\n".join(DIAG_LOG.read_text(encoding="utf-8").splitlines()[-40:])
            if tail:
                st.sidebar.markdown("**Diag tail (recent)**")
                st.sidebar.code(tail)
    except Exception:
        pass

def note(msg: str):
    append_diag(msg)
