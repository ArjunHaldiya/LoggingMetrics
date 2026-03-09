import asyncio
import httpx
import random
import time

SERVERS = [
    "http://localhost:8000/predict",
    "http://localhost:8001/predict",
    "http://localhost:8002/predict",
]

async def send_request(client, url):
    try:
        response = await client.get(url, timeout=5.0)
        print(f"[{url.split(':')[1].split('/')[0]}] status={response.status_code}")
    except Exception as e:
        print(f"[ERROR] {url} → {e}")

async def run_traffic(rps_per_server=2, duration_seconds=120):
    print(f"Starting traffic generator — {rps_per_server} req/s per server for {duration_seconds}s")
    
    async with httpx.AsyncClient() as client:
        start = time.time()
        while time.time() - start < duration_seconds:
            tasks = []
            for url in SERVERS:
                for _ in range(rps_per_server):
                    tasks.append(send_request(client, url))
            
            await asyncio.gather(*tasks)
            await asyncio.sleep(1.0)

    print("Traffic generation complete.")

if __name__ == "__main__":
    asyncio.run(run_traffic(rps_per_server=2, duration_seconds=120))