# app/clock_fragment.py
"""
Analog clock widget embedded as HTML/JS.
This updates in the browser every second and does NOT cause Streamlit reruns.
Call render_clock() from your page where you want the clock to appear.
"""
import streamlit as st
from textwrap import dedent

_CLOCK_HTML = dedent("""
<div style="display:flex;justify-content:center;margin-top:8px;margin-bottom:8px;">
  <canvas id="analogClock" width="110" height="110" style="border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.12);"></canvas>
</div>
<script>
(function() {
  const canvas = document.getElementById('analogClock');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const radius = canvas.height / 2;
  ctx.translate(radius, radius);
  const drawClock = () => {
    const now = new Date();
    drawFace(ctx, radius);
    drawNumbers(ctx, radius);
    drawTime(ctx, radius, now);
  };

  function drawFace(ctx, radius) {
    ctx.beginPath();
    ctx.arc(0, 0, radius * 0.98, 0, 2 * Math.PI);
    const grad = ctx.createRadialGradient(0,0,radius*0.95, 0,0,radius*1.05);
    grad.addColorStop(0, '#ffffff');
    grad.addColorStop(0.5, '#f3f4f6');
    grad.addColorStop(1, '#e5e7eb');
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.strokeStyle = '#9ca3af';
    ctx.lineWidth = radius * 0.03;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(0, 0, radius * 0.05, 0, 2 * Math.PI);
    ctx.fillStyle = '#111827';
    ctx.fill();
  }

  function drawNumbers(ctx, radius) {
    const angStep = Math.PI / 6;
    ctx.font = radius * 0.12 + "px sans-serif";
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    for (let num = 1; num <= 12; num++) {
      const ang = num * angStep;
      ctx.rotate(ang);
      ctx.translate(0, -radius * 0.78);
      ctx.rotate(-ang);
      ctx.fillStyle = "#111827";
      ctx.fillText(num.toString(), 0, 0);
      ctx.rotate(ang);
      ctx.translate(0, radius * 0.78);
      ctx.rotate(-ang);
    }
  }

  function drawTime(ctx, radius, now) {
    let hour = now.getHours();
    let minute = now.getMinutes();
    let second = now.getSeconds();
    // hour
    hour = hour % 12;
    hour = (hour * Math.PI / 6) + (minute * Math.PI / (6 * 60)) + (second * Math.PI / (360 * 60));
    drawHand(ctx, hour, radius * 0.5, radius * 0.06, '#111827');
    // minute
    const minuteAngle = (minute * Math.PI / 30) + (second * Math.PI / (30 * 60));
    drawHand(ctx, minuteAngle, radius * 0.75, radius * 0.045, '#111827');
    // second
    const secondAngle = (second * Math.PI / 30);
    drawHand(ctx, secondAngle, radius * 0.88, radius * 0.015, '#dc2626');
    // ticks
    for (let i=0;i<60;i++){
      const ang = i * Math.PI/30;
      ctx.beginPath();
      const inner = (i % 5 === 0) ? radius*0.88 : radius*0.92;
      const outer = radius*0.97;
      ctx.lineWidth = (i % 5 === 0) ? 3 : 1;
      ctx.strokeStyle = '#6b7280';
      ctx.moveTo(inner * Math.cos(ang), inner * Math.sin(ang));
      ctx.lineTo(outer * Math.cos(ang), outer * Math.sin(ang));
      ctx.stroke();
    }
  }

  function drawHand(ctx, pos, length, width, color) {
    ctx.beginPath();
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.strokeStyle = color;
    ctx.moveTo(0, 0);
    ctx.rotate(pos);
    ctx.lineTo(0, -length);
    ctx.stroke();
    ctx.rotate(-pos);
  }

  // initial draw + update every second
  drawClock();
  if (window._analogClockInterval) clearInterval(window._analogClockInterval);
  window._analogClockInterval = setInterval(drawClock, 1000);
})();
</script>
""")

def render_clock():
    """
    Embed the analog clock HTML. This runs in-browser and updates independently.
    Call this at the top of your main page (before data fragment) to show a centered clock.
    """
    # Use safe mode to allow HTML+JS execution in the iframe created by Streamlit components.
    st.components.v1.html(_CLOCK_HTML, height=260, scrolling=False)
