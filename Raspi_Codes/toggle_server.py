#!/usr/bin/env python3
"""
toggle_server.py

Endpoints:
  GET /on     -> run toggle_usb.py on, then probe uhubctl and return JSON
  GET /off    -> run toggle_usb.py off, then probe uhubctl and return JSON
  GET /status -> probe uhubctl and return JSON

This will try to call `uhubctl` (no sudo). If that fails it will try `sudo uhubctl`.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import json
import logging
import re
from typing import Tuple, Optional, Dict, Any

PORT = 8000
SCRIPT = "/home/group6/project/python/toggle_usb.py"   # your toggle script (unchanged)
TARGET_HUB_ID = "1-1"  # hub id to inspect (matches the -l value in your toggle script)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_toggle_script(action: str, timeout: float = 10.0) -> Dict[str, Any]:
    """Run your toggle_usb.py and capture output."""
    try:
        proc = subprocess.run(["python3", SCRIPT, action],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, check=False, timeout=timeout)
        return {"exit_code": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}
    except Exception as e:
        logging.exception("Failed running toggle script")
        return {"exit_code": None, "stdout": "", "stderr": str(e)}


def run_uhubctl_try(sudo_fallback: bool = True, timeout: float = 8.0) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Try to run uhubctl and return raw output (stdout+stderr) and metadata.
    First tries ["uhubctl"]. If it fails (FileNotFoundError or permission), optionally tries ["sudo","uhubctl"].
    """
    commands_to_try = []
    if sudo_fallback:
        commands_to_try.append(["sudo", "uhubctl"])

    for cmd in commands_to_try:
        try:
            logging.info("Attempting to run: %s", " ".join(cmd))
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, check=False, timeout=timeout)
            raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
            # If we actually got non-empty output, return it (even if exit_code != 0)
            if raw.strip():
                return raw, {"cmd": cmd, "exit_code": proc.returncode, "raw": raw}
            # If output empty but exit_code indicates something, still return raw to allow diagnostics
            return raw, {"cmd": cmd, "exit_code": proc.returncode, "raw": raw}
        except FileNotFoundError:
            logging.info("Command not found: %s", cmd[0])
            continue
        except Exception as e:
            logging.exception("Error running: %s", cmd)
            # continue to next fallback
            continue
    return None, {"error": "uhubctl not found or failed (tried with/without sudo)"}


def parse_uhubctl_for_target_hub(raw: str, hub_id: str = TARGET_HUB_ID) -> Dict[int, Dict[str, str]]:
    """
    Parse uhubctl raw output looking for the hub header that contains the hub_id (e.g. '1-1')
    and return a mapping {port_num: {"status": "power"/"off"/"unknown", "raw": "<text>"}} for that hub.
    """
    result: Dict[int, Dict[str, str]] = {}
    if not raw:
        return result

    lines = raw.splitlines()
    # header like: "Current status for hub 1-1 [2109:3431 USB2.0 Hub, ...]"
    header_re = re.compile(r"Current status for (.+?)\s*\[", re.IGNORECASE)
    port_re = re.compile(r"Port\s+(\d+):\s*([0-9A-Fa-fxX]+)?\s*(.*)$", re.IGNORECASE)

    in_target = False
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        mh = header_re.search(s)
        if mh:
            header_name = mh.group(1).strip()
            # match if hub_id appears in header (flexible)
            in_target = hub_id.lower() in header_name.lower()
            # if target, reset any previous
            if in_target:
                result = {}
            continue

        if not in_target:
            continue

        mp = port_re.search(s)
        if mp:
            port = int(mp.group(1))
            code = (mp.group(2) or "").strip()
            rest = (mp.group(3) or "").strip().lower()
            if "power" in rest:
                status = "power"
            elif "off" in rest:
                status = "off"
            else:
                # heuristics if no words: interpret common codes
                if code in ("0000", "0080"):
                    status = "off"
                elif code in ("0100",):
                    status = "power"
                else:
                    status = "unknown"
            result[port] = {"status": status, "raw": rest or code}
        else:
            # sometimes status appears in different format; try to pick out port number and 'power'/'off'
            if "port" in s.lower() and ("power" in s.lower() or "off" in s.lower()):
                m = re.search(r"port\s*(\d+)", s, re.IGNORECASE)
                if m:
                    port = int(m.group(1))
                    result.setdefault(port, {})["status"] = "power" if "power" in s.lower() else "off"
                    result[port]["raw"] = s
    return result


def overall_bool_from_ports(ports: Dict[int, Dict[str, str]]) -> Optional[bool]:
    """Return True if any port has status 'power', False if we parsed ports and none have power, None if no data."""
    if not ports:
        return None
    if any(info.get("status") == "power" for info in ports.values()):
        return True
    return False


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, code: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path
        logging.info("Request %s from %s", path, self.client_address[0])

        if path == "/on":
            cmd_res = run_toggle_script("on")
            raw, details = run_uhubctl_try()
            ports = parse_uhubctl_for_target_hub(raw or "", TARGET_HUB_ID)
            overall = overall_bool_from_ports(ports)
            resp = {"action": "on", "command_result": cmd_res, "status_probe": details, "ports": ports, "usb_enabled": overall}
            self._send_json(resp); return

        if path == "/off":
            cmd_res = run_toggle_script("off")
            raw, details = run_uhubctl_try()
            ports = parse_uhubctl_for_target_hub(raw or "", TARGET_HUB_ID)
            overall = overall_bool_from_ports(ports)
            resp = {"action": "off", "command_result": cmd_res, "status_probe": details, "ports": ports, "usb_enabled": overall}
            self._send_json(resp); return

        if path == "/status":
            raw, details = run_uhubctl_try()
            ports = parse_uhubctl_for_target_hub(raw or "", TARGET_HUB_ID)
            overall = overall_bool_from_ports(ports)
            resp = {"action": "status", "status_probe": details, "ports": ports, "usb_enabled": overall}
            self._send_json(resp); return

        if path in ("/", "/index.html"):
            info = {"endpoints": ["/on", "/off", "/status"], "note": "Uses toggle_usb.py and probes uhubctl for hub '1-1'."}
            self._send_json(info); return

        self._send_json({"error": "unknown endpoint"}, code=404)

    def log_message(self, format, *args):
        logging.info("%s - - %s", self.address_string(), format % args)


if __name__ == "__main__":
    logging.info("Starting server on 0.0.0.0:%d", PORT)
    httpd = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down")
        httpd.server_close()
