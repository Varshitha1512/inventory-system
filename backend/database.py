"""
Database Manager — PostgreSQL with asyncpg, indexed queries, bulk operations.
"""

import asyncpg
import json
import random
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

CATEGORIES = [
    "Electronics", "Clothing", "Home & Garden", "Sports & Outdoors",
    "Books", "Toys & Games", "Health & Beauty", "Automotive",
    "Food & Grocery", "Office Supplies"
]

SAMPLE_PRODUCTS = [
    # Electronics
    ("Wireless Noise-Cancelling Headphones", "Premium over-ear headphones with 30-hour battery and active noise cancellation", "Electronics", 249.99),
    ("4K Ultra HD Smart TV 55\"", "Crystal clear display with built-in streaming apps and voice control", "Electronics", 699.99),
    ("Mechanical Gaming Keyboard RGB", "Tactile switches with per-key RGB lighting and programmable macros", "Electronics", 129.99),
    ("Portable Bluetooth Speaker", "Waterproof 360° sound with 20-hour playtime and USB-C charging", "Electronics", 89.99),
    ("Wireless Gaming Mouse", "16000 DPI sensor with 11 programmable buttons and 70-hour battery", "Electronics", 79.99),
    ("USB-C Hub 7-in-1", "Expand connectivity with HDMI 4K, USB 3.0, SD card reader, and 100W PD", "Electronics", 49.99),
    ("Smart Home Security Camera", "1080p night vision with motion detection and two-way audio", "Electronics", 59.99),
    ("Laptop Stand Adjustable", "Ergonomic aluminum stand compatible with all laptops up to 17 inches", "Electronics", 39.99),
    # Clothing
    ("Men's Waterproof Hiking Jacket", "Breathable Gore-Tex shell with sealed seams and adjustable hood", "Clothing", 189.99),
    ("Women's Yoga Leggings", "High-waist compression fabric with 4-way stretch and moisture wicking", "Clothing", 54.99),
    ("Unisex Classic Hoodie", "80% cotton fleece with kangaroo pocket and ribbed cuffs", "Clothing", 44.99),
    ("Running Shoes Ultra-Boost", "Responsive foam cushioning with breathable mesh upper for long-distance", "Clothing", 139.99),
    # Home & Garden
    ("Robot Vacuum Cleaner", "Auto-mapping AI navigation with self-emptying base and app control", "Home & Garden", 399.99),
    ("Air Purifier HEPA H13", "Filters 99.97% of particles with real-time air quality display", "Home & Garden", 229.99),
    ("Indoor Herb Garden Kit", "Self-watering pods with LED grow lights for year-round fresh herbs", "Home & Garden", 79.99),
    ("Weighted Blanket 15lb", "Glass bead filling with removable cooling cover for better sleep", "Home & Garden", 89.99),
    # Sports
    ("Adjustable Dumbbell Set", "Space-saving design from 5 to 52.5 lbs with quick-change mechanism", "Sports & Outdoors", 349.99),
    ("Yoga Mat Premium Cork", "Non-slip natural cork surface with alignment lines and carry strap", "Sports & Outdoors", 64.99),
    ("Foam Roller Deep Tissue", "High-density EVA foam with textured surface for muscle recovery", "Sports & Outdoors", 34.99),
    ("Resistance Bands Set", "5 levels from 10 to 50 lbs with handles, ankle straps, and door anchor", "Sports & Outdoors", 29.99),
    # Books
    ("Clean Code: A Handbook", "Robert Martin's guide to writing readable, maintainable software", "Books", 39.99),
    ("Atomic Habits", "James Clear's framework for building good habits and breaking bad ones", "Books", 16.99),
    ("Designing Data-Intensive Apps", "Kleppmann's definitive guide to scalable, reliable distributed systems", "Books", 54.99),
    # Toys
    ("LEGO Architecture Eiffel Tower", "1665-piece iconic Paris landmark kit for ages 18+ collectors", "Toys & Games", 169.99),
    ("Board Game Settlers of Catan", "Classic strategy game for 3-4 players with expansion-ready design", "Toys & Games", 44.99),
    # Health
    ("Massage Gun Deep Tissue", "Percussive therapy device with 6 attachments and 5-speed settings", "Health & Beauty", 149.99),
    ("Smart Water Bottle", "Tracks hydration with LED reminders and connects to fitness apps", "Health & Beauty", 49.99),
    ("Posture Corrector Adjustable", "Figure-8 back brace with breathable mesh for office and daily wear", "Health & Beauty", 24.99),
]


