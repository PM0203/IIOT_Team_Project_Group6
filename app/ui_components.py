# app/ui_components.py
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

def apply_global_style():
    st.markdown(
        """
        <style>
        html, body, .stApp { background-color: #f3f4f6; }
        [data-testid="stAppViewContainer"] { background-color: #f3f4f6; }
        [data-testid="stHeader"] { background-color: #f3f4f6; }
        [data-testid="stSidebar"] { background-color: #e5e7eb; }
        div[data-testid="stRadio"] > div { display: flex; gap: 0; }
        div[data-testid="stRadio"] label[data-baseweb="radio"] {
            background-color: #e5e7eb; color: #374151; padding: 4px 18px; margin-right: 0;
            border-radius: 0; cursor: pointer; font-weight: 600; font-size: 14px;
        }
        div[data-testid="stRadio"] label[data-baseweb="radio"]:first-child { border-radius: 999px 0 0 999px; }
        div[data-testid="stRadio"] label[data-baseweb="radio"]:last-child { border-radius: 0 999px 999px 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )

def humidity_gauge(value, title, unit):
    if pd.isna(value) if 'pd' in globals() else (value is None):
        bar_color = "#9ca3af"
    elif value > 33:
        bar_color = "#dc2626"
    elif value < 33:
        bar_color = "#eab308"
    else:
        bar_color = "#22c55e"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": title, "font": {"size": 18}},
        number={"suffix": f" {unit}", "font": {"size": 75}},
        gauge={"axis": {"range": [0,100]}, "bar": {"color": bar_color}},
    ))
    fig.update_layout(height=260, margin=dict(l=5, r=5, t=40, b=5))
    return fig


def digital_display(value, title, unit):
    fig = go.Figure(go.Indicator(
        mode="number",
        value=value,
        title={"text": title, "font": {"size": 18}},
        number={"suffix": f" {unit}", "font": {"size": 75}},
    ))
    fig.update_layout(height=260, margin=dict(l=5, r=5, t=5, b=0))
    return fig

def sensor_color(h):
    if h is None:
        return "#9ca3af"
    if h > 30:
        return "#dc2626"
    if h < 20:
        return "#eab308"
    return "#22c55e"

def device_icon(label, image_path, text_color="#111827", font_size=20, image_width=150):
    try:
        st.image(image_path, width=image_width)
    except Exception:
        # graceful fallback if icon missing
        st.markdown(f"**{label}**")
    st.markdown(
        f"""
        <div style="text-align:center; font-weight:bold; margin-top:2px; margin-bottom:2px;
                    color:{text_color}; font-size:{font_size}px;">
            {label}
        </div>
        """, unsafe_allow_html=True
    )
