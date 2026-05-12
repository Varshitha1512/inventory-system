#!/usr/bin/env python3
"""
Cache Benchmark — Measures DB vs Redis latency to verify 60% reduction.
"""

import asyncio
import aiohttp
import time
import statistics

BASE_URL = "http://localhost:8000"


async def benchmark_cache():
    print("\n🔬 Cache Latency Benchmark\n")

    async with aiohttp.ClientSession() as session:
        # Warm-up
        for _ in range(3):
            async with session.get(f"{BASE_URL}/api/products?page=1&limit=20") as r:
                await r.json()

        # Cold (DB) latencies — use unique pages to avoid cache
        db_latencies = []
        for page in range(100, 130):
            start = time.monotonic()
            async with session.get(f"{BASE_URL}/api/products?page={page}&limit=20") as r:
                data = await r.json()
                elapsed = (time.monotonic() - start) * 1000
                if data.get("cache") == "MISS":
                    db_latencies.append(elapsed)

        # Hot (Redis) latencies — repeat same pages
        redis_latencies = []
        for page in range(100, 130):
            start = time.monotonic()
            async with session.get(f"{BASE_URL}/api/products?page={page}&limit=20") as r:
                data = await r.json()
                elapsed = (time.monotonic() - start) * 1000
                if data.get("cache") == "HIT":
                    redis_latencies.append(elapsed)

        if db_latencies and redis_latencies:
            avg_db = statistics.mean(db_latencies)
            avg_redis = statistics.mean(redis_latencies)
            reduction = (avg_db - avg_redis) / avg_db * 100

            print(f"  DB (cold) avg latency:    {avg_db:.1f}ms")
            print(f"  Redis (hot) avg latency:  {avg_redis:.1f}ms")
            print(f"  Latency reduction:        {reduction:.1f}%  {'✅' if reduction >= 60 else '⚠️'} (target: 60%)")
        else:
            print("  Could not collect enough cache HIT/MISS samples. Ensure Redis is running.")


async def benchmark_search():
    print("\n🔬 Semantic Search Latency Benchmark\n")

    queries = [
        "wireless headphones", "yoga mat", "robot vacuum",
        "laptop stand ergonomic", "running shoes marathon",
    ]

    async with aiohttp.ClientSession() as session:
        latencies = []
        for q in queries * 5:
            start = time.monotonic()
            async with session.get(f"{BASE_URL}/api/search?q={q.replace(' ', '+')}") as r:
                data = await r.json()
                elapsed = (time.monotonic() - start) * 1000
                latencies.append(elapsed)
                print(f"  Query: '{q}' → {data.get('total_found',0)} results | {elapsed:.1f}ms | cache:{data.get('cache')}")

        avg = statistics.mean(latencies)
        p99 = statistics.quantiles(latencies, n=100)[98]
        print(f"\n  Avg search latency: {avg:.1f}ms  {'✅' if avg < 1000 else '❌'} (target: <1000ms)")
        print(f"  p99 search latency: {p99:.1f}ms")


if __name__ == "__main__":
    asyncio.run(benchmark_cache())
    asyncio.run(benchmark_search())
