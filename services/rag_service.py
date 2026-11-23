"""
rag_service.py
Full Phase 2 RAG pipeline with disk caching:
  - FAISS indexes saved to faiss_indexes/ after first build
  - Cache is validated against the current CSV data (fingerprint), so a changed
    dataset or embedding model triggers a rebuild instead of serving stale vectors
  - Index builds are guarded by a per-city file lock and written atomically, so
    several server processes can start at once without corrupting the cache
  - Groq llama-3.3-70b for LLM answers
  - City-aware by default, cross-city when query demands it
  - ML predictions injected into context when relevant
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
import requests
from filelock import FileLock, Timeout
from sentence_transformers import SentenceTransformer

import groq_budget
from cache import chat_store, get_or_compute, localities_store
from concurrency import chat_pool
from config import (RAG_DATA_PATHS, SUPPORTED_CITIES, GROQ_API_KEY,
                    LLM_MODEL, GROWTH_RATES, DATASET_AGE_YEARS, FAISS_INDEX_DIR)

# Constants
TOP_K        = 8 # i'll try 9-12 vals further
EMBED_MODEL  = "all-MiniLM-L6-v2"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
INDEX_DIR    = FAISS_INDEX_DIR          # absolute path, set in config.py
BUILD_LOCK_TIMEOUT_S = 15 * 60          # how long to wait for another process's build

# Global stores
_dfs:      dict[str, pd.DataFrame]       = {}
_indexes:  dict[str, faiss.IndexFlatIP]  = {}
_texts:    dict[str, list[str]]          = {}
_embedder: SentenceTransformer | None    = None

# Cross-city detection
CROSS_CITY_TRIGGERS = [
    "vs", "versus", "compare", "better", "cheaper", "expensive",
    "difference", "which city", "both", "all cities",
    "mumbai and", "pune and", "bengaluru and", "bangalore and",
]
CITY_ALIASES = {
    "bangalore": "bengaluru",
    "bengalore": "bengaluru",
    "bombay":    "mumbai",
}


# Disk cache helpers
#
# Per city, two files live in INDEX_DIR:
#   <city>.index      the FAISS index
#   <city>.meta.json  fingerprint of the texts + embedding model it was built from
# The meta file is written last, so it doubles as a "build finished" marker.
# The row texts are NOT cached: they are rebuilt from the CSV on every start
# (fast), which also removes the need to unpickle anything from disk.

def _index_path(city: str) -> Path:
    return INDEX_DIR / f"{city}.index"

def _meta_path(city: str) -> Path:
    return INDEX_DIR / f"{city}.meta.json"

def _lock_path(city: str) -> Path:
    return INDEX_DIR / f"{city}.lock"

def _fingerprint(texts: list[str]) -> str:
    """Changes whenever the data, the text template or the embedding model changes."""
    h = hashlib.sha256()
    h.update(EMBED_MODEL.encode("utf-8"))
    h.update(b"\0")
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()

def _try_load_cache(city: str, fingerprint: str, expected_count: int):
    """Return the cached index if it exists and matches the current data, else None."""
    if not (_index_path(city).exists() and _meta_path(city).exists()):
        return None
    try:
        meta = json.loads(_meta_path(city).read_text(encoding="utf-8"))
        if meta.get("fingerprint") != fingerprint:
            print(f"[RAG] Cache for '{city}' is stale (data or settings changed)")
            return None
        index = faiss.read_index(str(_index_path(city)))
        if index.ntotal != expected_count:
            print(f"[RAG] Cache for '{city}' has {index.ntotal} vectors, "
                  f"expected {expected_count}")
            return None
        return index
    except Exception as e:
        print(f"[RAG] Cache for '{city}' unreadable ({e}); will rebuild")
        return None

def _save_cache(city: str, index, fingerprint: str):
    """Write to temp files, then rename, so readers never see a half-written file."""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()

    tmp_index = INDEX_DIR / f"{city}.index.tmp-{pid}"
    faiss.write_index(index, str(tmp_index))
    os.replace(tmp_index, _index_path(city))

    meta = {
        "fingerprint": fingerprint,
        "vectors":     int(index.ntotal),
        "embed_model": EMBED_MODEL,
        "built_at":    datetime.now(timezone.utc).isoformat(),
    }
    tmp_meta = INDEX_DIR / f"{city}.meta.json.tmp-{pid}"
    tmp_meta.write_text(json.dumps(meta), encoding="utf-8")
    os.replace(tmp_meta, _meta_path(city))
    print(f"[RAG] Cache saved for '{city}' ✓")

def _build_index(texts: list[str]):
    embeddings = _embedder.encode(texts, show_progress_bar=True, batch_size=256)
    embeddings = np.array(embeddings).astype("float32")
    faiss.normalize_L2(embeddings)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    return index

def _load_or_build_index(city: str, texts: list[str]):
    """Return (index, how) where how says whether it came from cache or was built."""
    fingerprint = _fingerprint(texts)

    index = _try_load_cache(city, fingerprint, len(texts))
    if index is not None:
        return index, "cache"

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(_lock_path(city)), timeout=BUILD_LOCK_TIMEOUT_S):
            # Another process may have finished the build while we waited for the lock
            index = _try_load_cache(city, fingerprint, len(texts))
            if index is not None:
                return index, "cache (built by another process)"

            print(f"[RAG] Building FAISS index for '{city}' ({len(texts)} rows)...")
            index = _build_index(texts)
            _save_cache(city, index, fingerprint)
            return index, "fresh build"
    except Timeout:
        raise RuntimeError(
            f"Timed out waiting for another process to build the '{city}' index "
            f"(lock: {_lock_path(city)}). If no other server is starting, delete "
            "that lock file and retry."
        )

def _row_to_text(city: str, row) -> str:
    return (
        f"City: {city.title()}. "
        f"Locality: {row.get('locality', '')}. "
        f"Region: {row.get('region', '')}. "
        f"Type: {row.get('type', '')}. "
        f"BHK: {row.get('bhk', '')}. "
        f"Area: {row.get('area', '')} sqft. "
        f"Price per sqft: ₹{row.get('price_per_sqft', 0):.0f}. "
        f"Status: {row.get('status', '')}. "
        f"Age: {row.get('age', '')}."
    )


def load_all_rag_data():
    """Called once from main.py lifespan."""
    global _embedder
    t_start = time.perf_counter()

    print("[RAG] Loading sentence-transformer model...")
    _embedder = SentenceTransformer(EMBED_MODEL)
    _embedder.encode(["warm-up"], normalize_embeddings=True)  # first call is slow; pay it now
    print(f"[RAG] Embedder ready in {time.perf_counter() - t_start:.1f}s ✓")

    for city in SUPPORTED_CITIES:
        path = RAG_DATA_PATHS[city]
        if not path.exists():
            print(f"[RAG] WARNING — dataset missing for '{city}'")
            continue

        t_city = time.perf_counter()
        df = pd.read_csv(path).dropna(subset=["locality", "price_per_sqft"])
        texts = [_row_to_text(city, row) for row in df.to_dict("records")]

        index, how = _load_or_build_index(city, texts)

        _dfs[city]     = df
        _texts[city]   = texts
        _indexes[city] = index
        print(f"[RAG] '{city}' ready from {how} — {index.ntotal} vectors "
              f"in {time.perf_counter() - t_city:.1f}s ✓")

    if is_ready():
        print(f"[RAG] All indexes ready in {time.perf_counter() - t_start:.1f}s ✅")
    else:
        print("[RAG] WARNING — not every city is loaded; /ready will report 503")


def get_status() -> dict:
    """What is loaded right now. Used by /ready."""
    cities = {
        c: {
            "loaded":  c in _dfs and c in _indexes,
            "rows":    len(_dfs[c]) if c in _dfs else 0,
            "vectors": int(_indexes[c].ntotal) if c in _indexes else 0,
        }
        for c in SUPPORTED_CITIES
    }
    return {
        "embedder_loaded": _embedder is not None,
        "cities":          cities,
        "ready":           _embedder is not None and all(v["loaded"] for v in cities.values()),
    }


def is_ready() -> bool:
    return get_status()["ready"]


def get_localities(city: str) -> list[str]:
    if city not in _dfs or "locality" not in _dfs[city].columns:
        return []
    return sorted(_dfs[city]["locality"].dropna().unique().tolist())


def _detect_cities_in_query(query: str) -> list[str]:
    q = query.lower()
    found = []
    for city in SUPPORTED_CITIES:
        if city in q:
            found.append(city)
    for alias, canonical in CITY_ALIASES.items():
        if alias in q and canonical not in found:
            found.append(canonical)
    return found

def _is_cross_city_query(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in CROSS_CITY_TRIGGERS) or len(_detect_cities_in_query(query)) >= 2

def _resolve_cities(query: str, active_city: str) -> list[str]:
    if _is_cross_city_query(query):
        mentioned = _detect_cities_in_query(query)
        return mentioned if mentioned else SUPPORTED_CITIES
    return [active_city]


# FAISS retrieval

def _retrieve(query: str, cities: list[str]) -> list[str]:
    if _embedder is None:
        return []
    q_emb = _embedder.encode([query], normalize_embeddings=True).astype("float32")
    all_results = []
    for city in cities:
        if city not in _indexes:
            continue
        scores, indices = _indexes[city].search(q_emb, TOP_K)
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:
                all_results.append((float(score), _texts[city][idx]))
    all_results.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in all_results[:TOP_K]]


def _get_ml_context(query: str, cities: list[str]) -> str:
    bhk_match  = re.search(r'(\d)\s*bhk', query.lower())
    area_match = re.search(r'(\d+)\s*(?:sqft|sq\.?ft|square)', query.lower())
    if not bhk_match:
        return ""

    bhk   = int(bhk_match.group(1))
    lines = [f"\n[ML price data for {bhk}BHK]"]

    for city in cities:
        if city not in _dfs:
            continue
        filtered = _dfs[city][_dfs[city]["bhk"] == bhk]
        if filtered.empty:
            continue
        avg_pps     = filtered["price_per_sqft"].mean()
        growth      = GROWTH_RATES.get(city, 0.08)
        current_pps = avg_pps * ((1 + growth) ** DATASET_AGE_YEARS)

        if area_match:
            area          = int(area_match.group(1))
            current_total = current_pps * area
            future_3yr    = current_total * ((1 + growth) ** 3)
            lines.append(
                f"  {city.title()}: ₹{current_pps:,.0f}/sqft (2025). "
                f"{area} sqft → ₹{current_total/1e5:,.1f}L today, "
                f"₹{future_3yr/1e5:,.1f}L in 3 years."
            )
        else:
            lines.append(
                f"  {city.title()}: avg ₹{current_pps:,.0f}/sqft (2025)."
            )
    return "\n".join(lines) if len(lines) > 1 else ""


def _call_groq(system_prompt: str, user_message: str) -> tuple[str, bool]:
    """Returns (text, ok). Error messages come back as text with ok=False,
    so callers can avoid caching them."""
    if not GROQ_API_KEY:
        return "Groq API key not set. Add GROQ_API_KEY to your .env file.", False

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":    LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                "temperature": 0.4,
                "max_tokens":  1024,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip(), True
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", False
    except requests.exceptions.HTTPError as e:
        return f"Groq API error: {e.response.status_code} — {e.response.text}", False
    except Exception as e:
        return f"Unexpected error: {str(e)}", False


def _build_system_prompt(active_city: str, retrieved: list[str], ml_context: str) -> str:
    return f"""You are LocalLens, a friendly and expert Indian real estate assistant for Mumbai, Bengaluru, and Pune.

