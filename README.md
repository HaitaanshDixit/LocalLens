# LocalLens Backend

> **Real estate price intelligence powered by machine learning and RAG**

LocalLens is a full-stack platform that brings transparency to Indian real estate pricing. This repository contains the **backend**: a FastAPI server that serves ML-based price predictions, inflation-adjusted forecasts, and a conversational RAG chatbot grounded in real property data. It is built to run on free tooling and includes the production-style protections a public API needs: authentication, caching, rate limiting and concurrency control.

---

## What This Does

LocalLens solves three real problems in the Indian housing market:

1. **Price opacity**: No one knows what a property is *actually* worth. Brokers give estimates, listings are outdated, and buyers are flying blind.
2. **Dataset staleness**: Public real estate data is very old. We apply inflation correction to make predictions relevant to today.
3. **Inaccessible insights**: Most people can't interpret "₹22,000/sqft." Our RAG chatbot answers questions in plain English, grounded in real data.

### What the backend provides

- **ML price prediction**: Random Forest and XGBoost models trained per city
- **Inflation adjustment**: Compound growth for present market prices
- **Future projection**: Project prices 1-20 years forward using per-city growth rates
- **RAG chatbot**: FAISS vector retrieval + Groq LLM for conversational queries
- **Locality search**: Fetch all valid localities per city from cleaned datasets
- **City comparison**: Side-by-side price rankings with automatic cheapest detection
- **Accounts and JWT auth**: Register and log in; expensive endpoints require a token
- **Caching**: Repeated predictions and questions are answered without re-running the model or the LLM
- **Rate limiting**: Per-IP and per-user limits, with a strict budget on chat
- **Concurrency control**: Caps on simultaneous requests, and identical in-flight requests share one computation
- **Fast, safe startup**: Models and indexes load once; the FAISS cache is validated and build-locked

---

## Architecture

```
  Client (Next.js frontend)
      |
      v
  FastAPI request pipeline
  ------------------------------------------------------------
  1. Per-IP rate limit (all endpoints)             -> 429
  2. App-wide in-flight cap                        -> 503 when full
  3. JWT authentication                            -> 401
  4. Per-user rate limit                           -> 429
  5. Per-user in-flight cap                        -> 429
      |
      v
  Routers:  /auth  /predict  /future  /compare  /localities  /chat
      |
      v
  TTL cache --- hit ---> return immediately   (X-Cache: HIT)
      | miss
      v
  Single-flight: identical in-flight requests share one computation
      |
      v
  Compute pool (ML: 16, chat: 4)                   -> 503 when full
      |                         |
      v                         v
  ML service                Groq budget  ->  RAG service
  (joblib models)           (429 if used up)  (FAISS + Groq API)

  Loaded once at startup (lifespan):
  SQLite tables | ML models | embedding model + warm-up | CSVs | FAISS indexes
```

Rejected requests are answered immediately. Nothing is queued, so a traffic spike cannot pile up threads or memory.

---

## Quick Start

### Prerequisites

- Python 3.10+
- pip
- A Groq API key (free tier)

### Installation

```bash
# Clone the repository
git clone https://github.com/HaitaanshDixit/LocalLens.git
cd LocalLens

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

`requirements.txt` must include these packages in addition to the original ones: `PyJWT`, `bcrypt`, `SQLAlchemy`, `email-validator`, `filelock`, `cachetools`, `limits`.

### Configuration

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_api_key_here
JWT_SECRET=paste_a_long_random_string_here
CORS_ORIGINS=http://localhost:3000
```

