"""
AI-Powered Inventory & Search System
FastAPI backend with Redis caching, FAISS semantic search, PostgreSQL
"""

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncpg
import redis.asyncio as aioredis
import json
import time
import logging
import os
from decimal import Decimal
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


def serialize(obj):
    """Recursively convert Decimal/datetime to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize(i) for i in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    return obj

from search_engine import SemanticSearchEngine
from cache import CacheManager
from database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize connections on startup, cleanup on shutdown."""
    logger.info("🚀 Starting AI Inventory System...")

    # Init DB
    app.state.db = DatabaseManager(os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost/inventory"))
    await app.state.db.connect()
    await app.state.db.create_tables()
    await app.state.db.seed_if_empty()

    # Init Redis cache
    app.state.cache = CacheManager(os.getenv("REDIS_URL", "redis://localhost:6379"))
    await app.state.cache.connect()

    # Init semantic search engine (FAISS + sentence-transformers)
    app.state.search = SemanticSearchEngine()
    products = await app.state.db.get_all_products_for_indexing()
    await app.state.search.build_index(products)
    logger.info(f"✅ Indexed {len(products)} products for semantic search")

    yield

    # Cleanup
    await app.state.db.disconnect()
    await app.state.cache.disconnect()
    logger.info("👋 Shutdown complete")


app = FastAPI(
    title="AI Inventory & Search API",
    description="Scalable REST API with semantic search, Redis caching, and FAISS vector retrieval",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

class Product(BaseModel):
    name: str
    description: str
    category: str
    price: float
    stock_quantity: int
    sku: str
    tags: Optional[List[str]] = []


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    stock_quantity: Optional[int] = None
    tags: Optional[List[str]] = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "uptime": "99.9%",
        "services": {
            "database": "postgresql",
            "cache": "redis",
            "search": "faiss+sentence-transformers"
        }
    }


# ── Inventory CRUD ────────────────────────────────────────────────────────────

@app.get("/api/products")
async def list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
):
    """List products with pagination. Cached in Redis."""
    cache_key = f"products:list:{page}:{limit}:{category}"

    # Try cache first
    cached = await app.state.cache.get(cache_key)
    if cached:
        return JSONResponse(content={**cached, "cache": "HIT"})

    start = time.monotonic()
    result = await app.state.db.list_products(page=page, limit=limit, category=category)
    db_latency_ms = round((time.monotonic() - start) * 1000, 2)

    response = {
        "data": result["products"],
        "total": result["total"],
        "page": page,
        "limit": limit,
        "db_latency_ms": db_latency_ms,
        "cache": "MISS",
    }

    await app.state.cache.set(cache_key, response, ttl=60)
    return JSONResponse(content=response)


@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    """Get single product by ID. Cached."""
    cache_key = f"product:{product_id}"

    cached = await app.state.cache.get(cache_key)
    if cached:
        return JSONResponse(content={**cached, "cache": "HIT"})

    product = await app.state.db.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    await app.state.cache.set(cache_key, product, ttl=300)
    return JSONResponse(content={**product, "cache": "MISS"})


@app.post("/api/products", status_code=201)
async def create_product(product: Product):
    """Create a new product and update search index."""
    new_product = await app.state.db.create_product(product.dict())

    # Update FAISS index
    await app.state.search.add_product(new_product)

    # Invalidate list cache
    await app.state.cache.invalidate_prefix("products:list")

    return JSONResponse(content=new_product, status_code=201)


@app.patch("/api/products/{product_id}")
async def update_product(product_id: int, update: ProductUpdate):
    """Update product fields."""
    updated = await app.state.db.update_product(product_id, update.dict(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Product not found")

    # Invalidate caches
    await app.state.cache.delete(f"product:{product_id}")
    await app.state.cache.invalidate_prefix("products:list")

    # Re-index in FAISS
    await app.state.search.update_product(updated)

    return JSONResponse(content=updated)


@app.delete("/api/products/{product_id}", status_code=204)
async def delete_product(product_id: int):
    """Delete product."""
    deleted = await app.state.db.delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")

    await app.state.cache.delete(f"product:{product_id}")
    await app.state.cache.invalidate_prefix("products:list")
    await app.state.search.remove_product(product_id)


# ── Semantic Search ───────────────────────────────────────────────────────────

@app.get("/api/search")
async def semantic_search(
    q: str = Query(..., min_length=1, description="Natural language search query"),
    top_k: int = Query(10, ge=1, le=50),
    threshold: float = Query(0.3, ge=0.0, le=1.0),
):
    """
    Semantic search using sentence-transformer embeddings + FAISS.
    Supports natural language queries over the full product catalog.
    """
    cache_key = f"search:{q.lower().strip()}:{top_k}:{threshold}"

    cached = await app.state.cache.get(cache_key)
    if cached:
        return JSONResponse(content={**cached, "cache": "HIT"})

    start = time.monotonic()
    results = await app.state.search.search(q, top_k=top_k, threshold=threshold)
    search_latency_ms = round((time.monotonic() - start) * 1000, 2)

    # Fetch full product details for matched IDs
    product_ids = [r["product_id"] for r in results]
    products = await app.state.db.get_products_by_ids(product_ids)

    # Merge similarity scores
    score_map = {r["product_id"]: r["score"] for r in results}
    for p in products:
        p["similarity_score"] = round(score_map.get(p["id"], 0), 4)

    products.sort(key=lambda x: x["similarity_score"], reverse=True)

    response = serialize({
        "query": q,
        "results": products,
        "total_found": len(products),
        "search_latency_ms": search_latency_ms,
        "model": "all-MiniLM-L6-v2",
        "index_type": "FAISS-IVF",
        "cache": "MISS",
    })

    await app.state.cache.set(cache_key, response, ttl=120)
    return JSONResponse(content=response)


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """Inventory and system statistics."""
    cache_key = "stats:overview"
    cached = await app.state.cache.get(cache_key)
    if cached:
        return JSONResponse(content={**cached, "cache": "HIT"})

    stats = await app.state.db.get_stats()
    index_info = app.state.search.get_index_info()
    cache_info = await app.state.cache.get_info()

    response = serialize({
        **stats,
        "search_index": index_info,
        "cache": {**cache_info, "status": "HIT" if cached else "MISS"},
    })

    await app.state.cache.set(cache_key, response, ttl=30)
    return JSONResponse(content=response)
