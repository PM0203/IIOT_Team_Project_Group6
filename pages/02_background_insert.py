# pages/02_background_ingest.py
"""
Background ingestion + migration runner.

- Runs insert.py every INGEST_INTERVAL seconds (default 10s).
- After each insert run, automatically runs migration.py (if present).
- Worker runs in a daemon thread created once via st.cache_resource so it
  does not block or trigger page reruns and does not create duplicate workers.
- Logs stdout/stderr to ingest/worker.log and ingest/worker.error.log
"""

import streamlit as st
from pathlib import Path
import threading
import subprocess
import shlex
import time
from datetime import datetime, timedelta, timezone

ARIZONA_TZ = timezone(timedelta(hours=-7))
now_az = datetime.now()


import sys
from typing import Optional

# ----------------------------
# Configuration
# ----------------------------
PROJECT_ROOT = Path(".").resolve()
INSERT_SCRIPT = PROJECT_ROOT / "insert.py"       # unchanged insert.py
MIGRATE_SCRIPT = PROJECT_ROOT / "migration.py"   # your migration script; will be run if present
INGEST_DIR = PROJECT_ROOT / "ingest"             # where insert.py writes success/failed logs
INGEST_DIR.mkdir(parents=True, exist_ok=True)

WORKER_LOG = INGEST_DIR / "worker.log"
WORKER_ERR_LOG = INGEST_DIR / "worker.error.log"

# default interval (seconds)
DEFAULT_INGEST_INTERVAL = 10

# ----------------------------
# Helpers
# ----------------------------
def now_iso() -> str:
    return now_az.isoformat(timespec="seconds")

def append_log(path: Path, text: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:
        # best-effort only
        pass

def run_command(cmd: str, timeout: Optional[int] = None) -> dict:
    """
    Run a command using subprocess (no shell). Returns dict with returncode, stdout, stderr.
    """
    if not cmd:
        return {"returncode": 0, "stdout": "", "stderr": ""}

    parts = shlex.split(cmd)
    try:
        proc = subprocess.Popen(parts, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = proc.communicate(timeout=timeout)
        return {"returncode": proc.returncode, "stdout": out, "stderr": err}
    except subprocess.TimeoutExpired as te:
        try:
            proc.kill()
        except Exception:
            pass
        out, err = proc.communicate() if 'proc' in locals() else ("", str(te))
        return {"returncode": -1, "stdout": out, "stderr": f"TimeoutExpired: {err}"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}

# ----------------------------
# Worker implementation
# ----------------------------
class BackgroundIngestWorker:
    def __init__(self, ingest_interval: int = DEFAULT_INGEST_INTERVAL):
        self.ingest_interval = max(1, int(ingest_interval))
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_run = None
        self._running = False

    def _run_loop(self):
        # IMPORTANT: never call Streamlit APIs from this thread
        self._running = True
        append_log(WORKER_LOG, f"{now_iso()} | WORKER_STARTED | interval={self.ingest_interval}s")
        while not self._stop_event.is_set():
            start_ts = now_iso()
            run_meta = {"start": start_ts, "insert": None, "migrate": None, "error": None}

            # 1) Run insert.py (if present)
            if INSERT_SCRIPT.exists():
                insert_cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(INSERT_SCRIPT))}"
                append_log(WORKER_LOG, f"{now_iso()} | RUN_INSERT | cmd={insert_cmd}")
                try:
                    res = run_command(insert_cmd, timeout=None)
                    run_meta["insert"] = res
                    append_log(WORKER_LOG, f"{now_iso()} | INSERT_RET | rc={res.get('returncode')}")
                    if res.get("stdout"):
                        append_log(WORKER_LOG, f"{now_iso()} | INSERT_OUT | {res.get('stdout')[:4000]}")
                    if res.get("stderr"):
                        append_log(WORKER_ERR_LOG, f"{now_iso()} | INSERT_ERR | {res.get('stderr')[:4000]}")
                except Exception as e:
                    run_meta["error"] = f"insert_exception:{e}"
                    append_log(WORKER_ERR_LOG, f"{now_iso()} | INSERT_EXCEPTION | {e}")
            else:
                append_log(WORKER_ERR_LOG, f"{now_iso()} | INSERT_MISSING | {INSERT_SCRIPT}")

            # 2) Run migration.py automatically (if present)
            if MIGRATE_SCRIPT.exists():
                migrate_cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(MIGRATE_SCRIPT))}"
                append_log(WORKER_LOG, f"{now_iso()} | RUN_MIGRATE | cmd={migrate_cmd}")
                try:
                    res2 = run_command(migrate_cmd, timeout=None)
                    run_meta["migrate"] = res2
                    append_log(WORKER_LOG, f"{now_iso()} | MIGRATE_RET | rc={res2.get('returncode')}")
                    if res2.get("stdout"):
                        append_log(WORKER_LOG, f"{now_iso()} | MIGRATE_OUT | {res2.get('stdout')[:4000]}")
                    if res2.get("stderr"):
                        append_log(WORKER_ERR_LOG, f"{now_iso()} | MIGRATE_ERR | {res2.get('stderr')[:4000]}")
                except Exception as e:
                    run_meta["error"] = f"migrate_exception:{e}"
                    append_log(WORKER_ERR_LOG, f"{now_iso()} | MIGRATE_EXCEPTION | {e}")
            else:
                append_log(WORKER_LOG, f"{now_iso()} | MIGRATE_SKIP | {MIGRATE_SCRIPT} not found")

            # record last run metadata (thread-safe)
            with self._lock:
                self._last_run = run_meta
                self._last_run_time = now_az.isoformat(timespec="seconds")

            # sleep interval but allow stop to interrupt sooner
            for _ in range(self.ingest_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        append_log(WORKER_LOG, f"{now_iso()} | WORKER_STOPPED")
        self._running = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def run_once(self):
        """Run a single iteration asynchronously (non-blocking for UI)."""
        t = threading.Thread(target=self._run_once_sync, daemon=True)
        t.start()
        return True

    def _run_once_sync(self):
        start_ts = now_iso()
        run_meta = {"start": start_ts, "insert": None, "migrate": None, "error": None}
        if INSERT_SCRIPT.exists():
            insert_cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(INSERT_SCRIPT))}"
            res = run_command(insert_cmd, timeout=None)
            run_meta["insert"] = res
            append_log(WORKER_LOG, f"{now_iso()} | RUN_ONCE_INSERT | rc={res.get('returncode')}")
        if MIGRATE_SCRIPT.exists():
            try:
                migrate_cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(MIGRATE_SCRIPT))}"
                res2 = run_command(migrate_cmd, timeout=None)
                run_meta["migrate"] = res2
                append_log(WORKER_LOG, f"{now_iso()} | RUN_ONCE_MIGRATE | rc={res2.get('returncode')}")
            except Exception as e:
                append_log(WORKER_ERR_LOG, f"{now_iso()} | RUN_ONCE_MIGRATE_EXCEPTION | {e}")
        with self._lock:
            self._last_run = run_meta
            self._last_run_time = now_az.isoformat(timespec="seconds")

    def get_status(self):
        with self._lock:
            last = self._last_run
            last_time = getattr(self, "_last_run_time", None)
            return {"running": self._running, "last_run": last, "last_run_time": last_time}