Generate a secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **Get a Groq API key:** Sign up at [https://console.groq.com](https://console.groq.com) → API Keys → Create new key
>
> The server refuses to start without `JWT_SECRET`. Every other setting has a default; see [Configuration reference](#configuration-reference).

### Build the search indexes (optional, recommended)

```bash
python build_indexes.py
```

The first run embeds every dataset row and takes a few minutes. After that, starts load the cached indexes in seconds. If you skip this step, the server builds them on its first start instead.

### Run the server

```bash
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000`

**Interactive docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Check it is working

1. Open `/ready`. It should return `"ready": true`.
2. In `/docs`, call `POST /auth/register`, then `POST /auth/login`, and copy the `access_token`.
3. Click **Authorize** and paste the token (without the word `Bearer`).
4. Call `POST /predict` twice with the same body. The second response header says `x-cache: HIT`.

---

## Authentication

Accounts are stored in SQLite (`data/locallens.db`) with a bcrypt-hashed password. Login returns a JWT (valid for 60 minutes by default) that is sent in the `Authorization` header. The token is verified by its signature and the user is looked up on each request, so deactivating an account takes effect immediately.

```bash
# Register
curl -X POST "http://127.0.0.1:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"name": "Asha", "email": "asha@example.com", "password": "a-long-password"}'

# Log in (returns access_token)
curl -X POST "http://127.0.0.1:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "asha@example.com", "password": "a-long-password"}'

# Use the token
curl "http://127.0.0.1:8000/auth/me" -H "Authorization: Bearer YOUR_TOKEN"
```

Passwords must be 8-72 bytes (a bcrypt limit). Login failures always say "Invalid email or password", and the response time does not reveal whether an email is registered.

---

## Model Files

The trained ML models (`.pkl` files) are **not included** in this repository due to GitHub's 100MB file size limit.

(You can directly reach out to the author for the same)

---

## API Endpoints

| Method | Endpoint             | Auth  | Description                                 |
|--------|----------------------|-------|---------------------------------------------|
| `GET`  | `/`                  | none  | Basic status                                |
| `GET`  | `/health`            | none  | Liveness check                              |
| `GET`  | `/ready`             | none  | Readiness: models, datasets and indexes loaded (503 if not) |
| `GET`  | `/cities`            | none  | Returns list of supported cities            |
| `GET`  | `/localities/{city}` | none  | Get all localities for a city               |
| `POST` | `/auth/register`     | none  | Create an account                           |
| `POST` | `/auth/login`        | none  | Log in, returns a JWT                       |
| `GET`  | `/auth/me`           | token | The logged-in user                          |
| `POST` | `/predict`           | token | Get current price (2025 inflation-adjusted) |
| `POST` | `/future`            | token | Get current + future price projection       |
| `POST` | `/compare`           | token | Compare prices across 2-3 cities            |
| `POST` | `/chat`              | token | Ask the RAG chatbot a question              |
| `GET`  | `/stats`             | token | Cache hit rates, concurrency slots, Groq usage today |

### Example: Price Prediction

**Request:**

```bash
curl -X POST "http://127.0.0.1:8000/predict" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "city": "mumbai",
    "bhk": 2,
    "area": 1000,
    "type": "Apartment",
    "region": "Andheri West",
    "status": "Ready to Move",
    "age": "0-5 years"
  }'
```

**Response** (illustrative values):

```json
{
  "city": "mumbai",
  "raw_price_per_sqft": 22771.45,
  "raw_total_price_lac": 227.71,
  "current_price_per_sqft": 28685.47,
  "current_total_price_inr": 28685468.82,
  "current_total_price_lac": 286.85,
  "area_sqft": 1000.0,
  "growth_rate_used": 0.08,
  "inflation_years_applied": 3
}
```

`raw_*` is the model output on the 2022 dataset; `current_*` is inflation-adjusted to 2025.

### Example: Chatbot Query

**Request:**

```bash
curl -X POST "http://127.0.0.1:8000/chat" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the average price of a 2 BHK in Andheri?",
    "city": "mumbai"
  }'
```

**Response** (example output):

```json
{
  "answer": "Based on the data, 2 BHK apartments in Andheri West average around ₹22,771 per sqft. For a 1000 sqft property, that comes to approximately ₹2.28 crores.",
  "sources": ["LocalLens dataset — Mumbai"]
}
```

### Response headers

| Header | Meaning |
|---|---|
| `X-Cache` | `HIT` (served from cache or shared with an identical in-flight request), `MISS`, or `PARTIAL` (`/compare` only: some cities were cached) |
| `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` | The tightest limit that applies to the request |
| `Retry-After` | Seconds to wait; sent with every 429 and 503 |

### Error responses

| Status | Meaning |
|---|---|
| `401` | Missing, invalid or expired token |
| `429` | Rate limit hit, too many of your own requests in progress, or the Groq budget is used up. The message says which |
| `503` | The server is at capacity. Retry after the `Retry-After` delay |

---

## How It Works

### 1. Data Preprocessing

Three city datasets (Mumbai, Bengaluru, Pune) are cleaned and standardized:

- Price conversion: Lakhs/Crores → INR
- Area conversion: Sq. Metres/Yards → sqft
- Outlier removal: Domain-specific thresholds
- Target variable: `price_per_sqft = price_in_inr / area`

Output: `rag_dfs/<city>_cleaned_dataset.csv`

### 2. Model Training

Three algorithms tested per city:

- Linear Regression (baseline)
- Random Forest
- XGBoost

**Selection criteria:** R² + MAE. When R² is similar, MAE breaks the tie.

**Results:**

| City      | Model         | R²   | MAE (₹/sqft) |
|-----------|---------------|------|--------------|
| Mumbai    | Random Forest | 0.83 | 2000         |
| Bengaluru | XGBoost       | 0.59 | 1576         |
| Pune      | Random Forest | 0.28 | 1976         |

Models saved as: `models/<city>_price_model.pkl`

### 3. Inflation Adjustment

Predictions are compounded forward using per-city growth rates:

| City      | Annual Growth Rate |
|-----------|--------------------|
| Mumbai    | 8%                 |
| Bengaluru | 12%                |
| Pune      | 6%                 |

Formula:

```
P_current = P_model × (1 + r)^3        (2022 → 2025)
P_future  = P_current × (1 + r)^n      (2025 → 2025+n years)
```

### 4. RAG Pipeline

**Embedding:**

- Each CSV row → sentence: "City: Mumbai. Locality: Andheri. BHK: 2..."
- Sentence → 384-dim vector using `all-MiniLM-L6-v2`
- Vectors stored in FAISS IndexFlatIP (cosine similarity)

**Query flow:**

1. User query → embedded using the same model
2. FAISS retrieves the top-8 similar property records
3. City detection: cross-city keywords → search all cities, else search the active city only
4. Retrieved rows + ML context → system prompt
5. Groq API generates a grounded answer
6. Return answer + sources

**FAISS cache:** each city's index is saved to `faiss_indexes/` together with a fingerprint of the data and embedding model. If a CSV changes, the index rebuilds automatically instead of serving stale vectors. Builds are written atomically and guarded by a file lock, so several processes can start together without corrupting the cache. The first build takes a few minutes; later starts load in seconds.

---

## System Design

### Startup preloading
Models, the embedding model (with a warm-up call), datasets and FAISS indexes load once in the FastAPI `lifespan`, with per-stage timing printed to the console. `/ready` returns 503 if any city is missing its model, dataset or index.

### Caching
- The ML call `predict_price_per_sqft` is cached, not each response, so `/predict`, `/future` and `/compare` reuse each other's work (the same property predicted for `/predict` and `/future` runs the model once).
- Chat answers are cached by city and normalized question (case, spacing and trailing punctuation ignored). Failed LLM answers are never cached.
- Locality lists are cached once per city.
- Caches are in-memory TTL caches (`cachetools`), thread-safe, and empty after every restart.

### Rate limiting
Built on the `limits` library with a moving window. Layers: a per-IP limit on every endpoint (applied before authentication, so floods of unauthenticated requests are cut off cheaply), a per-IP limit on login and registration (brute-force protection), and per-user limits on the ML endpoints and on chat. `/health`, `/ready` and `/` are exempt from the global limit.

### Concurrency control
- App-wide cap on requests in progress, and per-user caps (3 for ML endpoints, 1 for chat).
- Separate compute pools for ML (16) and chat (4). They apply only to cache misses, so cached answers are still served when the server is busy.
- **Single flight:** if several identical requests arrive at once, one computes and the others share its result. Six users asking the same question at the same moment cost one Groq call.
- Full means rejected immediately with 503 or 429, never queued.

### Groq budget
Only real Groq calls count: cache hits and shared requests are free. The per-minute count is in memory; the per-day count is stored in the database (UTC day), so a restart does not reset it. When the budget is used up, repeated questions are still answered from the cache. Set `GROQ_MAX_PER_MINUTE` and `GROQ_MAX_PER_DAY` just under the limits shown in your Groq console.

### Defaults

| Setting | Default |
|---|---|
| Global per-IP rate limit | 300/minute |
| ML endpoints per user | 60/minute |
| Chat per user | 10/minute and 100/day |
| Login per IP | 10/minute |
| Register per IP | 10/hour |
| App-wide requests in progress | 50 |
| ML requests in progress per user | 3 |
| Chat requests in progress per user | 1 |
| Model runs at once (cache misses) | 16 |
| Chat answers computed at once (cache misses) | 4 |
| Groq calls | 20/minute, 500/day |
| Prediction cache lifetime | 6 hours |
| Chat cache lifetime | 6 hours |
| Locality cache lifetime | 24 hours |

---

## Configuration reference

All settings are environment variables (in `.env`) and all are optional except the first two.

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET` | none, **required** | Signs login tokens |
| `GROQ_API_KEY` | none | Needed for `/chat` |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated frontend origins |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Login token lifetime |
| `DATABASE_URL` | SQLite file in `data/` | User accounts and Groq usage |
| `CACHE_ENABLED` | `1` | `0` turns all caching and request sharing off |
| `CACHE_PREDICT_TTL_S` / `CACHE_PREDICT_MAXSIZE` | `21600` / `10000` | Prediction cache |
| `CACHE_CHAT_TTL_S` / `CACHE_CHAT_MAXSIZE` | `21600` / `1000` | Chat cache |
| `CACHE_LOCALITIES_TTL_S` | `86400` | Locality cache |
| `RATE_LIMIT_ENABLED` | `1` | `0` turns rate limiting off |
| `RATE_LIMIT_GLOBAL_IP` | `300/minute` | All endpoints, per IP |
| `RATE_LIMIT_ML_USER` | `60/minute` | `/predict`, `/future`, `/compare`, per user |
| `RATE_LIMIT_CHAT_USER` | `10/minute;100/day` | `/chat`, per user |
| `RATE_LIMIT_LOGIN_IP` | `10/minute` | `/auth/login`, per IP |
| `RATE_LIMIT_REGISTER_IP` | `10/hour` | `/auth/register`, per IP |
| `CONCURRENCY_ENABLED` | `1` | `0` turns the concurrency caps off |
| `MAX_INFLIGHT_GLOBAL` | `50` | Requests in progress, whole app |
| `MAX_INFLIGHT_PER_USER_ML` / `MAX_INFLIGHT_PER_USER_CHAT` | `3` / `1` | Per user |
| `MAX_COMPUTE_ML` / `MAX_COMPUTE_CHAT` | `16` / `4` | Cache-miss work at once |
| `COALESCE_WAIT_TIMEOUT_S` | `60` | How long a request waits on an identical in-flight one |
| `GROQ_BUDGET_ENABLED` | `1` | `0` turns the Groq budget off |
| `GROQ_MAX_PER_MINUTE` / `GROQ_MAX_PER_DAY` | `20` / `500` | Real Groq calls |

Limit values use the form `60/minute`, or several at once: `10/minute;100/day`.

---

## Project Structure

```
locallens-backend/
├── main.py                  # App, startup (lifespan), CORS, router wiring, /health /ready /stats
├── config.py                # Paths, cities, growth rates, LLM, auth, cache, limit settings
├── schemas.py               # Pydantic request/response models
├── auth_schemas.py          # Pydantic models for register / login
├── database.py              # SQLAlchemy engine and sessions
├── db_models.py             # User table
├── security.py              # Password hashing and JWT create/verify
├── dependencies.py          # get_current_user (token check)
├── ratelimit.py             # Rate limit dependencies
├── concurrency.py           # In-flight slot caps and pools
├── guards.py                # App-wide and per-user concurrency dependencies
├── groq_budget.py           # Per-minute and per-day cap on Groq calls
├── cache.py                 # TTL cache with single-flight request sharing
├── build_indexes.py         # Pre-build the FAISS indexes
├── requirements.txt         # Python dependencies
├── .env                     # Secrets and settings (not committed)
│
├── services/
│   ├── ml_service.py        # Load models, predict (cached), status
│   └── rag_service.py       # FAISS indexing, retrieval, Groq API, cached chat
│
├── routers/
│   ├── auth.py              # POST /auth/register, /auth/login, GET /auth/me
│   ├── predict.py           # POST /predict
│   ├── future.py            # POST /future
│   ├── compare.py           # POST /compare
│   ├── localities.py        # GET /localities/{city}
│   └── chat.py              # POST /chat
│
├── models/                  # .pkl model files (trained separately, not committed)
│   ├── mumbai_price_model.pkl
│   ├── bengaluru_price_model.pkl
│   └── pune_price_model.pkl
│
├── rag_dfs/                 # Cleaned datasets for RAG
│   ├── mumbai_cleaned_dataset.csv
│   ├── bengaluru_cleaned_dataset.csv
│   └── pune_cleaned_dataset.csv
│
├── faiss_indexes/           # Cached FAISS indexes (auto-generated)
│   ├── <city>.index
│   ├── <city>.meta.json
│   └── <city>.lock
│
├── data/                    # SQLite database (auto-generated, not committed)
│   └── locallens.db
│
└── model_files/             # Training scripts (reference only)
    ├── mum.py
    ├── beng.py
    └── pun.py
```

Add `data/`, `faiss_indexes/` and `.env` to `.gitignore`.

---

## Tech Stack

| Layer           | Technology                               |
|-----------------|------------------------------------------|
| **Framework**   | FastAPI, Uvicorn                         |
| **ML**          | scikit-learn, XGBoost, joblib            |
| **RAG**         | FAISS (faiss-cpu), sentence-transformers |
| **LLM**         | Groq API (llama-3.3-70b-versatile)       |
| **Auth**        | PyJWT, bcrypt                            |
| **Database**    | SQLAlchemy, SQLite                       |
| **Caching**     | cachetools                               |
| **Rate limiting** | limits                                 |
| **Locking**     | filelock                                 |
| **Validation**  | Pydantic                                 |
| **Environment** | python-dotenv                            |
| **HTTP Client** | requests                                 |

**Why these choices?**

- **FastAPI:** Auto-generates OpenAPI docs, Pydantic validation out of the box, and runs plain functions in a worker threadpool
- **XGBoost/Random Forest:** Strong performers on tabular real estate data
- **FAISS:** Industry standard for vector search, runs locally
- **Groq:** Free tier, low latency, strong instruction-following with llama-3.3-70b
- **sentence-transformers:** Pre-trained semantic embeddings, no training required
- **SQLite + in-memory caches:** No extra services to run; each can be swapped for Postgres or Redis later without changing the API

---

## Development

### Add a New City

1. **Prepare dataset:** Clean CSV with columns matching the schema the models were trained on
2. **Train model:** Run a training script (see `model_files/mum.py` as template)
3. **Save model:** `joblib.dump(pipeline, "models/newcity_price_model.pkl")`
4. **Update `config.py`:** Add the city to `MODEL_PATHS`, `RAG_DATA_PATHS` and `GROWTH_RATES`
5. **Add cleaned CSV:** Save to `rag_dfs/newcity_cleaned_dataset.csv`
6. **Restart the server** (or run `python build_indexes.py`): its FAISS index builds automatically

### Quick checks

```bash
# Is everything loaded?
curl http://127.0.0.1:8000/ready

# Cache: send the same /predict request twice and compare the x-cache header
curl -i -X POST http://127.0.0.1:8000/predict -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" -d '{...}'

# Rate limit: set RATE_LIMIT_ML_USER=3/minute in .env, restart, then call /predict
# four times. The fourth returns 429 with a Retry-After header.
```

For load testing from one machine, switch the protections off with `RATE_LIMIT_ENABLED=0`, `CONCURRENCY_ENABLED=0` and `CACHE_ENABLED=0`, then turn them back on to compare.

### Debug Mode

```bash
# Enable auto-reload on code changes
uvicorn main:app --reload --log-level debug
```

---

## Deployment notes

- **Behind a reverse proxy** (Nginx, a platform load balancer): every request appears to come from the proxy's IP, so the per-IP limits would throttle all users together. Start uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy IP>`, using the proxy's real address, not `*`.
- **Several workers:** each worker has its own cache, rate-limit counters and concurrency counters, and loads its own copy of the models and indexes. The user and Groq-usage data in SQLite is shared. Redis would be the fix for sharing the in-memory parts.
- **First start:** run `python build_indexes.py` during deployment so the server starts from cached indexes.
- **Secrets:** never commit `.env`. Rotating `JWT_SECRET` logs everyone out.

---

## Performance

Approximate latency without caching:

| Operation                         | Latency     |
|-----------------------------------|-------------|
| `/predict` (ML inference)         | < 100ms     |
| `/future`                         | < 100ms     |
| `/compare` (2 cities)             | < 200ms     |
| `/localities/{city}`              | < 50ms      |
| `/chat` (FAISS + Groq)            | 5-8 seconds |
| FAISS index build (first startup) | 3-5 minutes |
| FAISS index load (cached)         | < 5 seconds |

Cached requests skip the model or the LLM entirely. Load-test results comparing the protections on and off will be added here.

**Model Accuracy:**

- **Mumbai:** R² = 0.83, MAE = ₹2,000/sqft (±₹20L on 1000 sqft)
- **Bengaluru:** R² = 0.59, MAE = ₹1,576/sqft
- **Pune:** R² = 0.28, MAE = ₹1,976/sqft (dataset is inherently noisy)

---

## Known Issues & Limitations

1. **Dataset age:** Currently using 2022 data with inflation correction. A future version will integrate live listings.
2. **Locality encoding:** Excluded from model features to prevent overfitting on smaller datasets. This limits price variation capture within cities.
3. **Weak Pune model:** R² of 0.28 means the Pune estimates are rough.
4. **Groq free tier:** Rate limits and occasional latency spikes. The built-in budget protects the quota, but when it is used up, new (uncached) questions are refused until the next day.
5. **Per-process state:** Caches, rate-limit counters and concurrency counters are held in memory, so they reset on restart and are not shared between workers.
6. **No logout or token revocation:** Tokens are valid until they expire (60 minutes by default). Deactivating a user blocks them immediately, though.
7. **Rephrased questions miss the chat cache:** Only the same question (ignoring case, spacing and trailing punctuation) is reused.
8. **Model files are not in the repo:** `/predict` cannot run without them.

---

## Acknowledgments

- **Open-source communities:** FastAPI, scikit-learn, XGBoost, FAISS, sentence-transformers, Hugging Face
- **Data sources:** Public real estate listing datasets
- **Market research:** Anarock Property Consultants, Knight Frank India
- **LLM API:** Groq for providing free-tier access to openai/gpt-oss-120b