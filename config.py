"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATHS = {
    "mumbai":    BASE_DIR / "models" / "mumbai_price_model.pkl",
    "bengaluru": BASE_DIR / "models" / "bengaluru_price_model.pkl",
    "pune":      BASE_DIR / "models" / "pune_price_model.pkl",
}

RAG_DATA_PATHS = {
    "mumbai":    BASE_DIR / "rag_dfs" / "mumbai_cleaned_dataset.csv",
    "bengaluru": BASE_DIR / "rag_dfs" / "bengaluru_cleaned_dataset.csv",
    "pune":      BASE_DIR / "rag_dfs" / "pune_cleaned_dataset.csv",
}

SUPPORTED_CITIES = list(MODEL_PATHS.keys())

# All 3 datasets are from 2022 → inflate 3 years to reach 2025
DATASET_AGE_YEARS = 3

GROWTH_RATES = {
    "mumbai":    0.08,
    "bengaluru": 0.12,
    "pune":      0.06,
}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL    = "openai/gpt-oss-120b"
"""


import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATHS = {
    "mumbai": BASE_DIR / "models" / "mumbai_price_model.pkl",
    "bengaluru": BASE_DIR / "models" / "bengaluru_price_model.pkl",
    "pune": BASE_DIR / "models" / "pune_price_model.pkl",
}

RAG_DATA_PATHS = {
    "mumbai": BASE_DIR / "rag_dfs" / "mumbai_cleaned_dataset.csv",
    "bengaluru": BASE_DIR / "rag_dfs" / "bengaluru_cleaned_dataset.csv",
    "pune": BASE_DIR / "rag_dfs" / "pune_cleaned_dataset.csv",
}

SUPPORTED_CITIES = list(MODEL_PATHS.keys())

# Cached FAISS indexes
FAISS_INDEX_DIR = BASE_DIR / "faiss_indexes"

# All 3 datasets are from 2022 -> inflated by 3 years to reach 2025
DATASET_AGE_YEARS = 3

GROWTH_RATES = {
    "mumbai": 0.08,
    "bengaluru": 0.12,
    "pune": 0.06,
}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL = "openai/gpt-oss-120b"

#Database
DATA_DIR = BASE_DIR / "data"
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{(DATA_DIR / 'locallens.db').as_posix()}"
)

#Auth
# Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

#CORS
# Comma-separated list of allowed frontend origins
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

#Cache
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1") != "0"
CACHE_PREDICT_TTL_S = int(os.getenv("CACHE_PREDICT_TTL_S", str(6 * 3600)))
CACHE_PREDICT_MAXSIZE = int(os.getenv("CACHE_PREDICT_MAXSIZE", "10000"))
CACHE_CHAT_TTL_S = int(os.getenv("CACHE_CHAT_TTL_S", "900"))
CACHE_CHAT_MAXSIZE = int(os.getenv("CACHE_CHAT_MAXSIZE", "1000"))
CACHE_LOCALITIES_TTL_S = int(os.getenv("CACHE_LOCALITIES_TTL_S", str(24 * 3600)))