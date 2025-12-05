# app/utils.py
from datetime import datetime, timezone
from pathlib import Path

DIAG_LOG = Path("ingest/diagnostic.log")
DIAG_LOG.parent.mkdir(parents=True, exist_ok=True)

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def append_diag(msg: str):
    try:
        with open(DIAG_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {msg}\n")
    except Exception:
        pass
