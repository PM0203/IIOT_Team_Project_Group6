# app/data_loader.py
import os
from typing import Dict, Optional, Tuple, Union
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

# timezone helper (zoneinfo on py3.9+)
try:
    from zoneinfo import ZoneInfo
    AZ_TZ = ZoneInfo("America/Phoenix")
except Exception:
    AZ_TZ = None  # best-effort; will fallback to naive datetimes


def get_engine():
    """
    Build an SQLAlchemy Engine from environment variables (postgresql+psycopg2).
    Uses SQLAlchemy URL.create to correctly escape credentials.
    """
    user = os.environ.get("PGUSER", "postgres")
    password = os.environ.get("PGPASSWORD", "admin")
    host = os.environ.get("PGHOST", "localhost")
    port = int(os.environ.get("PGPORT", 5432))
    db = os.environ.get("PGDATABASE", "postgres")

    try:
        url = URL.create(
            drivername="postgresql+psycopg2",
            username=user,
            password=password,
            host=host,
            port=port,
            database=db,
        )
        engine = create_engine(url, pool_pre_ping=True)
        return engine
    except Exception as e:
        # If engine creation fails, propagate error to caller (they will handle)
        raise


def _read_all_rows(start_dt: Optional[Union[datetime, str]] = None,
                   end_dt: Optional[Union[datetime, str]] = None) -> Optional[pd.DataFrame]:
    """
    Read sensor_data table returning a dataframe with device_id, event_ts, temperature, humidity.
    Optionally restrict rows to start_dt <= event_ts <= end_dt. Accepts datetime or ISO strings.
    Returns None on DB error.
    """
    q_base = """
    SELECT device_id, event_ts, temperature, humidity
    FROM sensor_data
    """
    where_clauses = []
    params = {}

    def _to_iso_str(dt):
        if isinstance(dt, datetime):
            # ensure UTC-ish ISO if tz-aware, else naive ISO
            try:
                return datetime.now().isoformat(timespec="seconds")
            except Exception:
                return dt.isoformat()
        return str(dt)

    if start_dt is not None:
        where_clauses.append("event_ts >= %(start_dt)s")
        params["start_dt"] = _to_iso_str(start_dt)
    if end_dt is not None:
        where_clauses.append("event_ts <= %(end_dt)s")
        params["end_dt"] = _to_iso_str(end_dt)

    if where_clauses:
        q = q_base + " WHERE " + " AND ".join(where_clauses) + " ORDER BY event_ts ASC;"
    else:
        q = q_base + " ORDER BY event_ts ASC;"

    try:
        engine = get_engine()
        # Use read_sql with params to avoid string interpolation issues
        df = pd.read_sql(q, con=engine, params=params if params else None)
        engine.dispose()
    except Exception as e:
        # Log to stdout (keeps behavior similar to previous; UI pages should handle None)
        print("DB read error:", e)
        return None

    # Normalize column names and types
    if "event_ts" in df.columns:
        # try parse and keep tzinfo if present
        df["ts"] = pd.to_datetime(df["event_ts"], errors="coerce", utc=True)
        # convert from UTC to America/Phoenix if zoneinfo available
        if AZ_TZ is not None:
            try:
                df["ts"] = df["ts"].dt.tz_convert(AZ_TZ)
            except Exception:
                # if tz conversion fails, keep UTC-aware
                pass
        else:
            # drop tz info to keep naive datetimes (consistent with earlier code)
            try:
                df["ts"] = df["ts"].dt.tz_convert(timezone.utc).dt.tz_localize(None)
            except Exception:
                try:
                    df["ts"] = df["ts"].dt.tz_localize(None)
                except Exception:
                    pass
    elif "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")

    if "temperature" in df.columns:
        df["temperature_c"] = pd.to_numeric(df["temperature"], errors="coerce")
    elif "temperature_c" in df.columns:
        df["temperature_c"] = pd.to_numeric(df["temperature_c"], errors="coerce")

    if "humidity" in df.columns:
        df["humidity_pct"] = pd.to_numeric(df["humidity"], errors="coerce")
    elif "humidity_pct" in df.columns:
        df["humidity_pct"] = pd.to_numeric(df["humidity_pct"], errors="coerce")

    keep_cols = [c for c in ["device_id", "ts", "temperature_c", "humidity_pct"] if c in df.columns]
    df = df[keep_cols].copy()
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return df


def _choose_device_ids(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    # same logic as before
    if df is None or df.empty:
        return (None, None)

    devs = df["device_id"].astype(str).unique().tolist()
    devs_lower = [d.lower() for d in devs]

    easy = None
    sense = None
    for d, dl in zip(devs, devs_lower):
        if "easylog" in dl or "easy-log" in dl or "easy_log" in dl:
            easy = d
        if "sense" in dl or "sense_hat" in dl or "hat" in dl:
            sense = d

    if easy and sense and easy != sense:
        return (easy, sense)

    counts = df["device_id"].value_counts().index.tolist()
    if len(counts) >= 2:
        return (counts[0], counts[1])
    elif len(counts) == 1:
        return (counts[0], None)
    else:
        return (None, None)


def split_by_device(df: pd.DataFrame, device_id: Optional[str]) -> Optional[pd.DataFrame]:
    if df is None or device_id is None:
        return None
    sub = df[df["device_id"] == device_id].copy()
    if sub.empty:
        return None
    sub = sub[["ts", "temperature_c", "humidity_pct"]].copy()
    sub = sub.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return sub


def load_sensor_data(start_dt: Optional[Union[datetime, str]] = None,
                     end_dt: Optional[Union[datetime, str]] = None) -> Dict[str, Optional[pd.DataFrame]]:
    """
    Load sensor data; optionally only rows between start_dt and end_dt (inclusive).
    start_dt/end_dt can be datetime objects or ISO strings. If omitted, full table is read.
    Returns dict {sensor1_df, sensor2_df} where each may be None.
    """
    df = _read_all_rows(start_dt=start_dt, end_dt=end_dt)
    if df is None:
        return {"sensor1_df": None, "sensor2_df": None}
    d1, d2 = _choose_device_ids(df)
    df1 = split_by_device(df, d1)
    df2 = split_by_device(df, d2)
    if df1 is None and df2 is None and not df.empty:
        unique = df["device_id"].unique().tolist()
        if len(unique) >= 1:
            df1 = split_by_device(df, unique[0])
        if len(unique) >= 2:
            df2 = split_by_device(df, unique[1])
    return {"sensor1_df": df1, "sensor2_df": df2}
