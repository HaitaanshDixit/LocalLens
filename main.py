from dotenv import load_dotenv

load_dotenv()

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import groq_budget
from cache import all_stats
from concurrency import stats as concurrency_stats
from concurrency import user_chat, user_ml
from database import init_db
from dependencies import get_current_user
from guards import global_inflight, user_concurrency
from ratelimit import global_ip_limit, rate_limit_user
from routers import auth, chat, compare, future, localities, predict
from services.ml_service import get_status as ml_status
from services.ml_service import load_all_models
from services.rag_service import get_status as rag_status
from services.rag_service import load_all_rag_data


def _timed(label: str, fn) -> None:
    t = time.perf_counter()
    fn()
    print(f"[startup] {label}: {time.perf_counter() - t:.2f}s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    t_start = time.perf_counter()
    print("LocalLens starting up...")

    if not config.JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is not set. Add it to .env "
            '(python -c "import secrets; print(secrets.token_urlsafe(48))")'
        )

    _timed("database", init_db)               # creates the users table on first run
    _timed("Groq usage table", groq_budget.ensure_table)
    _timed("ML models", load_all_models)      # joblib loads all .pkl files
    _timed("RAG data + FAISS", load_all_rag_data)  # CSVs, embedder, FAISS indexes

    app.state.startup_seconds = round(time.perf_counter() - t_start, 2)
    print(f"Ready in {app.state.startup_seconds}s.")
    yield
    print("Shutting down.")


app = FastAPI(
    title="LocalLens API",
    description="Housing price prediction for Mumbai, Bengaluru & Pune",
    version="1.1.0",
    lifespan=lifespan,
    dependencies=[Depends(global_ip_limit), Depends(global_inflight)],  # per-IP limit, then app-wide in-flight cap
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,  # tokens travel in the Authorization header, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[  # let the browser frontend read these
        "X-Cache", "Retry-After",
        "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
    ],
)

# Public
app.include_router(auth.router)
app.include_router(localities.router)

# Require a valid token, then apply that user's rate limit.
# /predict, /future and /compare share one "ml" budget; /chat has its own, tighter one.
auth_required = Depends(get_current_user)
ml_limit = Depends(rate_limit_user("ml", config.RATE_LIMIT_ML_USER))
chat_limit = Depends(rate_limit_user("chat", config.RATE_LIMIT_CHAT_USER))
ml_conc = Depends(user_concurrency(user_ml))      # max simultaneous requests per user
chat_conc = Depends(user_concurrency(user_chat))

app.include_router(predict.router, dependencies=[auth_required, ml_limit, ml_conc])
app.include_router(future.router, dependencies=[auth_required, ml_limit, ml_conc])
app.include_router(compare.router, dependencies=[auth_required, ml_limit, ml_conc])
app.include_router(chat.router, dependencies=[auth_required, chat_limit, chat_conc])


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "project": "LocalLens", "version": "1.1.0"}


@app.get("/health", tags=["Health"])
def health():
    """Liveness: the process is up and answering."""
    return {"status": "ok"}


@app.get("/ready", tags=["Health"])
def ready(request: Request):
    """Readiness: every city has a model, a dataset and a FAISS index loaded."""
    models = ml_status()
    rag = rag_status()
    ok = all(models.values()) and rag["ready"]
    body = {
        "ready": ok,
        "startup_seconds": getattr(request.app.state, "startup_seconds", None),
        "models": models,
        "rag": rag,
    }
    return JSONResponse(body, status_code=200 if ok else 503)


@app.get("/cities", tags=["Health"])
def cities():
    return {"cities": config.SUPPORTED_CITIES}


@app.get("/stats", tags=["Health"], dependencies=[Depends(get_current_user)])
def stats():
    """Cache hit rates, concurrency slots in use, and today's Groq usage."""
    return {"cache": all_stats(), "concurrency": concurrency_stats(), "groq": groq_budget.status()}