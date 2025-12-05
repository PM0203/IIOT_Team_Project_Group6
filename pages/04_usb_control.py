# pages/00_usb_autocontrol.py
"""
USB Toggle + Sliding-window (last 60 records) weighted-average auto-control.

Behavior:
 - Collect the last 60 records (most recent overall) across all devices' mqtt store.
 - Compute per-device averages from that 60-record window.
 - Compute a weighted overall humidity average: overall = w1*avg_sensor1 + w2*avg_sensor2.
   By default sensor2 is given higher weight (configurable in sidebar).
 - If overall UCL/LCL decision logic desired, replace with direct threshold test on weighted average.
 - Manual OFF override prevents auto-ON until cleared. Manual ON clears the override.
"""
from __future__ import annotations
import streamlit as st
import time
from datetime import datetime, timezone
import statistics
import requests
from typing import Dict, List, Optional, Tuple

# Pi endpoint (can put in st.secrets)
PI_URL = "http://192.168.137.22:8000"

# Config
WINDOW_RECORDS = 60
POLL_INTERVAL = 1.0  # seconds per fragment loop

st.set_page_config(page_title="USB + Sliding-window Auto Control", layout="centered")
st.title("USB Toggle — Sliding-window (last 60 records) Weighted Auto Control")

# sidebar controls
st.sidebar.header("Weighted averaging & thresholds")
w2 = st.sidebar.slider("Weight for Sensor 2 (sense_hat) relative (0..1)", 0.0, 1.0, 0.7, 0.05, key="weight_sensor2")
w1 = 1.0 - float(w2)
st.sidebar.write(f"Effective weight: Sensor1 = {w1:.2f}, Sensor2 = {w2:.2f}")

th_on = st.sidebar.number_input("Auto-ON if weighted avg > (humidity %)", min_value=0.0, max_value=100.0, value=75.0, step=0.5, key="ws_th_on")
th_off = st.sidebar.number_input("Auto-OFF if weighted avg < (humidity %)", min_value=0.0, max_value=100.0, value=40.0, step=0.5, key="ws_th_off")

st.sidebar.markdown("---")
if "ws_manual_override" not in st.session_state:
    st.session_state["ws_manual_override"] = None  # {"state":"on"/"off","ts":iso}

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("Manual ON"):
        try:
            r = requests.get(f"{PI_URL}/on", timeout=8)
            st.sidebar.success(f"ON (HTTP {r.status_code})")
            st.session_state["ws_manual_override"] = {"state": "on", "ts": datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            st.sidebar.error(f"Manual ON failed: {e}")
with col2:
    if st.button("Manual OFF"):
        try:
            r = requests.get(f"{PI_URL}/off", timeout=8)
            st.sidebar.success(f"OFF (HTTP {r.status_code})")
            st.session_state["ws_manual_override"] = {"state": "off", "ts": datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            st.sidebar.error(f"Manual OFF failed: {e}")

st.sidebar.markdown("---")
if st.session_state.get("ws_manual_override"):
    mo = st.session_state["ws_manual_override"]
    st.sidebar.warning(f"Manual override: {mo.get('state').upper()} (set {mo.get('ts')})")
    if st.sidebar.button("Clear manual override"):
        st.session_state.pop("ws_manual_override", None)
        st.sidebar.success("Manual override cleared.")

st.markdown(
    f"Using sliding window of the **last {WINDOW_RECORDS} records** across all devices. "
    "Sensor2 receives higher weight by default. Devices with no records in the window are excluded."
)

# helper to normalize timestamps into epoch float for sorting
def _to_epoch(ts) -> Optional[float]:
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, str):
            # try iso parse
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                # treat naive as UTC
                return dt.replace(tzinfo=timezone.utc).timestamp()
            return dt.astimezone(timezone.utc).timestamp()
        if hasattr(ts, "timestamp"):
            # datetime-like
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc).timestamp()
            return ts.astimezone(timezone.utc).timestamp()
    except Exception:
        try:
            return float(ts)
        except Exception:
            return None

