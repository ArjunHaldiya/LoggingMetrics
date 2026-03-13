import google.generativeai as genai
import os
from fastapi import FastAPI, Body, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
import httpx
import random, time, json, logging
import asyncio
from contextlib import asynccontextmanager
from prometheus_client import Gauge

PROMETHEUS_URL = "http://prometheus:9090"


def update_weight_metrics():
    for node_id, weight in weights.items():
        ROUTING_WEIGHT.labels(node_id=node_id).set(weight)


weights = {
    "server_health" : 0.60,
    "server_degraded": 0.30,
    "server_critical" : 0.10
}


ROUTING_WEIGHT = Gauge(
    'router_server_weight',
    'Current routing weight per server',
    ['node_id']
)

update_weight_metrics()

async def fetch_context():
    context = {}
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query",
            params = {"query" : 'sum(rate(requests_total_custom_total{outcome="error"}[2m])) by (node_id)'},
            timeout= 5.0)
        context["error_rates"] = r.json()["data"]["result"]
        
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query",
            params = {"query" : 'histogram_quantile(0.95, sum(rate(healthy_predict_latency_seconds_bucket[2m])) by (le))'},
            timeout= 5.0)
        context["p95_healthy"] = r.json()["data"]["result"]
        
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query",
            params = {"query" : 'histogram_quantile(0.95, sum(rate(degraded_predict_latency_seconds_bucket[2m])) by (le))'},
            timeout= 5.0)
        context["p95_degraded"] = r.json()["data"]["result"]
        
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query",
            params = {"query" : 'histogram_quantile(0.95, sum(rate(critical_predict_latency_seconds_bucket[2m])) by (le))'},
            timeout= 5.0)
        context["p95_critical"] = r.json()["data"]["result"]
        
        r = await client.get(
            "http://loki:3100/loki/api/v1/query_range",
            params={
                "query": '{container=~"/edgewatch-server.*"} | json | status_code=`503`',
                "limit": 20,
                "start": str(int(time.time() - 300) * 1000000000),
                "end": str(int(time.time()) * 1000000000)
            },
            timeout=5.0)
        
        loki_data = r.json()
        logs = []
        for stream in loki_data.get("data", {}).get("result", []):
            for entry in stream.get("values", []):
                logs.append(entry[1])
        context["recent_error_logs"] = logs[:20]
    context["current_weights"] = weights
    return context
        
async def check_server_health():
    while True:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": 'sum(rate(requests_total_custom_total{outcome="error"}[1m])) by (node_id)'},
                    timeout=5.0
                )
                data = response.json()
                results = data["data"]["result"]

                total_query = await client.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": 'sum(rate(requests_total_custom_total[1m])) by (node_id)'},
                    timeout=5.0
                )
                total_data = total_query.json()["data"]["result"]

                # Build total requests per node
                totals = {r["metric"]["node_id"]: float(r["value"][1]) for r in total_data}

                for result in results:
                    node_id = result["metric"]["node_id"]
                    error_rate = float(result["value"][1])
                    total = totals.get(node_id, 1)
                    error_pct = error_rate / total if total > 0 else 0

                    print(json.dumps({
                        "event": "health_check",
                        "node_id": node_id,
                        "error_pct": round(error_pct, 3),
                        "timestamp": time.time()
                    }))

                    if error_pct > 0.20 and weights.get(node_id, 0) > 0:
                        print(json.dumps({
                            "event": "auto_reroute",
                            "node_id": node_id,
                            "reason": f"error_rate={error_pct:.1%}",
                            "action": "weight_set_to_0"
                        }))
                        weights[node_id] = 0.0
                    elif error_pct < 0.05 and weights.get(node_id, 0) == 0:
                        default_weights = {
                            "server_health" : 0.60,
                            "server_degraded": 0.30,
                            "server_critical" : 0.10
                        }
                        weights[node_id] = default_weights[node_id]
                        print(json.dumps({
                            "event" : "auto_recover",
                            "node_id":node_id,
                            "reason" : f"error_rate = {error_pct:.1%}",
                            "action" : f"weight_restored_to_{default_weights[node_id]}"
                        }))
                    update_weight_metrics()

        except Exception as e:
            print(f"Health check failed: {e}")

        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(check_server_health())
    yield

async def eval_server(node_id, url, n_requests=50):
    latencies = []
    errors = 0
    confidences = []

    async with httpx.AsyncClient() as client:
        tasks = [client.get(url, timeout=10.0) for _ in range(n_requests)]
        start = time.time()
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.time() - start

    for r in responses:
        if isinstance(r, Exception):
            errors += 1
        elif r.status_code != 200:
            errors += 1
        else:
            latencies.append(r.elapsed.total_seconds() * 1000)
            try:
                data = r.json()
                if "confidence" in data:
                    confidences.append(data["confidence"])
            except:
                pass

    if not latencies:
        return None

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    throughput = n_requests / duration
    error_rate = errors / n_requests
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0

    return {
        "node_id": node_id,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "throughput": round(throughput, 2),
        "error_rate": round(error_rate, 3),
        "avg_confidence": round(avg_confidence, 3)
    }

app = FastAPI(title="Router", lifespan=lifespan)


Instrumentator().instrument(app).expose(app)
def log_dump(node_id):
    print(json.dumps({
        "node_id" : node_id,
        "timestamp" : time.time()
    })) 



@app.get("/predict")
async def predict():
    servers = []
    for server, weight in weights.items():
        port = {"server_health" : 8000, "server_degraded":8001, "server_critical":8002}[server]
        count = int(weight * 100)
        servers.extend([f"http://{server}:{port}"]*count)
    
    target = random.choice(servers)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{target}/predict", timeout=10.0)
            log_dump(node_id=target)
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Server {target} unavailable: {str(e)}")

@app.post("/config")
def config(new_weights: dict = Body(...)):
    global weights
    weights = new_weights
    update_weight_metrics()
    return {"updated_weights": weights}

@app.post("/eval")
async def trigger_eval():
    servers ={
        "server_health" : "http://server_health:8000/predict",
        "server_degraded" : "http://server_degraded:8001/predict",
        "server_critical" : "http://server_critical:8002/predict"
    }
    results = []
    for node_id, url in servers.items():
        result = await eval_server(node_id, url)
        if result:
            results.append(result)
    return {"results" : results}

@app.post("/analyze")
async def analyze_incident():
    context = await fetch_context()
    prompt = f"""You are an AI Site Reliability Engineer analyzing an incident.  

    `Here is the current system state:

    Current routing weights: {json.dumps(context['current_weights'], indent=2)}

    Error rates per server (requests/sec): {json.dumps(context['error_rates'], indent=2)}

    p95 Latency:
    - server_health: {context['p95_healthy']}
    - server_degraded: {context['p95_degraded']}
    - server_critical: {context['p95_critical']}

    Recent 503 error logs (last 5 minutes):
    {chr(10).join(context['recent_error_logs'][:10])}

    Based on this data:
    1. Identify which servers are degraded and why
    2. Assess the severity (P0/P1/P2)
    3. Explain the likely root cause
    4. Recommend immediate actions
    5. Recommend longer term fixes
    Be concise and specific. Format as a clear incident report with each analysis under 50 words to maintain clarity and briefness."""
    
    genai.configure(api_key=os.environ.get("GEMINI_API"))
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    analysis = response.text

    print(json.dumps({
        "event" : "Incident_Analysis",
        "timestamp" : time.time(),
        "analysis" : analysis
    }))

    return {
        "analysis" : analysis,
        "context" : context
    } 



@app.get("/weights")
def get_weights():
    return weights