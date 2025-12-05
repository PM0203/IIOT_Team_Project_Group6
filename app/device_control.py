# app/device_control.py
import requests
import threading

def send_device_command(url: str, timeout: float = 2.0):
    """
    Non-blocking device HTTP GET call. Runs in a daemon thread so Streamlit UI won't block.
    """
    def _req(u):
        try:
            requests.get(u, timeout=timeout)
        except Exception:
            # swallow errors; you could log to file if desired
            pass

    t = threading.Thread(target=_req, args=(url,), daemon=True)
    t.start()
