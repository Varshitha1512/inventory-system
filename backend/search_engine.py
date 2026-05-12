"""
Semantic Search Engine
Uses sentence-transformers (all-MiniLM-L6-v2) to embed products and 
FAISS IVF index for sub-second approximate nearest-neighbor retrieval.
"""

import numpy as np
import json
import logging
import asyncio
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

try:
    import faiss
    from sentence_transformers import SentenceTransformer
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("⚠️  FAISS/sentence-transformers not installed. Falling back to cosine similarity mock.")


class SemanticSearchEngine:
    """
    Two-phase semantic search:
    1. Encode query → 384-dim embedding via MiniLM
    2. FAISS IVF index for ANN retrieval in sub-second time
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.index = None
        self.product_ids: List[int] = []
        self.product_texts: List[str] = []
        self.embeddings: Optional[np.ndarray] = None
        self.dim = 384
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._lock = asyncio.Lock()

        if FAISS_AVAILABLE:
            logger.info(f"🔍 Loading model: {model_name}")
            self.model = SentenceTransformer(model_name)
            logger.info("✅ Sentence-transformer model loaded")
        else:
            logger.info("🔍 Using fallback cosine similarity search")

    def _make_text(self, product: Dict) -> str:
        """Concatenate fields for richer semantic representation."""
        tags = product.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        tag_str = " ".join(tags) if tags else ""
        return f"{product.get('name', '')} {product.get('description', '')} {product.get('category', '')} {tag_str}".strip()

    def _encode(self, texts: List[str]) -> np.ndarray:
        if FAISS_AVAILABLE and self.model:
            embeddings = self.model.encode(texts, batch_size=256, show_progress_bar=False, normalize_embeddings=True)
            return embeddings.astype(np.float32)
        else:
            # Deterministic hash-based mock embeddings for fallback
            vecs = []
            for text in texts:
                rng = np.random.RandomState(abs(hash(text)) % (2**31))
                v = rng.randn(self.dim).astype(np.float32)
                v /= np.linalg.norm(v) + 1e-9
                vecs.append(v)
            return np.array(vecs, dtype=np.float32)

    def _build_faiss_index(self, embeddings: np.ndarray) -> "faiss.Index":
        n, d = embeddings.shape
        if FAISS_AVAILABLE:
            if n > 1000:
                # IVF index: faster for large catalogs
                nlist = min(256, n // 10)
                quantizer = faiss.IndexFlatIP(d)
                index = faiss.IndexIVFFlat(quantizer, d, nlist, faiss.METRIC_INNER_PRODUCT)
                index.train(embeddings)
                index.add(embeddings)
                index.nprobe = 32  # probe 32 cells for recall/speed balance
            else:
                index = faiss.IndexFlatIP(d)
                index.add(embeddings)
            return index
        else:
            return None  # fallback uses numpy

    async def build_index(self, products: List[Dict]):
        """Build FAISS index from all products. Called at startup."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self._sync_build_index, products)
            logger.info(f"✅ FAISS index built: {len(products)} products, dim={self.dim}")

    def _sync_build_index(self, products: List[Dict]):
        self.product_ids = [p["id"] for p in products]
        self.product_texts = [self._make_text(p) for p in products]
        self.embeddings = self._encode(self.product_texts)
        self.index = self._build_faiss_index(self.embeddings)

    async def search(self, query: str, top_k: int = 10, threshold: float = 0.3) -> List[Dict]:
        """Encode query and retrieve top-k nearest products from FAISS."""
        if not self.product_ids:
            return []

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            self._executor, self._sync_search, query, top_k, threshold
        )
        return results

    def _sync_search(self, query: str, top_k: int, threshold: float) -> List[Dict]:
        query_vec = self._encode([query])  # shape (1, 384)

        if FAISS_AVAILABLE and self.index is not None:
            k = min(top_k, len(self.product_ids))
            scores, indices = self.index.search(query_vec, k)
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue
                if float(score) >= threshold:
                    results.append({
                        "product_id": self.product_ids[idx],
                        "score": float(score),
                    })
        else:
            # Fallback: cosine similarity via numpy
            sims = (self.embeddings @ query_vec.T).flatten()
            top_indices = np.argsort(sims)[::-1][:top_k]
            results = []
            for idx in top_indices:
                score = float(sims[idx])
                if score >= threshold:
                    results.append({
                        "product_id": self.product_ids[idx],
                        "score": score,
                    })

        return results

    async def add_product(self, product: Dict):
        """Add a single product to the FAISS index."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self._sync_add_product, product)

    def _sync_add_product(self, product: Dict):
        text = self._make_text(product)
        vec = self._encode([text])  # (1, 384)
        self.product_ids.append(product["id"])
        self.product_texts.append(text)
        if self.embeddings is not None:
            self.embeddings = np.vstack([self.embeddings, vec])
        else:
            self.embeddings = vec
        if FAISS_AVAILABLE and self.index is not None:
            self.index.add(vec)

    async def update_product(self, product: Dict):
        """Re-index updated product (remove + re-add)."""
        await self.remove_product(product["id"])
        await self.add_product(product)

    async def remove_product(self, product_id: int):
        """Remove product from index."""
        async with self._lock:
            if product_id not in self.product_ids:
                return
            idx = self.product_ids.index(product_id)
            self.product_ids.pop(idx)
            self.product_texts.pop(idx)
            if self.embeddings is not None and len(self.embeddings) > idx:
                self.embeddings = np.delete(self.embeddings, idx, axis=0)
            # Rebuild index after removal (FAISS IVF doesn't support direct deletion)
            if FAISS_AVAILABLE and self.embeddings is not None and len(self.embeddings) > 0:
                self.index = self._build_faiss_index(self.embeddings)

    def get_index_info(self) -> Dict:
        return {
            "model": self.model_name,
            "index_type": "FAISS-IVF" if FAISS_AVAILABLE else "numpy-cosine-fallback",
            "total_indexed": len(self.product_ids),
            "embedding_dim": self.dim,
            "faiss_available": FAISS_AVAILABLE,
        }