# ----------------------------
# Create a singleton worker via st.cache_resource
# ----------------------------
@st.cache_resource
def get_ingest_worker(ingest_interval: int = DEFAULT_INGEST_INTERVAL):
    w = BackgroundIngestWorker(ingest_interval=ingest_interval)
    w.start()
    return w

# Initialize worker (starts on page load — singleton)
worker = get_ingest_worker(ingest_interval=DEFAULT_INGEST_INTERVAL)

# ----------------------------
# Minimal UI (does not control the worker loop except to update migration toggle)
# ----------------------------
st.title("Background Ingest + Migration (always-on)")

st.markdown(
    """
    This page runs a background worker that executes `insert.py` every 10 seconds
    and then runs `migration.py` (if present). The worker runs in a thread and
    will NOT trigger reruns or block other Streamlit pages.
    """
)

col1, col2 = st.columns([2, 1])

with col1:
    st.write("Insert script:", str(INSERT_SCRIPT))
    st.write("Migration script:", str(MIGRATE_SCRIPT))
    st.write("Ingest interval (seconds):", DEFAULT_INGEST_INTERVAL)
    st.write("Worker thread alive:", worker._thread.is_alive() if worker._thread else False)

with col2:
    if st.button("Run one iteration now"):
        worker.run_once()
        st.success("Triggered one iteration (non-blocking).")

# Display last run info
st.markdown("---")
st.subheader("Worker last run status")
status = worker.get_status()
st.write("Running:", status.get("running"))
st.write("Last run time:", status.get("last_run_time") or "never")
last_run = status.get("last_run")
if last_run:
    st.write("Last run details:")
    st.json(last_run)

# Small tail of worker log files
st.markdown("---")
st.subheader("Recent worker log (worker.log)")
try:
    tail = WORKER_LOG.read_text(encoding="utf-8").splitlines()[-200:]
    st.code("\n".join(tail[-200:]) if tail else "(no logs yet)")
except Exception as e:
    st.code(f"(error reading worker.log: {e})")

st.subheader("Recent worker errors (worker.error.log)")
try:
    tail_err = WORKER_ERR_LOG.read_text(encoding="utf-8").splitlines()[-200:]
    st.code("\n".join(tail_err[-200:]) if tail_err else "(no errors yet)")
except Exception as e:
    st.code(f"(error reading worker.error.log: {e})")

st.caption(
    "Notes: This worker runs inside the Streamlit process as a daemon thread. "
    "It will stop when the Streamlit server stops or restarts. For production, "
    "run insert.py and migrations in a dedicated process/service."
)