The user is currently viewing: {active_city.title()}

RETRIEVED PROPERTY DATA (real listings from dataset):
{chr(10).join(retrieved)}
{ml_context}

INSTRUCTIONS:
- Answer conversationally and helpfully for ANY question — real estate or general
- For real estate questions, base answers on the retrieved data above
- Always quote prices in Indian format: Lakhs (L) or Crores (Cr)
- Mention specific localities and price ranges from the data when relevant
- For cross-city queries, clearly state which city is cheaper and by how much
- Growth rates: Mumbai 8%, Bengaluru 12%, Pune 6% per year
- All prices are inflation-adjusted to 2025 from 2022 dataset
- If asked something outside real estate, answer helpfully as a general assistant
- Keep answers concise: 3-6 sentences for simple queries, more for comparisons
- Never make up locality names or prices not present in the data
"""


def _normalize_city(active_city: str) -> str:
    active_city = CITY_ALIASES.get(active_city.lower().strip(), active_city.lower().strip())
    if active_city not in SUPPORTED_CITIES:
        active_city = "mumbai"
    return active_city


def ask_with_status(query: str, active_city: str = "mumbai"):
    """Returns (result_dict, ok). ok is False when the LLM call failed."""
    print(f"[DEBUG] Received active_city = '{active_city}'")  # ← add this line only
    active_city = _normalize_city(active_city)

    cities    = _resolve_cities(query, active_city)
    retrieved = _retrieve(query, cities)
    ml_ctx    = _get_ml_context(query, cities)
    system    = _build_system_prompt(active_city, retrieved, ml_ctx)
    answer, ok = _call_groq(system, query)

    return {
        "answer":  answer,
        "sources": [f"LocalLens dataset — {c.title()}" for c in cities],
    }, ok


def ask(query: str, active_city: str = "mumbai") -> dict:
    result, _ = ask_with_status(query, active_city)
    return result


def ask_cached(query: str, active_city: str = "mumbai"):
    """
    Same as ask(), but repeated questions are served from cache.
    Returns (result_dict, served_without_calling_groq).

    - identical questions asked at the same moment share ONE Groq call
    - only real Groq calls count against the budget (groq_budget.take)
    - at most MAX_COMPUTE_CHAT answers are computed at once
    - failed LLM calls are never cached
    The answer depends only on the question and city, so it is safe to share
    across users.
    """
    city = _normalize_city(active_city)
    # lowercase, collapse whitespace, drop trailing punctuation ("2.5 cr" stays intact)
    normalised = " ".join(query.lower().split()).strip(" ?!.,;:")
    key = (city, hashlib.sha256(normalised.encode("utf-8")).hexdigest())

    def compute():
        groq_budget.take()                        # raises BudgetExceeded (HTTP 429)
        return ask_with_status(query, active_city)  # (result, ok)

    (result, _ok), served = get_or_compute(
        chat_store, key, compute, pool=chat_pool, cacheable=lambda v: v[1]
    )
    return result, served


def get_localities_cached(city: str):
    """Returns (locality_list, cache_hit). Empty lists are not cached."""
    found, value = localities_store.get(city)
    if found:
        return value, True
    value = get_localities(city)
    if value:
        localities_store.set(city, value)
    return value, False