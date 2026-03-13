import streamlit as st
import requests
import subprocess
import threading
import time

API_BASE = "http://localhost:8080"
GRAFANA_BASE = "http://localhost:3000/d-solo/adsgzjt/edgewatch?orgId=1&refresh=5s&theme=dark&__feature.dashboardScene=true"
SERVERS = {
    "server_health": 8000,
    "server_degraded": 8001,
    "server_critical": 8002,
}

PANELS = {
    "Router Traffic Weights": 11,
    "Latency SLO Compliance": 10,
    "Error Budget Remaining %": 9,
    "Availability Burn Rate": 8,
    "Model Confidence": 7,
    "Success vs Error": 6,
    "Requests in Flight": 5,
    "Error Rate": 4,
    "p95 Latency": 3,
    "Error Logs": 1,
}

if "traffic_proc" not in st.session_state:
    st.session_state.traffic_proc = None

st.set_page_config(
    page_title="",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Minimal Dark CSS ──────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #111217; color: #d0d0d0; }
    .block-container { padding: 1.2rem 1.5rem; }
    h1,h2,h3 { color: #e0e0e0; }
    .section-title {
        font-size: 0.4rem;
        font-weight: 600;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #666;
        margin-bottom: 0.5rem;
        margin-top: 1.2rem;
        border-bottom: 1px solid #222;
        padding-bottom: 4px;
    }
    .server-card {
        background: #1a1d24;
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 6px;
        border-left: 3px solid #333;
        font-size: 0.5rem;
    }
    .server-card.online { border-left-color: #2ecc71; }
    .server-card.chaos { border-left-color: #e74c3c; }
    .server-card.offline { border-left-color: #e67e22; }
    .tag {
        display: inline-block;
        font-size: 0.65rem;
        padding: 1px 6px;
        border-radius: 3px;
        margin-left: 6px;
        font-weight: 600;
    }
    .tag-online { background: #1a3a2a; color: #2ecc71; }
    .tag-chaos { background: #3a1a1a; color: #e74c3c; }
    .tag-offline { background: #3a2a1a; color: #e67e22; }
    .stButton button {
        background: #1a1d24;
        color: #d0d0d0;
        border: 1px solid #333;
        border-radius: 4px;
        font-size: 0.78rem;
        padding: 4px 10px;
        width: 100%;
    }
    .stButton button:hover { background: #252830; border-color: #555; }
    .stSlider { padding: 0; }
    div[data-testid="stMetric"] {
        background: #1a1d24;
        border-radius: 6px;
        padding: 10px;
        border: 1px solid #222;
    }
    div[data-testid="stMetricValue"] { font-size: 1.1rem; color: #e0e0e0; }
    div[data-testid="stMetricLabel"] { font-size: 0.7rem; color: #888; }
    .ai-report {
        background: #1a1d24;
        border-radius: 6px;
        padding: 1rem 1.2rem;
        border: 1px solid #2a2d34;
        font-size: 0.85rem;
        line-height: 1.6;
    }
    iframe { border-radius: 6px; border: 1px solid #222; }
</style>
""", unsafe_allow_html=True)

# ── Helper functions ──────────────────────────────────
def get_weights():
    try:
        return requests.get(f"{API_BASE}/weights", timeout=3).json()
    except:
        return {"server_health": 0.6, "server_degraded": 0.3, "server_critical": 0.1}

def get_chaos(port):
    try:
        return requests.get(f"http://localhost:{port}/chaos/status", timeout=3).json().get("chaos", False)
    except:
        return None

def toggle_chaos(port):
    try:
        requests.post(f"http://localhost:{port}/chaos", timeout=3)
    except:
        pass

def set_weights(w):
    try:
        return requests.post(f"{API_BASE}/config", json=w,
            headers={"Content-Type": "application/json"}, timeout=3).json()
    except Exception as e:
        return {"error": str(e)}

def send_predict():
    try:
        return requests.get(f"{API_BASE}/predict", timeout=10).json()
    except Exception as e:
        return {"error": str(e)}

def run_eval():
    try:
        return requests.post(f"{API_BASE}/eval", timeout=120).json()
    except Exception as e:
        return {"error": str(e)}

def analyze():
    try:
        return requests.post(f"{API_BASE}/analyze", timeout=60).json()
    except Exception as e:
        return {"error": str(e)}

# ── Header ────────────────────────────────────────────
st.markdown("## Infra Observability")
st.caption("AI Edge Infrastructure Observability Platform")

st.divider()

# ── Row 1: Server Status + Weights ───────────────────
left, right = st.columns([1, 2])

with left:
    st.markdown("### Server Status")
    weights = get_weights()
    for name, port in SERVERS.items():
        chaos = get_chaos(port)
        w = weights.get(name, 0)
        status = "CHAOS" if chaos else ("OFFLINE" if w == 0 else "ONLINE")
        color = "status-chaos" if chaos else ("status-chaos" if w == 0 else "status-ok")
        st.markdown(f"""
        <div style='padding:10px; margin:6px 0; background:#f9f9f9; border-radius:6px; border-left: 3px solid {"#c0392b" if status != "ONLINE" else "#2d8a4e"}'>
            <b>{name}</b><br>
            <span class='{color}'>{status}</span> &nbsp;|&nbsp; Weight: <b>{int(w*100)}%</b> &nbsp;|&nbsp; Port: {port}
        </div>
        """, unsafe_allow_html=True)

with right:
    st.markdown("### Traffic Routing Weights")
    w = get_weights()
    c1, c2, c3 = st.columns(3)
    with c1:
        wh = st.slider("server_health", 0.0, 1.0, float(w.get("server_health", 0.6)), 0.05)
    with c2:
        wd = st.slider("server_degraded", 0.0, 1.0, float(w.get("server_degraded", 0.3)), 0.05)
    with c3:
        wc = st.slider("server_critical", 0.0, 1.0, float(w.get("server_critical", 0.1)), 0.05)

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Apply Weights"):
            result = set_weights({
                "server_health": wh,
                "server_degraded": wd,
                "server_critical": wc
            })
            st.success("Weights updated")
    with c2:
        if st.button("All to server_health"):
            set_weights({"server_health": 1.0, "server_degraded": 0.0, "server_critical": 0.0})
            st.success("All traffic routed to server_health")
            st.rerun()
    with c3:
        if st.button("Reset to Default"):
            set_weights({"server_health": 0.6, "server_degraded": 0.3, "server_critical": 0.1})
            st.success("Weights reset")
            st.rerun()

st.divider()

# ── Row 2: Chaos Controls + Test Request ─────────────
left, right = st.columns([1, 1])

with left:
    st.markdown("### Chaos Controls")
    for name, port in SERVERS.items():
        chaos = get_chaos(port)
        label = f"Disable Chaos — {name}" if chaos else f"Enable Chaos — {name}"
        if st.button(label, key=f"chaos_{port}"):
            toggle_chaos(port)
            st.rerun()

with right:
    st.markdown("## Test Request")
    st.caption("Send a single request through the router and see which server handled it")
    if st.button("Send Request"):
        result = send_predict()
        if "error" in result:
            st.error(result["error"])
        else:
            st.json(result)

st.divider()

# ── Row 3: Model Evaluation ───────────────────────────
st.markdown("## Model Evaluation")
st.caption("Runs 50 concurrent requests against each server and compares performance")

if st.button("Run Evaluation"):
    with st.spinner("Evaluating all servers — this takes ~30 seconds..."):
        result = run_eval()

    if "results" in result:
        rows = result["results"]
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        headers = ["Server", "p50 (ms)", "p95 (ms)", "p99 (ms)", "RPS", "Error Rate", "Confidence"]
        for col, h in zip([c1,c2,c3,c4,c5,c6,c7], headers):
            col.markdown(f"**{h}**")
        for r in rows:
            c1.write(r["node_id"])
            c2.write(r["p50_ms"])
            c3.write(r["p95_ms"])
            c4.write(r["p99_ms"])
            c5.write(r["throughput"])
            c6.write(r["error_rate"])
            c7.write(r["avg_confidence"])
    else:
        st.error(f"Evaluation failed: {result}")

st.divider()

# ── Row 4: AI Incident Analyzer ───────────────────────
st.markdown("## AI Incident Analyzer")
st.caption("Fetches live metrics from Prometheus and error logs from Loki, then generates a root cause report using Gemini AI")

if st.button("Analyze Incident"):
    with st.spinner("Collecting metrics and logs, consulting AI..."):
        result = analyze()

    if "analysis" in result:
        st.markdown("### Incident Report")
        st.markdown(result["analysis"])

        with st.expander("Raw context sent to AI"):
            st.json(result["context"])
    else:
        st.error(f"Analysis failed: {result}")

st.divider()
