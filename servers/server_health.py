from fastapi import FastAPI, HTTPException
import json, time, logging
import random
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Histogram, Gauge, Counter

Latency = Histogram(
    "healthy_predict_latency_seconds",
    "Latency of predict endpoints",
    buckets= [0.05,0.06,0.07,0.08,0.09,0.1,0.11,0.12,0.13,0.14,0.15,0.16,0.17,0.18,0.19,0.2]
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
app = FastAPI(title= "Server Health")

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
        "node_id" : "server_health",
        "timestamp" : time.time()
    }))

    return {"chaos" : chaos, "status" : status}

@app.get("/chaos/status")
def chaos_status():
    return{"chaos" : chaos}


logging.basicConfig(level=logging.INFO)
def log_request(node_id, latency_ms, status_code):
    print(json.dumps({
        "node_id" : node_id,
        "latency_ms" : round(latency_ms, 2),
        "status_code": status_code,
        "timestamp": time.time()
    }))

@app.get("/predict")
def predict():
    IN_FLIGHT.labels(node_id="server_health").inc()
    try:
        start = time.time()
        latency_multiplier = 5.0 if chaos else 1.0
        error_rate = 0.8 if chaos else 0.02 
        time.sleep(random.uniform(0.05,0.2)*latency_multiplier)
        if random.random() < error_rate:
            latency_ms = (time.time() - start) * 1000
            Latency.observe(latency_ms/1000)
            log_request("server_health", latency_ms, 503)
            REQUESTS.labels(node_id = "server_health", outcome = "error").inc()
            raise HTTPException(status_code=503, detail="Server Overloaded")
        confidence = random.uniform(0.7,0.99)
        CONFIDENCE.labels(node_id="server_health").observe(confidence)
        latency_ms = (time.time() - start) * 1000
        Latency.observe(latency_ms/1000)
        log_request("server_health", latency_ms, 200)
        REQUESTS.labels(node_id = "server_health", outcome = "success").inc()
        return {"result" : "positive" ,"status_code": 200, "confidence" : confidence}
    finally:
        IN_FLIGHT.labels(node_id = "server_health").dec()