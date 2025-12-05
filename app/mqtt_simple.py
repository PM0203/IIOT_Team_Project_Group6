# app/mqtt_simple.py
"""
Simple MQTT subscriber with short history per device (deque) and averaging.

Usage:
    from app.mqtt_simple import get_mqtt_simple
    sub = get_mqtt_simple(start=True)
    rec = sub.get_avg("easy_log", window_seconds=30)  # -> {"temperature_c": .., "humidity_pct": .., "last_ts": datetime} or None
"""
from __future__ import annotations
import threading
import json
import time
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from typing import Optional, Dict, Any, Tuple
import paho.mqtt.client as mqtt

# Config
DEFAULT_BROKER = "broker.hivemq.com"
DEFAULT_PORT = 1883
DEFAULT_TOPIC = "MSN/group6/#"
DEFAULT_MAX_SAMPLES = 1000  # per-device deque maxlen

# Internal store
_lock = threading.Lock()
_store: Dict[str, deque] = defaultdict(lambda: deque(maxlen=DEFAULT_MAX_SAMPLES))
_started = False
_client_thread = None
_client = None

def _now_utc():
    return datetime.now(timezone.utc)

def _parse_payload(payload_text: str) -> Tuple[Optional[float], Optional[float]]:
    """Try JSON first, then common keys, then simple regex heuristics."""
    temp = None
    hum = None
    # JSON attempt
    try:
        obj = json.loads(payload_text)
        if isinstance(obj, dict):
            for k in ("temperature_c", "temperature", "temp", "t"):
                if k in obj:
                    try:
                        temp = float(obj[k])
                        break
                    except Exception:
                        temp = None
            for k in ("humidity_pct", "humidity", "hum", "h"):
                if k in obj:
                    try:
                        hum = float(obj[k])
                        break
                    except Exception:
                        hum = None
            # sometimes payload nested under 'payload'
            if (temp is None or hum is None) and isinstance(obj.get("payload"), dict):
                inner = obj.get("payload")
                for k in ("temperature_c", "temperature", "temp", "t"):
                    if k in inner:
                        try:
                            temp = float(inner[k]); break
                        except Exception:
                            temp = None
                for k in ("humidity_pct", "humidity", "hum", "h"):
                    if k in inner:
                        try:
                            hum = float(inner[k]); break
                        except Exception:
                            hum = None
    except Exception:
        pass

    # Regex fallback for simple text like "temp:24.3 hum:48.8" or "t=24 h=48"
    if temp is None:
        try:
            m = re.search(r"t(?:emp(?:erature)?)?[:=]\s*([0-9]+(?:\.[0-9]+)?)", payload_text, re.I)
            if m:
                temp = float(m.group(1))
        except Exception:
            temp = None
    if hum is None:
        try:
            m2 = re.search(r"h(?:um(?:idity)?)?[:=]\s*([0-9]+(?:\.[0-9]+)?)", payload_text, re.I)
            if m2:
                hum = float(m2.group(1))
        except Exception:
            hum = None

    return temp, hum

def _infer_device_id(parsed: Optional[dict], topic: str) -> str:
    if isinstance(parsed, dict):
        for k in ("device_id", "device", "id", "dev", "name"):
            if k in parsed and isinstance(parsed[k], str):
                return parsed[k]
    # fallback to last topic segment
    try:
        if "/" in topic:
            return topic.strip().split("/")[-1]
    except Exception:
        pass
    return topic or "unknown"

def _on_connect(client, userdata, flags, rc):
    try:
        if rc == 0:
            client.subscribe(DEFAULT_TOPIC)
    except Exception:
        pass

def _on_message(client, userdata, msg):
    now = _now_utc()
    try:
        payload_text = msg.payload.decode("utf-8", errors="replace")
    except Exception:
        payload_text = str(msg.payload)

    parsed = None
    try:
        parsed = json.loads(payload_text)
    except Exception:
        parsed = None

    device_id = _infer_device_id(parsed, msg.topic)
    temp, hum = _parse_payload(payload_text)

    # append a sample tuple: (timestamp, temp, hum, payload_text, topic)
    with _lock:
        _store[device_id].append((now, temp, hum, payload_text, msg.topic))

def _run_mqtt(broker=DEFAULT_BROKER, port=DEFAULT_PORT, topic=DEFAULT_TOPIC):
    global _client
    client = mqtt.Client(client_id=f"mqtt_simple_{int(time.time())}")
    client.on_connect = _on_connect
    client.on_message = _on_message
    try:
        client.connect(broker, port, keepalive=60)
    except Exception:
        # connect failed; exit thread (caller can retry by restarting singleton)
        return
    _client = client
    client.loop_forever()

class MQTTSimple:
    def __init__(self, broker=DEFAULT_BROKER, port=DEFAULT_PORT, topic=DEFAULT_TOPIC, max_samples=DEFAULT_MAX_SAMPLES):
        self.broker = broker
        self.port = port
        self.topic = topic
        self.max_samples = max_samples

    def start(self):
        global _started, _client_thread
        if _started:
            return
        t = threading.Thread(target=_run_mqtt, args=(self.broker, self.port, self.topic), daemon=True)
        t.start()
        _client_thread = t
        _started = True

    def get_latest(self, device_id: str) -> Optional[Dict[str, Any]]:
        with _lock:
            dq = _store.get(device_id)
            if not dq:
                return None
            ts, t, h, payload, topic = dq[-1]
            return {"payload": payload, "ts": ts, "temperature_c": t, "humidity_pct": h, "topic": topic}

    def get_avg(self, device_id: str, window_seconds: int = 30) -> Optional[Dict[str, Any]]:
        """Return averages over the last `window_seconds` seconds, or None if no samples."""
        now = _now_utc()
        cutoff = now - timedelta(seconds=int(window_seconds))
        temps = []
        hums = []
        last_ts = None
        with _lock:
            dq = _store.get(device_id)
            if not dq:
                return None
            # iterate from newest to oldest for efficiency
            for ts, t, h, payload, topic in reversed(dq):
                if ts < cutoff:
                    break
                last_ts = ts if last_ts is None else (ts if ts > last_ts else last_ts)
                if t is not None:
                    temps.append(float(t))
                if h is not None:
                    hums.append(float(h))
        if last_ts is None:
            return None
        avg_t = (sum(temps)/len(temps)) if temps else None
        avg_h = (sum(hums)/len(hums)) if hums else None
        return {"temperature_c": avg_t, "humidity_pct": avg_h, "last_ts": last_ts}

    def get_all_avgs(self, window_seconds: int = 30) -> Dict[str, Dict]:
        """Return averages for all known devices."""
        res = {}
        with _lock:
            keys = list(_store.keys())
        for k in keys:
            a = self.get_avg(k, window_seconds=window_seconds)
            res[k] = a
        return res

# module-level singleton
_singleton = None
_singleton_lock = threading.Lock()

def get_mqtt_simple(start: bool = False, broker: str = DEFAULT_BROKER, port: int = DEFAULT_PORT, topic: str = DEFAULT_TOPIC) -> MQTTSimple:
    """
    Get singleton. If start=True it will start the background MQTT client thread (safe to call multiple times).
    """
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = MQTTSimple(broker=broker, port=port, topic=topic)
        if start:
            _singleton.start()
    return _singleton