class DatabaseManager:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(
                self.dsn,
                min_size=5,
                max_size=20,
                command_timeout=30,
            )
            logger.info("✅ PostgreSQL connected")
        except Exception as e:
            logger.error(f"❌ DB connection failed: {e}")
            raise

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    sku VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    category VARCHAR(100),
                    price NUMERIC(10, 2) NOT NULL,
                    stock_quantity INTEGER DEFAULT 0,
                    tags JSONB DEFAULT '[]',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
                CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
                CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
                CREATE INDEX IF NOT EXISTS idx_products_name_fts ON products USING gin(to_tsvector('english', name || ' ' || COALESCE(description, '')));
            """)
            logger.info("✅ Tables and indexes created")

    async def seed_if_empty(self):
        async with self.pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM products")
            if count > 0:
                logger.info(f"ℹ️  DB already has {count} products, skipping seed")
                return

            # Generate 10,000+ products
            records = []
            sku_counter = 1
            for _ in range(370):  # ~370 × 28 = ~10,360 products
                for name, desc, cat, base_price in SAMPLE_PRODUCTS:
                    price_variation = round(base_price * random.uniform(0.85, 1.15), 2)
                    stock = random.randint(0, 500)
                    sku = f"SKU-{sku_counter:06d}"
                    suffix = f" v{random.randint(2, 9)}" if sku_counter > 28 else ""
                    tags = json.dumps(random.sample(["new", "sale", "popular", "limited", "eco", "premium"], k=random.randint(1, 3)))
                    records.append((sku, name + suffix, desc, cat, price_variation, stock, tags))
                    sku_counter += 1

            await conn.executemany(
                "INSERT INTO products (sku, name, description, category, price, stock_quantity, tags) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)",
                records
            )
            logger.info(f"✅ Seeded {len(records)} products")

    async def list_products(self, page: int, limit: int, category: Optional[str] = None) -> Dict:
        offset = (page - 1) * limit
        async with self.pool.acquire() as conn:
            if category:
                rows = await conn.fetch(
                    "SELECT * FROM products WHERE category=$1 ORDER BY id LIMIT $2 OFFSET $3",
                    category, limit, offset
                )
                total = await conn.fetchval("SELECT COUNT(*) FROM products WHERE category=$1", category)
            else:
                rows = await conn.fetch(
                    "SELECT * FROM products ORDER BY id LIMIT $1 OFFSET $2",
                    limit, offset
                )
                total = await conn.fetchval("SELECT COUNT(*) FROM products")

            return {"products": [dict(r) for r in rows], "total": total}

    async def get_product(self, product_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM products WHERE id=$1", product_id)
            return dict(row) if row else None

    async def get_products_by_ids(self, ids: List[int]) -> List[Dict]:
        if not ids:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM products WHERE id = ANY($1::int[])", ids
            )
            return [dict(r) for r in rows]

    async def create_product(self, data: Dict) -> Dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO products (sku, name, description, category, price, stock_quantity, tags)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb) RETURNING *""",
                data["sku"], data["name"], data["description"],
                data["category"], data["price"], data["stock_quantity"],
                json.dumps(data.get("tags", []))
            )
            return dict(row)

    async def update_product(self, product_id: int, updates: Dict) -> Optional[Dict]:
        if not updates:
            return await self.get_product(product_id)
        set_clauses = []
        values = []
        i = 1
        for k, v in updates.items():
            if k == "tags":
                set_clauses.append(f"{k} = ${i}::jsonb")
                values.append(json.dumps(v))
            else:
                set_clauses.append(f"{k} = ${i}")
                values.append(v)
            i += 1
        values.append(product_id)
        query = f"UPDATE products SET {', '.join(set_clauses)}, updated_at=NOW() WHERE id=${i} RETURNING *"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *values)
            return dict(row) if row else None

    async def delete_product(self, product_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM products WHERE id=$1", product_id)
            return result == "DELETE 1"

    async def get_all_products_for_indexing(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, description, category, tags FROM products")
            return [dict(r) for r in rows]

    async def get_stats(self) -> Dict:
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM products")
            categories = await conn.fetch(
                "SELECT category, COUNT(*) as count, AVG(price)::numeric(10,2) as avg_price FROM products GROUP BY category ORDER BY count DESC"
            )
            low_stock = await conn.fetchval("SELECT COUNT(*) FROM products WHERE stock_quantity < 10")
            total_value = await conn.fetchval("SELECT SUM(price * stock_quantity)::numeric(14,2) FROM products")

            return {
                "total_products": total,
                "low_stock_alerts": low_stock,
                "total_inventory_value": float(total_value or 0),
                "categories": [dict(r) for r in categories],
            }