# fragment: cooperative loop
@st.fragment
def usb_control_fragment(poll_interval: float = POLL_INTERVAL, window_records: int = WINDOW_RECORDS):
    try:
        from app import mqtt_simple
    except Exception as e:
        st.error(f"mqtt_simple import failed: {e}")
        return

    # ensure subscriber started (idempotent)
    try:
        mqtt_simple.get_mqtt_simple(start=True)
    except Exception:
        pass

    ph_status = st.empty()
    ph_table = st.empty()
    ph_action = st.empty()
    ph_debug = st.empty()

    MAX_RUN = 60 * 30
    start_time = time.time()

    while True:
        # cooperative exit guards
        if st.session_state.get("stop_usb_control_fragment", False):
            ph_status.info("USB-control fragment stopped by session_state flag.")
            break
        if time.time() - start_time > MAX_RUN:
            ph_status.warning("USB-control fragment reached guard timeout.")
            break

        # copy all samples from mqtt_simple store safely
        try:
            with mqtt_simple._lock:
                # mqtt_simple._store is assumed mapping device_id -> deque[(ts, temp, hum, raw, topic), ...]
                all_entries = []
                for dev, dq in mqtt_simple._store.items():
                    for (ts, t, h, raw, topic) in dq:
                        epoch = _to_epoch(ts)
                        all_entries.append({"device": dev, "ts_epoch": epoch, "temp": t, "hum": h, "raw": raw, "topic": topic})
        except Exception as e:
            ph_status.error(f"Error reading mqtt_simple store: {e}")
            time.sleep(max(0.1, poll_interval))
            continue

        if not all_entries:
            ph_status.info("No MQTT samples available yet.")
            ph_table.table({"device": [], "avg_hum": [], "avg_temp": [], "samples": []})
            ph_action.markdown("**Action:** No action (no samples)")
            time.sleep(max(0.1, poll_interval))
            continue

        # sort by timestamp ascending and take last `window_records` (most recent)
        # if ts_epoch None, treat as very old (put to front so they get dropped)
        all_entries.sort(key=lambda e: (e["ts_epoch"] is None, e["ts_epoch"]))  # None will be (True, None) -> at end? invert: use tuple
        # better: convert None to -inf so they sort oldest
        def _sort_key(e):
            return e["ts_epoch"] if e["ts_epoch"] is not None else -1.0
        all_entries.sort(key=_sort_key)
        recent = all_entries[-window_records:] if len(all_entries) >= 1 else []

        # Build per-device lists from these recent records
        per_device: Dict[str, Dict[str, List[float]]] = {}
        for ent in recent:
            dev = ent["device"]
            hum = ent["hum"]
            temp = ent["temp"]
            if dev not in per_device:
                per_device[dev] = {"hums": [], "temps": []}
            try:
                if hum is not None:
                    per_device[dev]["hums"].append(float(hum))
            except Exception:
                pass
            try:
                if temp is not None:
                    per_device[dev]["temps"].append(float(temp))
            except Exception:
                pass

        # Compute per-device means and build a device rows list for table
        device_rows = []
        # Identify sensor1 and sensor2 device ids heuristically:
        # sensor2 preferred if dev name contains 'sense', 'sense_hat', or 'hat'
        sensor1_id = None
        sensor2_id = None
        dev_keys = list(per_device.keys())
        for d in dev_keys:
            dl = d.lower()
            if "sense" in dl or "hat" in dl:
                sensor2_id = d
            if "easy" in dl or "easylog" in dl or "easy-log" in dl:
                sensor1_id = d
        # fallback: pick first two devices if no name hints
        if not sensor1_id and dev_keys:
            sensor1_id = dev_keys[0]
        if not sensor2_id and len(dev_keys) >= 2:
            sensor2_id = dev_keys[1] if dev_keys[1] != sensor1_id else (dev_keys[0] if len(dev_keys) > 1 else None)

        for dev, lists in per_device.items():
            avg_h = statistics.mean(lists["hums"]) if lists["hums"] else None
            avg_t = statistics.mean(lists["temps"]) if lists["temps"] else None
            device_rows.append({
                "device": dev,
                "avg_hum": (None if avg_h is None else f"{avg_h:.2f}"),
                "avg_temp": (None if avg_t is None else f"{avg_t:.2f}"),
                "samples": len(lists["hums"])
            })
            # update session state per-device averages (so other pages can use)
            st.session_state[f"sensor_{dev}_avg_humidity"] = avg_h
            st.session_state[f"sensor_{dev}_avg_temperature"] = avg_t

        # compute weighted average across sensor1 and sensor2 (prefer sensor2 if present)
        avg_s1 = None
        avg_s2 = None
        if sensor1_id and sensor1_id in per_device and per_device[sensor1_id]["hums"]:
            avg_s1 = statistics.mean(per_device[sensor1_id]["hums"])
        if sensor2_id and sensor2_id in per_device and per_device[sensor2_id]["hums"]:
            avg_s2 = statistics.mean(per_device[sensor2_id]["hums"])

        weighted_avg = None
        # if both present: use weighted combination
        if avg_s1 is not None and avg_s2 is not None:
            weighted_avg = w1 * avg_s1 + w2 * avg_s2
        elif avg_s2 is not None:
            weighted_avg = avg_s2  # prefer sensor2 if only it exists
        elif avg_s1 is not None:
            weighted_avg = avg_s1
        else:
            weighted_avg = None

        # present status and decide action
        if weighted_avg is None:
            ph_status.info(f"No humidity values present in the last {window_records} records.")
            ph_table.table(device_rows if device_rows else {"device": [], "avg_hum": [], "avg_temp": [], "samples": []})
            ph_action.markdown("**Action:** No action (no humidity)")
            ph_debug.write({"window_count": len(recent)})
            time.sleep(max(0.1, poll_interval))
            continue

        # Show status
        ph_status.markdown(
            f"**Sliding window (last {window_records} records):** total samples={len(recent)}  "
            f"Weighted avg = {weighted_avg:.2f}%"
        )
        ph_table.table(device_rows)

        # Decision: simple thresholds on weighted_avg
        action_taken = "No action"
        manual_override = st.session_state.get("ws_manual_override")
        allow_auto_on = not (manual_override and manual_override.get("state") == "off")

        try:
            if weighted_avg > float(st.session_state.get("ws_th_on", th_on)):
                if allow_auto_on:
                    try:
                        r = requests.get(f"{PI_URL}/on", timeout=8)
                        action_taken = f"AUTO-ON (HTTP {r.status_code})"
                    except Exception as ex:
                        action_taken = f"AUTO-ON failed: {ex}"
                else:
                    action_taken = "Auto-ON suppressed by manual OFF override"
            elif weighted_avg < float(st.session_state.get("ws_th_off", th_off)):
                try:
                    r = requests.get(f"{PI_URL}/off", timeout=8)
                    action_taken = f"AUTO-OFF (HTTP {r.status_code})"
                except Exception as ex:
                    action_taken = f"AUTO-OFF failed: {ex}"
            else:
                action_taken = "No action"
        except Exception as e:
            action_taken = f"Decision error: {e}"

        ph_action.markdown(f"**Action:** {action_taken}")

        ph_debug.json({
            "window_records": len(recent),
            "sensor1_id": sensor1_id,
            "sensor2_id": sensor2_id,
            "avg_s1": avg_s1,
            "avg_s2": avg_s2,
            "w1": w1,
            "w2": w2,
            "weighted_avg": weighted_avg,
            "threshold_on": st.session_state.get("ws_th_on"),
            "threshold_off": st.session_state.get("ws_th_off"),
            "manual_override": manual_override,
            "action": action_taken
        })

        time.sleep(max(0.1, poll_interval))

# call the fragment
usb_control_fragment(poll_interval=POLL_INTERVAL, window_records=WINDOW_RECORDS)
