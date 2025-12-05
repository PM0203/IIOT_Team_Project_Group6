#!/usr/bin/env python3
"""
Selenium -> MQTT publisher for EasyLog readings (resilient).

Behavior:
- Creates Chrome webdriver + MQTT client and publishes readings in a loop.
- If any error occurs (Selenium error, element missing, MQTT publish error,
  driver crash, network hiccup, etc.) the script will:
    1) cleanly close the driver and MQTT client,
    2) wait (with exponential backoff),
    3) recreate both and resume from the start (load ep4.htm then ep1.htm).
- Runs forever until you stop it (Ctrl-C).
"""

import time
import json
import traceback
import sys

import paho.mqtt.client as mqtt
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# --- Config: change these to match your setup ---
URL1 = "http://easylog.local/web/ep4.htm"
URL2 = "http://easylog.local/web/ep1.htm"

BROKER = "broker.hivemq.com"
PORT = 1883
GROUP = 6
DEVICE_ID = "easylog-01"           # <-- change this
CLIENTID = f"EasyLog_{GROUP}"

TOPIC_BASE = f"MSN/group{GROUP}/sensors"
TOPIC_DEVICE = f"{TOPIC_BASE}/{DEVICE_ID}"
PUBLISH_INTERVAL = 1.0   # seconds between publishes (match polling frequency)

# Selenium/Chromium locations (Pi)
CHROMIUM_BIN = "/usr/bin/chromium-browser"
CHROMEDRIVER_BIN = "/usr/bin/chromedriver"

# WebDriver wait timeouts
PAGE_LOAD_TIMEOUT = 15
ELEMENT_WAIT_TIMEOUT = 15

# Reconnection/backoff config
INITIAL_BACKOFF = 1.0    # seconds
MAX_BACKOFF = 60.0       # seconds

# --- MQTT callbacks ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected to broker")
        userdata["connected"] = True
    else:
        print("[MQTT] Failed to connect, rc=", rc)
        userdata["connected"] = False

def on_disconnect(client, userdata, rc):
    print("[MQTT] Disconnected (rc=%s)" % rc)
    userdata["connected"] = False

def on_publish(client, userdata, mid):
    # optional: print mids in debug
    # print(f"[MQTT] Published mid: {mid}")
    pass

def create_mqtt_client():
    userdata = {"connected": False}
    client = mqtt.Client(client_id=CLIENTID, userdata=userdata)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish
    # If you need username/password, set here:
    # client.username_pw_set(username="user", password="pass")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()
    return client, userdata

# --- Selenium driver (Pi-optimized) ---
def create_driver(headless=True):
    opts = Options()
    if headless:
        # use headless new mode if available
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--single-process")
    opts.add_argument("--window-size=1280,800")
    opts.binary_location = CHROMIUM_BIN
    service = Service(CHROMEDRIVER_BIN)
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver

def safe_quit_driver(driver):
    try:
        if driver:
            driver.quit()
    except Exception:
        # best effort
        try:
            driver.close()
        except Exception:
            pass

def safe_stop_mqtt(client, userdata):
    try:
        if client:
            client.loop_stop()
            client.disconnect()
            # give the client a moment to close
            time.sleep(0.2)
    except Exception:
        pass
    if userdata is not None:
        userdata["connected"] = False

# --- main loop that fully restarts on any error ---
def run_once():
    """
    Create driver + mqtt client, run the publish loop.
    If an exception occurs, raise it so the outer loop can cleanup and retry.
    """
    client, userdata = create_mqtt_client()
    driver = None

    try:
        driver = create_driver(headless=True)

        print("Opening ep4.htm...")
        driver.get(URL1)
        WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print("ep4.htm loaded.")
        time.sleep(1)

        print("Loading ep1.htm...")
        driver.get(URL2)

        # Wait for reading elements to appear
        WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CLASS_NAME, "channel-0-reading"))
        )
        WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CLASS_NAME, "channel-1-reading"))
        )
        print("Reading elements found. Starting publish loop...")

        # publish loop
        while True:
            ts_ms = int(time.time() * 1000)
            # If MQTT disconnected, raise to force restart (so it reconnects cleanly)
            if not userdata.get("connected", False):
                raise RuntimeError("MQTT disconnected")

            try:
                ch0_elem = driver.find_element(By.CLASS_NAME, "channel-0-reading")
                ch1_elem = driver.find_element(By.CLASS_NAME, "channel-1-reading")
                ch0_raw = ch0_elem.text if ch0_elem is not None else None
                ch1_raw = ch1_elem.text if ch1_elem is not None else None

                def parse_val(raw):
                    if raw is None:
                        return None
                    try:
                        cleaned = raw.replace("°", "").replace("%", "").strip()
                        return float(cleaned)
                    except Exception:
                        return raw.strip()

                ch0 = parse_val(ch0_raw)
                ch1 = parse_val(ch1_raw)

                payload = {
                    "device_id": DEVICE_ID,
                    "temperature": ch0,
                    "humidity": ch1,
                    "ts": ts_ms
                }
                payload_str = json.dumps(payload)

                # publish and check result
                # publish returns (result, mid) where result==0 means success (depending on network)
                res1 = client.publish(TOPIC_DEVICE, payload_str, qos=0)
                res2 = client.publish(TOPIC_BASE, payload_str, qos=0)

                # res1/res2 are MQTTMessageInfo; check rc attribute where available (call rc property if exists)
                # We will check userdata.connected for reliability and also inspect .rc if attribute exists.
                if hasattr(res1, "rc") and res1.rc != 0:
                    raise RuntimeError(f"MQTT publish failed rc={res1.rc}")

                # debug print
                print(f"Published to {TOPIC_DEVICE}: {payload_str}")

            except Exception as e:
                # bubble up to cause a full restart
                print("Error during read/publish; will restart driver+mqtt:", e)
                traceback.print_exc()
                raise

            time.sleep(PUBLISH_INTERVAL)

    finally:
        # cleanup everything
        print("Cleaning up driver and MQTT client...")
        safe_quit_driver(driver)
        safe_stop_mqtt(client, userdata)
        print("Cleanup complete.")

def main():
    backoff = INITIAL_BACKOFF
    while True:
        try:
            print("=== Starting new connection attempt ===")
            run_once()
            # if run_once returns normally (unlikely), reset backoff
            backoff = INITIAL_BACKOFF
        except KeyboardInterrupt:
            print("Interrupted by user. Exiting.")
            try:
                # best-effort cleanup (run_once already tries to clean)
                pass
            finally:
                sys.exit(0)
        except Exception as e:
            print("Run failed with error:", e)
            traceback.print_exc()
            print(f"Waiting {backoff:.1f}s before retrying...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
            print("Retrying now...")

if __name__ == "__main__":
    main()
