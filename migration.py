#migration.py
"""
migrate_raw_to_sensor_data.py

Migrate data from "RAW DATA" -> sensor_data and sensors tables.

Usage:
    export PGHOST=localhost
    export PGPORT=5432
    export PGDATABASE=IIOT
    export PGUSER=postgres
    export PGPASSWORD=admin

    python migrate_raw_to_sensor_data.py
"""
from __future__ import annotations
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple, List

import psycopg2
from psycopg2.extras import execute_values

# DB connection using env vars
def pg_connect():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", 5432)),
        dbname=os.environ.get("PGDATABASE", "postgres"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "admin"),
    )

def parse_payload(payload_field) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Return (temperature, humidity, payload_raw).
    Payload may be:
      - a JSON string ('{"temperature":26.2,"humidity":35.7,...}')
      - a dict already
      - arbitrary string
    """
    payload_raw = payload_field if payload_field is not None else ""
    parsed = None
    if isinstance(payload_field, dict):
        parsed = payload_field
    elif isinstance(payload_field, str):
        try:
            parsed = json.loads(payload_field)
        except Exception:
            parsed = None

    temp = None
    hum = None
    if isinstance(parsed, dict):
        # tolerant key lookup
        temp = parsed.get("temperature") or parsed.get("temp") or parsed.get("t")
        hum = parsed.get("humidity") or parsed.get("hum") or parsed.get("h")
        # ensure numeric
        try:
            temp = float(temp) if temp is not None else None
        except Exception:
            temp = None
        try:
            hum = float(hum) if hum is not None else None
        except Exception:
            hum = None

    return temp, hum, payload_raw

def migrate_batch(conn, rows: List[tuple]):
    """
    Insert a batch of parsed rows into sensor_data and upsert sensors metadata.
    Each tuple in rows: (device_id, event_ts (datetime), temperature (float), humidity (float), source_file, source_line_no)
    """
    if not rows:
        return 0

    # Bulk insert into sensor_data with ON CONFLICT DO NOTHING
    insert_sql = """
    INSERT INTO sensor_data
    (device_id, event_ts, temperature, humidity, source_file, source_line_no)
    VALUES %s
    ON CONFLICT (device_id, event_ts) DO NOTHING
    """
    with conn.cursor() as cur:
        execute_values(cur, insert_sql, rows, page_size=1000)

    # Update sensors table: we will upsert device rows with first_seen/last_seen using min/max of event_ts
    # Build an aggregation dict {device: (min_ts, max_ts)}
    agg = {}
    for device_id, event_dt, temp, hum, sf, ln in rows:
        if not device_id or event_dt is None:
            continue
        if device_id not in agg:
            agg[device_id] = (event_dt, event_dt)
        else:
            mn, mx = agg[device_id]
            if event_dt < mn: mn = event_dt
            if event_dt > mx: mx = event_dt
            agg[device_id] = (mn, mx)

    # Upsert sensors entries
    upsert_sql = """
    INSERT INTO sensors (device_id, first_seen, last_seen, topic)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (device_id) DO UPDATE
      SET first_seen = LEAST(COALESCE(sensors.first_seen, EXCLUDED.first_seen), EXCLUDED.first_seen),
          last_seen  = GREATEST(COALESCE(sensors.last_seen, EXCLUDED.last_seen), EXCLUDED.last_seen)
    """
    with conn.cursor() as cur:
        for device_id, (mn, mx) in agg.items():
            # topic unknown here; leave null. If you have topics, you can add.
            cur.execute(upsert_sql, (device_id, mn, mx, None))

    conn.commit()
    return len(rows)

def run_migration(batch_size: int = 1000, limit_rows: Optional[int] = None):
    conn = pg_connect()
    try:
        cur = conn.cursor()

        # Select rows from RAW DATA that have an event_ts (non-null) and device info
        # We will read in batches to avoid blowing memory.
        select_sql = """
        SELECT received_at, local_time, topic, payload, device_id, event_ts, event_ts_ms, source_file, source_line_no
        FROM "RAW DATA"
        WHERE event_ts IS NOT NULL
        ORDER BY event_ts ASC
        """
        if limit_rows:
            select_sql += f" LIMIT {int(limit_rows)}"

        cur.execute(select_sql)
        total_inserted = 0
        batch = []

        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for r in rows:
                received_at, local_time, topic, payload_field, device_id, event_ts, event_ts_ms, source_file, source_line_no = r

                # If device_id missing, try to infer from payload or topic
                did = device_id
                if not did:
                    # try payload
                    try:
                        if isinstance(payload_field, str):
                            payload_json = json.loads(payload_field)
                        elif isinstance(payload_field, dict):
                            payload_json = payload_field
                        else:
                            payload_json = None
                    except Exception:
                        payload_json = None
                    if payload_json:
                        did = payload_json.get("device_id") or payload_json.get("id")
                if not did:
                    # fallback to last segment of topic
                    if topic:
                        did = topic.split("/")[-1] if "/" in topic else topic

                if not did or not event_ts:
                    # skip rows that cannot produce device + timestamp (cannot create PK)
                    continue

                # parse payload to extract temp/humidity
                temp, hum, payload_raw = parse_payload(payload_field)

                # ensure event_ts is a python datetime
                event_dt = event_ts
                if isinstance(event_dt, str):
                    try:
                        event_dt = datetime.fromisoformat(event_dt)
                    except Exception:
                        # try fallback via psycopg2-friendly parsing
                        try:
                            from dateutil import parser as _p
                            event_dt = _p.parse(event_dt)
                        except Exception:
                            event_dt = None

                # Only migrate if we have a datetime event_dt
                if not event_dt:
                    continue

                batch.append((did, event_dt, temp, hum, source_file, source_line_no))

            if batch:
                # prepare tuples for insert: sensor_data expects (device_id, event_ts, temp, hum, source_file, source_line_no)
                rows_for_insert = [(d, ts, t, h, sf, ln) for (d, ts, t, h, sf, ln) in batch]
                inserted = migrate_batch(conn, rows_for_insert)
                total_inserted += inserted
                print(f"[INFO] Migrated batch: candidates={len(batch)} inserted={inserted} total={total_inserted}")
                batch = []

        print(f"[DONE] Total inserted into sensor_data: {total_inserted}")

    finally:
        conn.close()

if __name__ == "__main__":
    # Adjust batch_size or limit_rows as needed
    run_migration(batch_size=1000, limit_rows=None)
