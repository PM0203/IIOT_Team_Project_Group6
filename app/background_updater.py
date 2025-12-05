# app/background_updater.py
import time
import threading
from typing import Optional, Dict, List
import streamlit as st
from sqlalchemy import text
from app.data_loader import get_engine, load_sensor_data

class BackgroundUpdater:
    """
    Polls PostgreSQL for new sensor_data rows by checking MAX(event_ts).
    Stores last known ts to determine updates and caches loaded DataFrames.
    """

    def __init__(self, poll_interval: float = 2.0):
        self.poll_interval = float(poll_interval)
        self.last_ts = None  # timestamp of most recent event_ts seen (may be datetime)
        self._cache = {"sensor1_df": None, "sensor2_df": None}
        self._lock = threading.Lock()
        self._stop = False

        # initial load (best-effort)
        try:
            self._cache = load_sensor_data()
        except Exception:
            self._cache = {"sensor1_df": None, "sensor2_df": None}

        # get latest ts from DB (best-effort)
        try:
            self.last_ts = self._get_latest_ts()
        except Exception:
            self.last_ts = None

        # start background thread
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _get_latest_ts(self) -> Optional[object]:
        """
        Query MAX(event_ts) from the table using SQLAlchemy engine to detect new rows.
        Returns the raw value returned by the DB (likely a datetime or int), or None on error.
        """
        try:
            engine = get_engine()
            with engine.connect() as conn:
                res = conn.execute(text("SELECT MAX(event_ts) FROM sensor_data;"))
                latest = res.scalar_one_or_none()
            # dispose engine to avoid leaking connections in some environments
            try:
                engine.dispose()
            except Exception:
                pass
            return latest
        except Exception:
            return None

    def _run(self):
        while not self._stop:
            try:
                new_ts = self._get_latest_ts()
                if new_ts and (self.last_ts is None or new_ts > self.last_ts):
                    # new data detected -> reload cache
                    with self._lock:
                        try:
                            self._cache = load_sensor_data()
                        except Exception:
                            # keep previous cache on load failure
                            pass
                        self.last_ts = new_ts
            except Exception:
                # swallow errors to avoid crashing the thread; could log if desired
                pass
            time.sleep(self.poll_interval)

    def get_latest(self) -> Dict:
        with self._lock:
            return {
                "sensor1_df": self._cache.get("sensor1_df"),
                "sensor2_df": self._cache.get("sensor2_df"),
                "last_updated": self.last_ts,
            }

    def stop(self):
        self._stop = True
        if hasattr(self, "_thread") and self._thread.is_alive():
            self._thread.join(timeout=1.0)


# Factory cached via Streamlit so only one BackgroundUpdater created per session.
@st.cache_resource
def get_cached_updater(poll_interval: float = 2.0):
    return BackgroundUpdater(poll_interval=float(poll_interval))
