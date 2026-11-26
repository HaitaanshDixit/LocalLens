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

# Cached FAISS indexes (auto-generated; keep out of git)
FAISS_INDEX_DIR = BASE_DIR / "faiss_indexes"

# All 3 datasets are from 2022 -> inflate 3 years to reach 2025
DATASET_AGE_YEARS = 3

GROWTH_RATES = {
    "mumbai": 0.08,
    "bengaluru": 0.12,
    "pune": 0.06,
}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL = "openai/gpt-oss-120b"

DATA_DIR = BASE_DIR / "data"
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{(DATA_DIR / 'locallens.db').as_posix()}"
)

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1") != "0"
CACHE_PREDICT_TTL_S = int(os.getenv("CACHE_PREDICT_TTL_S", str(6 * 3600)))
CACHE_PREDICT_MAXSIZE = int(os.getenv("CACHE_PREDICT_MAXSIZE", "10000"))
CACHE_CHAT_TTL_S = int(os.getenv("CACHE_CHAT_TTL_S", str(6 * 3600)))  # dataset is static, so long is safe
CACHE_CHAT_MAXSIZE = int(os.getenv("CACHE_CHAT_MAXSIZE", "1000"))
CACHE_LOCALITIES_TTL_S = int(os.getenv("CACHE_LOCALITIES_TTL_S", str(24 * 3600)))

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") != "0"
RATE_LIMIT_GLOBAL_IP = os.getenv("RATE_LIMIT_GLOBAL_IP", "300/minute")      # all endpoints, per IP
RATE_LIMIT_ML_USER = os.getenv("RATE_LIMIT_ML_USER", "60/minute")           # /predict /future /compare, per user
RATE_LIMIT_CHAT_USER = os.getenv("RATE_LIMIT_CHAT_USER", "10/minute;100/day")  # /chat, per user
RATE_LIMIT_LOGIN_IP = os.getenv("RATE_LIMIT_LOGIN_IP", "10/minute")         # /auth/login, per IP
RATE_LIMIT_REGISTER_IP = os.getenv("RATE_LIMIT_REGISTER_IP", "10/hour")     # /auth/register, per IP

CONCURRENCY_ENABLED = os.getenv("CONCURRENCY_ENABLED", "1") != "0"
MAX_INFLIGHT_GLOBAL = int(os.getenv("MAX_INFLIGHT_GLOBAL", "50"))             # all requests at once
MAX_INFLIGHT_PER_USER_ML = int(os.getenv("MAX_INFLIGHT_PER_USER_ML", "3"))    # /predict /future /compare per user
MAX_INFLIGHT_PER_USER_CHAT = int(os.getenv("MAX_INFLIGHT_PER_USER_CHAT", "1"))  # /chat per user
MAX_COMPUTE_ML = int(os.getenv("MAX_COMPUTE_ML", "16"))      # model runs at once (cache misses only)
MAX_COMPUTE_CHAT = int(os.getenv("MAX_COMPUTE_CHAT", "4"))   # chat answers computed at once (cache misses only)
COALESCE_WAIT_TIMEOUT_S = int(os.getenv("COALESCE_WAIT_TIMEOUT_S", "60"))

GROQ_BUDGET_ENABLED = os.getenv("GROQ_BUDGET_ENABLED", "1") != "0"
GROQ_MAX_PER_MINUTE = int(os.getenv("GROQ_MAX_PER_MINUTE", "20"))
GROQ_MAX_PER_DAY = int(os.getenv("GROQ_MAX_PER_DAY", "500"))