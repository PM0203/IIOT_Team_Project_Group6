# app/live_component.py
import streamlit as st
from textwrap import dedent

def render_live_widget(http_url="http://127.0.0.1:8765/latest", pollInterval=1000):
    """
    Renders a small HTML widget (inside an iframe) that polls the given http_url
    every pollInterval milliseconds and updates the displayed sensor values.
    This keeps the Streamlit Python thread free (polling & UI update happen in browser).
    """
    html = dedent(f"""
    <div style="display:flex;justify-content:center;">
      <div id="live_widget" style="font-family:Inter, Arial, sans-serif; width:720px; border-radius:8px; padding:12px; background:#ffffff; box-shadow:0 2px 6px rgba(0,0,0,0.06);">
        <div style="display:flex;gap:12px;align-items:center;justify-content:space-between;">
          <div style="text-align:center;flex:1">
            <h4 style="margin:0">Sensor 1 (easy_log)</h4>
            <div id="s1_h" style="font-size:28px;color:#111827">—</div>
            <div id="s1_t" style="font-size:20px;color:#374151">—</div>
            <div id="s1_ts" style="font-size:12px;color:#6b7280">No Data</div>
          </div>
          <div style="width:1px;background:#e5e7eb;height:80px;margin:0 8px"></div>
          <div style="text-align:center;flex:1">
            <h4 style="margin:0">Sensor 2 (sense_hat)</h4>
            <div id="s2_h" style="font-size:28px;color:#111827">—</div>
            <div id="s2_t" style="font-size:20px;color:#374151">—</div>
            <div id="s2_ts" style="font-size:12px;color:#6b7280">No Data</div>
          </div>
          <div style="width:1px;background:#e5e7eb;height:80px;margin:0 8px"></div>
          <div style="text-align:center;min-width:160px">
            <h4 style="margin:0">Status</h4>
            <div id="status" style="font-size:14px;color:#0f766e">connecting…</div>
            <div id="last_update" style="font-size:12px;color:#6b7280">—</div>
          </div>
        </div>
      </div>
    </div>

    <script>
    (function() {{
      const url = "{http_url}";
      const poll = {pollInterval};
      const s1_h = document.getElementById("s1_h");
      const s1_t = document.getElementById("s1_t");
      const s1_ts = document.getElementById("s1_ts");
      const s2_h = document.getElementById("s2_h");
      const s2_t = document.getElementById("s2_t");
      const s2_ts = document.getElementById("s2_ts");
      const status = document.getElementById("status");
      const last_update = document.getElementById("last_update");

      async function fetchOnce() {{
        try {{
          const r = await fetch(url, {{cache: "no-store"}});
          if (!r.ok) {{
            status.textContent = "HTTP " + r.status;
            return;
          }}
          const js = await r.json();
          status.textContent = "connected";
          last_update.textContent = js.last_update ? ("Server: " + js.last_update) : "";
          // devices may or may not exist
          const d = js.devices || {{}};
          const s1 = d["easy_log"];
          const s2 = d["sense_hat"];

          if (!s1 || (s1.temperature_c === null && s1.humidity_pct === null)) {{
            s1_h.textContent = "No Data";
            s1_t.textContent = "";
            s1_ts.textContent = "";
          }} else {{
            s1_h.textContent = (s1.humidity_pct === null) ? "—" : (Math.round(s1.humidity_pct*10)/10) + " %";
            s1_t.textContent = (s1.temperature_c === null) ? "—" : (Math.round(s1.temperature_c*100)/100) + " °C";
            s1_ts.textContent = s1.last_ts ? new Date(s1.last_ts).toLocaleString() : "";
          }}

          if (!s2 || (s2.temperature_c === null && s2.humidity_pct === null)) {{
            s2_h.textContent = "No Data";
            s2_t.textContent = "";
            s2_ts.textContent = "";
          }} else {{
            s2_h.textContent = (s2.humidity_pct === null) ? "—" : (Math.round(s2.humidity_pct*10)/10) + " %";
            s2_t.textContent = (s2.temperature_c === null) ? "—" : (Math.round(s2.temperature_c*100)/100) + " °C";
            s2_ts.textContent = s2.last_ts ? new Date(s2.last_ts).toLocaleString() : "";
          }}
        }} catch (err) {{
          status.textContent = "fetch error";
          last_update.textContent = "";
        }}
      }}

      // initial fetch & then interval
      fetchOnce();
      if (window._liveWidgetInterval) clearInterval(window._liveWidgetInterval);
      window._liveWidgetInterval = setInterval(fetchOnce, poll);
    }})();
    </script>
    """)
    st.components.v1.html(html, height=160, scrolling=False)
