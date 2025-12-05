#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import os
import signal
import time
from urllib.parse import urlparse, parse_qs

PORT = 8081
SCRIPT = "/home/group6/project/python/toggle_usb.py"

# Directory where publisher.py and easylog_mqtt_pooler.py live (assumes same folder as this server)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Process handles (None when not running)
publisher_proc = None
pooler_proc = None

# Helper to run local USB script (keeps existing behaviour)
def run_script(action):
    subprocess.run(["python", SCRIPT, action], check=False)

# --- Process management helpers -------------------------------------------------
def start_process(name):
    global publisher_proc, pooler_proc
    if name == "publisher":
        if publisher_proc and publisher_proc.poll() is None:
            return (False, "publisher already running")
        path = os.path.join(BASE_DIR, "publisher.py")
        publisher_proc = subprocess.Popen(["python3", path], cwd=BASE_DIR)
        return (True, f"publisher started (pid={publisher_proc.pid})")
    elif name == "pooler":
        if pooler_proc and pooler_proc.poll() is None:
            return (False, "easylog_mqtt_pooler already running")
        path = os.path.join(BASE_DIR, "easylog_mqtt_pooler.py")
        pooler_proc = subprocess.Popen(["python3", path], cwd=BASE_DIR)
        return (True, f"easylog_mqtt_pooler started (pid={pooler_proc.pid})")
    else:
        return (False, "unknown process")

def stop_process(name, timeout=5.0):
    global publisher_proc, pooler_proc
    if name == "publisher":
        proc = publisher_proc
    elif name == "pooler":
        proc = pooler_proc
    else:
        return (False, "unknown process")

    if not proc or proc.poll() is not None:
        return (False, f"{name} not running")

    try:
        proc.terminate()  # SIGTERM
    except Exception as e:
        return (False, f"error terminating: {e}")

    # wait up to timeout seconds for graceful exit
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            break
        time.sleep(0.1)

    if proc.poll() is None:
        # still alive -> force kill
        try:
            proc.kill()
        except Exception as e:
            return (False, f"error killing process: {e}")

    # clear global ref
    if name == "publisher":
        publisher_proc = None
    else:
        pooler_proc = None

    return (True, f"{name} stopped")

def restart_process(name):
    stopped, msg = stop_process(name)
    # even if stop failed because "not running", we still try to start
    started, msg2 = start_process(name)
    return (started, f"stop -> {msg} ; start -> {msg2}")

def status_process(name):
    global publisher_proc, pooler_proc
    if name == "publisher":
        proc = publisher_proc
    elif name == "pooler":
        proc = pooler_proc
    else:
        return (False, "unknown process")

    if not proc:
        return (True, f"{name} not running")
    rc = proc.poll()
    if rc is None:
        return (True, f"{name} running (pid={proc.pid})")
    else:
        return (True, f"{name} stopped (exitcode={rc})")

# ------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # USB endpoints (existing)
        if path == "/on":
            run_script("on")
            self.respond("USB ON")
            return
        if path == "/off":
            run_script("off")
            self.respond("USB OFF")
            return
        if path == "/toggle":
            run_script("toggle")
            self.respond("USB TOGGLED")
            return

        # Process control endpoints for publisher and pooler:
        # /start-publisher, /stop-publisher, /restart-publisher, /status-publisher
        # /start-pooler,   /stop-pooler,   /restart-pooler,   /status-pooler
        if path.startswith("/start-"):
            target = path.replace("/start-", "")
            ok, msg = start_process(target)
            self.respond(msg, 200 if ok else 400)
            return

        if path.startswith("/stop-"):
            target = path.replace("/stop-", "")
            ok, msg = stop_process(target)
            self.respond(msg, 200 if ok else 400)
            return

        if path.startswith("/restart-"):
            target = path.replace("/restart-", "")
            ok, msg = restart_process(target)
            self.respond(msg, 200 if ok else 400)
            return

        if path.startswith("/status-"):
            target = path.replace("/status-", "")
            ok, msg = status_process(target)
            self.respond(msg, 200 if ok else 400)
            return

        # simple index page to show available endpoints
        if path in ("/", "/index"):
            body = (
                "Available endpoints:\n\n"
                "/on\n/off\n/toggle\n\n"
                "/start-publisher\n/stop-publisher\n/restart-publisher\n/status-publisher\n\n"
                "/start-pooler\n/stop-pooler\n/restart-pooler\n/status-pooler\n"
            )
            self.respond(body)
            return

        self.respond("Invalid endpoint", 404)

    def respond(self, message, code=200):
        self.send_response(code)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(message.encode())

if __name__ == "__main__":
    print(f"Server running on http://0.0.0.0:{PORT}")
    httpd = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down HTTP server...")
        httpd.server_close()
        # try to stop child processes cleanly
        for n in ("publisher", "pooler"):
            ok, msg = stop_process(n)
            print(f"stop {n}: {msg}")
