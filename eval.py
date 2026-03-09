import asyncio
import httpx
import time
import sqlite3
import uuid
import json

DB_PATH = "eval.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            run_id TEXT,
            node_id TEXT,
            p50_ms REAL,
            p95_ms REAL,
            p99_ms REAL,
            throughput REAL,
            error_rate REAL,
            avg_confidence REAL,
            run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

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

async def run_eval():
    init_db()
    run_id = str(uuid.uuid4())[:8]

    servers = {
        "server_health": "http://localhost:8000/predict",
        "server_degraded": "http://localhost:8001/predict",
        "server_critical": "http://localhost:8002/predict"
    }

    print(f"\n{'='*60}")
    print(f"EVAL RUN: {run_id}")
    print(f"{'='*60}")

    results = []
    for node_id, url in servers.items():
        print(f"Evaluating {node_id}...")
        result = await eval_server(node_id, url)
        if result:
            results.append(result)
            print(json.dumps(result, indent=2))

    # Save to SQLite
    conn = sqlite3.connect(DB_PATH)
    for r in results:
        conn.execute("""
            INSERT INTO eval_runs
            (run_id, node_id, p50_ms, p95_ms, p99_ms, throughput, error_rate, avg_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, r["node_id"], r["p50_ms"], r["p95_ms"], r["p99_ms"],
              r["throughput"], r["error_rate"], r["avg_confidence"]))
    conn.commit()
    conn.close()

    # Print comparison table
    print(f"\n{'='*60}")
    print("COMPARISON TABLE")
    print(f"{'='*60}")
    print(f"{'Node':<20} {'p50ms':<8} {'p95ms':<8} {'p99ms':<8} {'RPS':<8} {'ErrRate':<10} {'Confidence'}")
    print("-"*60)
    for r in results:
        print(f"{r['node_id']:<20} {r['p50_ms']:<8} {r['p95_ms']:<8} {r['p99_ms']:<8} {r['throughput']:<8} {r['error_rate']:<10} {r['avg_confidence']}")

if __name__ == "__main__":
    asyncio.run(run_eval())