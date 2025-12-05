# pages/03_server_data_log.py
"""
Streamlit page wrapper for server_data_log.py behavior.

- Starts a background MQTT subscriber that batches messages and writes JSONL files under `logs/<YYYY-MM-DD>/`.
- Flushes when batch size is reached or every `flush_interval_s` (default 1s).
- Exposes a fragment which updates every second (fragment-scoped reruns) showing live status.
"""

import streamlit as st
import threading
import time
import os
import json
import re
from datetime import datetime
import paho.mqtt.client as mqtt
from pathlib import Path
from typing import Optional

# -------- CONFIG (tweak as desired) ----------
DEFAULT_BROKER = "broker.hivemq.com"
DEFAULT_PORT = 1883
DEFAULT_GROUP = 6
DEFAULT_TOPIC = f"MSN/group{DEFAULT_GROUP}/#"
BATCH_SIZE = 10
ROOT_OUTDIR = Path("logs")
FLUSH_INTERVAL_S = 1.0   # flush every 1 second (or sooner if batch fills)
MQTT_CLIENT_ID = f"StreamlitBatcher-{int(time.time())}"

# ensure output folder exists
ROOT_OUTDIR.mkdir(parents=True, exist_ok=True)


# --------- Background worker class ----------
class MQTTFileBatcher:
    def __init__(self, broker=DEFAULT_BROKER, port=DEFAULT_PORT, topic=DEFAULT_TOPIC,
                 batch_size=BATCH_SIZE, outdir: Path = ROOT_OUTDIR, flush_interval_s: float = FLUSH_INTERVAL_S):
        self.broker = broker
        self.port = port
        self.topic = topic
        self.batch_size = max(1, int(batch_size))
        self.outdir = Path(outdir)
        self.flush_interval_s = float(flush_interval_s)

        self.buffer = []
        self.buffer_lock = threading.Lock()
        self.file_counter = -1
        self._stop_event = threading.Event()
        self._thread = None
        self._client = None
        self._files_written = 0
        self._last_flush_time: Optional[datetime] = None
        self._started = False

        self._init_file_counter()

    # ----- file helpers -----
    def _date_folder_name(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    def _make_output_folder_for_now(self) -> Path:
        folder = self.outdir / self._date_folder_name(datetime.now())
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _unique_filename(self, prefix: str = None, ext: str = "jsonl") -> str:
        # choose numeric prefix
        if prefix is None:
            prefix = str(self.file_counter)
        return f"{prefix}.{ext}"

    def _init_file_counter(self):
        # scan today's folder + processed for numeric prefixes
        out_folder = self._make_output_folder_for_now()
        num_re = re.compile(r"^(\d+)(?:\..*)?$")
        highest = -1

        def scan_dir(p: Path):
            local_high = -1
            try:
                for f in p.iterdir():
                    if not f.is_file():
                        continue
                    m = num_re.match(f.name)
                    if m:
                        try:
                            n = int(m.group(1))
                            if n > local_high:
                                local_high = n
                        except Exception:
                            continue
            except Exception:
                pass
            return local_high

        main_h = scan_dir(out_folder)
        processed_h = scan_dir(out_folder / "processed")
        highest = max(main_h, processed_h)
        self.file_counter = (highest + 1) if highest >= 0 else 0

    # ----- MQTT callbacks -----
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(self.topic)
        else:
            print(f"[MQTT] Connect rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload_text = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            payload_text = str(msg.payload)

        rec = {
            "received_at": datetime.now().isoformat(timespec="seconds"),
            "local_time": datetime.now().isoformat(),
            "topic": msg.topic,
            "qos": int(msg.qos),
            "retain": bool(msg.retain),
            "payload": payload_text,
        }
        with self.buffer_lock:
            self.buffer.append(rec)

        # flush asynchronously if buffer full
        if len(self.buffer) >= self.batch_size:
            threading.Thread(target=self._flush_buffer_to_file, args=(False,), daemon=True).start()

    # ----- flush -----
    def _flush_buffer_to_file(self, force: bool = False):
        with self.buffer_lock:
            if not self.buffer:
                return 0
            if len(self.buffer) < self.batch_size and not force:
                return 0
            # copy and clear buffer
            rows = list(self.buffer)
            self.buffer = []

        out_folder = self._make_output_folder_for_now()
        fname = self._unique_filename(prefix=str(self.file_counter))
        path = out_folder / fname
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            self.file_counter += 1
            self._files_written += 1
            self._last_flush_time = datetime.now()
            return len(rows)
        except Exception as e:
            # if write failed, put back rows into buffer (best-effort)
            with self.buffer_lock:
                # prepend to buffer
                self.buffer = rows + self.buffer
            print(f"[MQTTFileBatcher] Failed write {path}: {e}")
            return 0

    # ----- control lifecycle -----
    def start(self):
        if self._started:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._started = True

    def stop(self):
        self._stop_event.set()
        # stop MQTT loop if present
        try:
            if self._client:
                self._client.loop_stop()
                self._client.disconnect()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=1.0)
        self._started = False

    def _run_loop(self):
        # start mqtt client
        try:
            client = mqtt.Client(client_id=MQTT_CLIENT_ID)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.connect(self.broker, self.port, keepalive=60)
            client.loop_start()
            self._client = client
        except Exception as e:
            print(f"[MQTTFileBatcher] MQTT start error: {e}")
            self._client = None

        # loop: flush periodically until stopped
        while not self._stop_event.is_set():
            # periodic flush (force flush small batches)
            try:
                self._flush_buffer_to_file(force=True)
            except Exception as e:
                print(f"[MQTTFileBatcher] flush error: {e}")
            # sleep in small increments so we can exit quickly
            for _ in range(int(max(1, int(self.flush_interval_s)))):
                if self._stop_event.is_set():
                    break
                time.sleep(1)
        # final flush on exit
        try:
            self._flush_buffer_to_file(force=True)
        except Exception:
            pass

    # ----- utility / status -----
    def force_flush_now(self):
        return self._flush_buffer_to_file(force=True)

    def get_status(self):
        with self.buffer_lock:
            return {
                "buffer_len": len(self.buffer),
                "files_written": self._files_written,
                "file_counter": self.file_counter,
                "last_flush_time": (self._last_flush_time.isoformat() if self._last_flush_time else None),
                "started": self._started,
                "broker": self.broker,
                "topic": self.topic,
            }


# --------- Singleton via st.cache_resource ----------
@st.cache_resource
def get_file_batcher(broker=DEFAULT_BROKER, port=DEFAULT_PORT, topic=DEFAULT_TOPIC,
                     batch_size=BATCH_SIZE, outdir=ROOT_OUTDIR, flush_interval_s=FLUSH_INTERVAL_S):
    b = MQTTFileBatcher(broker=broker, port=port, topic=topic, batch_size=batch_size, outdir=outdir, flush_interval_s=flush_interval_s)
    b.start()
    return b


# --------- Fragment UI that refreshes (fragment-scoped if available) ----------
@st.fragment
def batcher_fragment(auto_refresh: bool = True, interval_s: float = 1.0):
    """
    Small fragment showing live batcher status. It will schedule a fragment-scoped
    rerun every `interval_s` seconds when auto_refresh=True.
    """
    st.subheader("MQTT -> File batcher (logs/)")

    batcher = get_file_batcher()  # singleton
    status = batcher.get_status()

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.write("Broker:", status.get("broker"))
        st.write("Topic:", status.get("topic"))
        st.write("Started:", status.get("started"))
    with col2:
        st.write("Buffer length:", status.get("buffer_len"))
        st.write("Files written:", status.get("files_written"))
    with col3:
        st.write("Next flush interval (s):", batcher.flush_interval_s)
        st.write("Last flush:", status.get("last_flush_time") or "—")

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Force flush now"):
            n = batcher.force_flush_now()
            st.success(f"Flushed {n} records (if any).")
    with c2:
        if st.button("Stop batcher"):
            batcher.stop()
            st.warning("Batcher stopped.")
    with c3:
        if st.button("Start batcher"):
            batcher.start()
            st.success("Batcher started.")

    # auto fragment rerun (fragment scope preferred)
    if auto_refresh:
        try:
            time.sleep(max(0.1, float(interval_s)))
            st.rerun(scope="fragment")
        except Exception:
            # fallback to full rerun
            time.sleep(max(0.1, float(interval_s)))
            st.rerun()


# --------- Page layout ----------
st.set_page_config(page_title="Server Data Log (MQTT -> logs/)", layout="wide")
st.title("Server Data Logging")

st.markdown(
    """
    This page runs a background MQTT subscriber that batches incoming messages and writes
    them as JSONL files under `logs/<YYYY-MM-DD>/`. The worker runs in a daemon thread
    started once (singleton). Use the controls below to force a flush or stop/start the batcher.
    """
)

# simple controls
auto_refresh = st.checkbox("Auto-refresh status (fragment)", value=True)
interval = st.slider("Fragment refresh interval (s)", min_value=0.5, max_value=10.0, value=1.0, step=0.5)

# call fragment (this fragment is where the "every 1s" UI refresh happens)
batcher_fragment(auto_refresh=auto_refresh, interval_s=interval)

st.markdown("---")
st.info("Files are saved to `logs/YYYY-MM-DD/` next to this app. The background batcher keeps writing even if you close this page; it stops when the Streamlit process stops.")
