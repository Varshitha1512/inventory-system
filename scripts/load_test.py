#!/usr/bin/env python3
"""
Load Testing Script
Simulates concurrent users hitting all endpoints to verify 99.9% uptime.
"""

import asyncio
import aiohttp
import time
import random
import statistics
from datetime import datetime

BASE_URL = "http://localhost:8000"

SEARCH_QUERIES = [
    "wireless headphones with noise cancellation",
    "yoga mat for beginners",
    "smart home security camera",
    "running shoes for marathon",
    "adjustable dumbbell set",
    "waterproof hiking jacket",
    "robot vacuum with self-emptying",
    "ergonomic laptop stand",
    "deep tissue massage gun",
    "indoor herb garden",
]


async def run_request(session: aiohttp.ClientSession, endpoint: str, stats: dict):
    start = time.monotonic()
    try:
        async with session.get(f"{BASE_URL}{endpoint}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            await resp.json()
            latency_ms = (time.monotonic() - start) * 1000
            stats["success"] += 1
            stats["latencies"].append(latency_ms)
    except Exception as e:
        stats["errors"] += 1
        stats["error_types"].append(str(type(e).__name__))


async def load_test(
    concurrent_users: int = 50,
    duration_seconds: int = 30,
    rps_target: int = 200,
):
    print(f"\n{'='*60}")
    print(f"🔥 Load Test: {concurrent_users} concurrent users, {duration_seconds}s duration")
    print(f"{'='*60}\n")

    stats = {"success": 0, "errors": 0, "latencies": [], "error_types": []}
    start_time = time.monotonic()
    request_count = 0

    endpoints = (
        ["/api/products?page=1&limit=20"] * 4
        + [f"/api/products?page={random.randint(1,50)}&limit=20" for _ in range(3)]
        + [f"/api/search?q={random.choice(SEARCH_QUERIES).replace(' ', '+')}" for _ in range(6)]
        + [f"/api/products/{random.randint(1,500)}" for _ in range(3)]
        + ["/api/stats"] * 2
        + ["/health"] * 2
    )

    connector = aiohttp.TCPConnector(limit=concurrent_users)
    async with aiohttp.ClientSession(connector=connector) as session:
        while (time.monotonic() - start_time) < duration_seconds:
            batch = [
                run_request(session, random.choice(endpoints), stats)
                for _ in range(min(concurrent_users, rps_target))
            ]
            await asyncio.gather(*batch)
            request_count += len(batch)

            elapsed = time.monotonic() - start_time
            if request_count % 500 == 0:
                current_rps = request_count / elapsed
                print(f"  ⏱  {elapsed:.1f}s | Req: {request_count} | RPS: {current_rps:.0f} | Errors: {stats['errors']}")

            await asyncio.sleep(1 / (rps_target / concurrent_users))

    elapsed = time.monotonic() - start_time
    total = stats["success"] + stats["errors"]
    uptime = stats["success"] / total * 100 if total > 0 else 0
    p50 = statistics.median(stats["latencies"]) if stats["latencies"] else 0
    p95 = statistics.quantiles(stats["latencies"], n=20)[18] if len(stats["latencies"]) > 20 else p50
    p99 = statistics.quantiles(stats["latencies"], n=100)[98] if len(stats["latencies"]) > 100 else p95
    avg_latency = statistics.mean(stats["latencies"]) if stats["latencies"] else 0

    print(f"\n{'='*60}")
    print(f"📊 RESULTS")
    print(f"{'='*60}")
    print(f"  Duration:         {elapsed:.1f}s")
    print(f"  Total Requests:   {total:,}")
    print(f"  Successful:       {stats['success']:,}")
    print(f"  Errors:           {stats['errors']:,}")
    print(f"  Uptime:           {uptime:.2f}%  {'✅' if uptime >= 99.9 else '❌'} (target: 99.9%)")
    print(f"  Avg RPS:          {total/elapsed:.0f}")
    print(f"  Avg Latency:      {avg_latency:.1f}ms")
    print(f"  p50 Latency:      {p50:.1f}ms")
    print(f"  p95 Latency:      {p95:.1f}ms")
    print(f"  p99 Latency:      {p99:.1f}ms  {'✅' if p99 < 500 else '⚠️'}")
    print(f"{'='*60}\n")

    if stats["error_types"]:
        from collections import Counter
        print("  Error breakdown:", Counter(stats["error_types"]))


if __name__ == "__main__":
    asyncio.run(load_test(concurrent_users=50, duration_seconds=30))
