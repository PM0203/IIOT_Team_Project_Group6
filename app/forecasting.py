# app/forecasting.py
import numpy as np
import pandas as pd
import plotly.express as px
from statsmodels.tsa.holtwinters import SimpleExpSmoothing, ExponentialSmoothing

def add_forecast_lines(df, y_col, minutes_ahead=30, num_points=30, alpha=0.3, beta=0.2, seasonal_periods=60):
    """
    Returns a plotly figure with actual series and forecast lines (SES/DES/TES) where possible.
    """
    if df is None or df.empty or y_col not in df.columns:
        fig = px.line()
        return fig

    arr = df[["ts", y_col]].dropna().sort_values("ts")
    if arr.empty:
        return px.line()

    fig = px.line(arr, x="ts", y=y_col, labels={"ts": "time", y_col: y_col})
    fig.update_layout(paper_bgcolor="#f3f4f6", plot_bgcolor="#f3f4f6")

    y = arr[y_col].astype(float).values
    if len(y) < 5:
        return fig

    N = min(10, len(y))
    last_value = np.mean(y[-N:])
    y_smooth = y.copy()
    y_smooth[-1] = last_value

    ses_forecast = des_forecast = tes_forecast = None

    try:
        ses_model = SimpleExpSmoothing(y_smooth).fit(smoothing_level=alpha, optimized=False)
        ses_forecast = ses_model.forecast(num_points)
    except Exception:
        pass

    try:
        des_model = ExponentialSmoothing(y_smooth, trend="add", seasonal=None).fit(
            smoothing_level=alpha, smoothing_trend=beta, optimized=False
        )
        des_forecast = des_model.forecast(num_points)
    except Exception:
        pass

    try:
        tes_model = ExponentialSmoothing(y_smooth, trend="add", seasonal="add", seasonal_periods=seasonal_periods).fit(optimized=True)
        tes_forecast = tes_model.forecast(num_points)
    except Exception:
        pass

    last_ts = arr["ts"].iloc[-1]
    dt = (arr["ts"].iloc[-1] - arr["ts"].iloc[-2]).total_seconds()
    if dt <= 0:
        dt = 1.0
    future_seconds = np.linspace(dt, minutes_ahead * 60, num_points)
    future_ts = [last_ts + pd.to_timedelta(s, unit="s") for s in future_seconds]

    if len(fig.data) > 0:
        fig.data[0].name = "Actual"
        fig.data[0].line.color = "#2563eb"

    if ses_forecast is not None:
        fig.add_scatter(x=future_ts, y=ses_forecast, mode="lines", name="SES (α)", line=dict(color="#f59e0b", dash="dot"))
    if des_forecast is not None:
        fig.add_scatter(x=future_ts, y=des_forecast, mode="lines", name="DES (α, β)", line=dict(color="#10b981", dash="dot"))
    if tes_forecast is not None:
        fig.add_scatter(x=future_ts, y=tes_forecast, mode="lines", name="TES", line=dict(color="#8b5cf6", dash="dot"))

    return fig
