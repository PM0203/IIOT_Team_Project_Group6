#!/usr/bin/env python3
"""
insert.py

Bulk ingest JSONL log files into Postgres "RAW DATA" table.

Behavior:
 - Walks logs/ (or a provided path) and finds .json .jsonl .log files
 - Parses each line (JSON) and extracts payload -> device_id and ts (ms)
 - Writes rows into "RAW DATA" with ON CONFLICT (device_id, event_ts_ms) DO NOTHING
 - Deletes each file after successful ingestion
 - Moves failed files to ingest/failed_files and logs errors
 - Keeps ingest/success.log and ingest/failed.log
 - Updates upload_status.json with counters and last_event_ts_ms

Requirements:
 - Python 3.8+
 - pip install psycopg2-binary
 - Environment: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""
from __future__ import annotations
import os
import sys
import json
import shutil
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

import psycopg2
from psycopg2.extras import execute_values

# Config
LOG_ROOT = Path("logs")         # default folder to scan
INGEST_DIR = Path("../ingest")     # folder for ingest logs and failed files
STATUS_FILE = Path("../upload_status.json")

SUCCESS_LOG = INGEST_DIR / "success.log"
FAILED_LOG = INGEST_DIR / "failed.log"
FAILED_FILES_DIR = INGEST_DIR / "failed_files"

# create ingest dirs
INGEST_DIR.mkdir(parents=True, exist_ok=True)
FAILED_FILES_DIR.mkdir(parents=True, exist_ok=True)


def pg_connect():
    """Connect to Postgres using env vars."""
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", 5432)),
        dbname=os.environ.get("PGDATABASE", "postgres"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "admin"),
    )


def ensure_unique_index(conn):
    """
    Ensure unique index on (device_id, event_ts_ms) exists.
    This is helpful to dedupe; safe to run multiple times.
    """
    sql = """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_rawdata_device_eventts
    ON "RAW DATA" (device_id, event_ts_ms);
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def update_status(file_name: str, inserted_count: int, max_event_ts_ms: Optional[int]):
    """Update upload_status.json with totals and last event ts seen."""
    data = {}
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    total_uploaded = data.get("total_uploaded", 0) + inserted_count
    data.update({
        "total_uploaded": total_uploaded,
        "last_upload_count": inserted_count,
        "last_file": file_name,
        "last_update": datetime.now().isoformat(timespec="seconds"),
    })
    if max_event_ts_ms is not None:
        data["last_event_ts_ms"] = max_event_ts_ms

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def log_success(file_name: str, inserted: int):
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"{ts} | SUCCESS | {file_name} | inserted={inserted}\n"
    with open(SUCCESS_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def log_failure(file_name: str, err: Exception, tb: str = ""):
    ts = datetime.now().isoformat(timespec="seconds")
    short_err = str(err).replace("\n", " ")
    with open(FAILED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} | FAILED | {file_name} | error={short_err}\n")
        if tb:
            f.write("TRACEBACK:\n")
            f.write(tb)
            f.write("\n---\n")


def parse_payload(payload_field) -> Tuple[Optional[str], Optional[int], str]:
    """
    Parse payload which may be:
      - a JSON string: '{"device_id":"sense_hat","ts":123...}'
      - a dict already
      - arbitrary string
    Returns (device_id, event_ts_ms, payload_raw)
    """
    payload_raw = payload_field if payload_field is not None else ""
    device_id = None
    event_ts_ms = None

    parsed = None
    if isinstance(payload_field, dict):
        parsed = payload_field
    elif isinstance(payload_field, str):
        try:
            parsed = json.loads(payload_field)
        except Exception:
            parsed = None

    if isinstance(parsed, dict):
        device_id = parsed.get("device_id") or parsed.get("id") or parsed.get("device")
        ts_candidate = parsed.get("ts") or parsed.get("timestamp") or parsed.get("time")
        if ts_candidate is not None:
            try:
                event_ts_ms = int(ts_candidate)
            except Exception:
                try:
                    event_ts_ms = int(float(ts_candidate))
                except Exception:
                    event_ts_ms = None

    return device_id, event_ts_ms, payload_raw


def count_rows_for_file(conn, source_file_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM "RAW DATA" WHERE source_file = %s', (source_file_name,))
        return cur.fetchone()[0]


def insert_file(conn, file_path: Path) -> Tuple[int, Optional[int]]:
    """
    Insert all candidates from the given JSONL file.
    Returns (inserted_count, max_event_ts_ms_seen).
    """
    candidates: List[tuple] = []
    max_event_ts_ms: Optional[int] = None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # treat whole line as payload if not JSON
                rec = {"payload": line}

            payload_field = rec.get("payload")
            device_id, event_ts_ms, payload_raw = parse_payload(payload_field)

            # fallback: infer device_id from topic if missing
            if not device_id:
                topic = rec.get("topic") or ""
                device_id = topic.split("/")[-1] if "/" in topic else (topic or None)

            event_ts_dt = None
            if event_ts_ms is not None:
                try:
                    event_ts_dt = datetime.fromtimestamp(event_ts_ms / 1000.0, )
                    if max_event_ts_ms is None or event_ts_ms > max_event_ts_ms:
                        max_event_ts_ms = event_ts_ms
                except Exception:
                    event_ts_dt = None

            candidates.append((
                rec.get("received_at"),
                rec.get("local_time"),
                rec.get("topic"),
                rec.get("qos"),
                rec.get("retain"),
                payload_raw if payload_raw is not None else (rec.get("payload") or ""),
                device_id,
                event_ts_ms,
                event_ts_dt,
                file_path.name,
                line_no
            ))

    if not candidates:
        return 0, None

    insert_sql = """
    INSERT INTO "RAW DATA"
    (received_at, local_time, topic, qos, retain, payload, device_id, event_ts_ms, event_ts, source_file, source_line_no)
    VALUES %s
    ON CONFLICT (device_id, event_ts_ms) DO NOTHING
    """

    # get before count: how many rows from this source_file already in DB
    before_count = count_rows_for_file(conn, file_path.name)

    with conn.cursor() as cur:
        execute_values(cur, insert_sql, candidates, page_size=1000)
    conn.commit()

    after_count = count_rows_for_file(conn, file_path.name)
    inserted_count = after_count - before_count
    return inserted_count, max_event_ts_ms


def process_path(path: Path, conn):
    """Process either a single file path or walk directory recursively."""
    if path.is_file():
        files = [path]
    else:
        files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".jsonl", ".log"}]

    total_inserted = 0
    for f in sorted(files):
        print(f"[INFO] Processing: {f}")
        try:
            inserted, max_ts = insert_file(conn, f)
            update_status(f.name, inserted, max_ts)
            log_success(f.name, inserted)
            total_inserted += inserted
            # delete file after successful ingestion
            try:
                f.unlink()
                print(f"[INFO] Deleted file: {f}")
            except Exception as e:
                print(f"[WARNING] Could not delete file {f}: {e}")
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"[ERROR] Failed to ingest {f}: {exc}")
            log_failure(f.name, exc, tb)
            # move file to failed_files for inspection
            try:
                dest = FAILED_FILES_DIR / f.name
                if dest.exists():
                    suffix = datetime.now().strftime("%Y%m%dT%H%M%S")
                    dest = FAILED_FILES_DIR / f"{f.stem}_{suffix}{f.suffix}"
                shutil.move(str(f), str(dest))
                print(f"[INFO] Moved failed file to: {dest}")
            except Exception as mv_e:
                print(f"[ERROR] Could not move failed file {f} to {FAILED_FILES_DIR}: {mv_e}")
    return total_inserted


def main():
    # default path (logs root) or one path provided on CLI
    path_arg = sys.argv[1] if len(sys.argv) > 1 else str(LOG_ROOT)
    path = Path(path_arg)

    if not path.exists():
        print(f"[ERROR] Path not found: {path}")
        sys.exit(1)

    try:
        conn = pg_connect()
    except Exception as e:
        print(f"[ERROR] Could not connect to Postgres: {e}")
        sys.exit(1)

    try:
        # ensure dedupe index exists (safe)
        try:
            ensure_unique_index(conn)
        except Exception as e:
            print(f"[WARNING] Could not create/check unique index: {e}")

        total = process_path(path, conn)
        print(f"[DONE] Total rows inserted this run: {total}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
