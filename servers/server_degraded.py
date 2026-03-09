from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Histogram, Gauge, Counter
import time, json, logging
import random

Latency = Histogram(
    "degraded_predict_latency_seconds",
    "Latency at predict endpoint",
    buckets= [0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5]
)
IN_FLIGHT = Gauge(
    'requests_in_flight',
    'Number of requests currently being processed',
    ['node_id']
)

REQUESTS = Counter(
    'requests_total_custom',
    'Total requests with outcome label',
    ['node_id', 'outcome']
)

CONFIDENCE = Histogram(
    'model_confidence_score',
    'Distribution of model confidence scores',
    ['node_id'],
    buckets = [0.5,0.6,0.7,0.8,0.9,0.95,0.99,1.0]
)

app = FastAPI(title = "Server Degraded")
Instrumentator().instrument(app).expose(app)

chaos = False

@app.post("/chaos")
def toggle_chaos():
    global chaos
    chaos = not chaos
    status = "ENABLED" if chaos else "DISABLED"
    print(json.dumps({
        "event": "chaos_mode_toggle",
        "status" : status,
        "node_id" : "server_degraded",
        "timestamp" : time.time()
    }))

    return {"chaos" : chaos, "status" : status}

@app.get("/chaos/status")
def chaos_status():
    return{"chaos" : chaos}


def logs(node_id, latency_ms, status_code):
    print(json.dumps({
        "node_id" : node_id,
        "latency_ms" : latency_ms,
        "status_code": status_code
    }))

@app.get("/predict")
def predict():
    IN_FLIGHT.labels(node_id = "server_degraded").inc()
    try:
        start = time.time()
        latency_multiplier = 5.0 if chaos else 1.0
        error_rate = 0.8 if chaos else 0.30
        time.sleep(random.uniform(0.5,1.5)*latency_multiplier)
        if random.random() < error_rate:
            latency_ms = (time.time() - start) * 1000
            Latency.observe(latency_ms/1000)
            logs("server_degraded", latency_ms, 503)
            REQUESTS.labels(node_id="server_degraded", outcome="error").inc()
            raise HTTPException(status_code=503, detail="Overloaded Server Degraded")
        confidence = random.uniform(0.7,0.99)
        CONFIDENCE.labels(node_id ="server_degraded").observe(confidence)
        latency_ms = (time.time() - start) * 1000
        Latency.observe(latency_ms/1000)
        logs("server_degraded", latency_ms, 200)
        REQUESTS.labels(node_id="server_degraded", outcome="success").inc()
        return {"result" : "positive","confidence":confidence, "status_code" : 200}
    finally:
        IN_FLIGHT.labels(node_id="server_degraded").dec()
