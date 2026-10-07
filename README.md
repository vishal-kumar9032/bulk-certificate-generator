# Bulk Certificate Generator API

A high-performance, resilient backend API built with FastAPI, SQLAlchemy 2.x, and ReportLab that processes bulk certificate generation requests asynchronously in-process. Designed specifically to handle real-world challenges such as partial failures, graceful degradation, crash recovery, and live progress reporting without heavy external broker dependencies.

---

## 1. Overview & Key Features

- **Single Bulk Request API:** Submit hundreds or thousands of recipients in a single HTTP `POST` request.
- **Asynchronous In-Process Processing:** Returns `202 Accepted` immediately with status polling URLs, offloading PDF rendering to a background `ThreadPoolExecutor`.
- **Per-Item Isolation & Failure Containment:** Each recipient certificate is rendered inside its own try/except block and committed in an isolated database transaction. A failure for one recipient (e.g. invalid email, missing name, or font error) never fails or halts the rest of the batch.
- **Lenient Recipient Validation:** Malformed or duplicate recipient data does not reject the entire bulk request; invalid items are persisted with descriptive error messages explaining why they failed.
- **Live Progress & Granular Inspection:** Polling the job status endpoint returns real-time completion counts and progress percentages. A dedicated certificates listing endpoint lets clients inspect the exact status and error message of every recipient.
- **Professional PDF Certificate Generation:** High-quality landscape A4 certificates generated via ReportLab with auto-scaling fonts to prevent text overflow, decorative borders, unique verification codes, and bundled TrueType font (`DejaVuSans.ttf`) support for Unicode names.
- **Safe Batch & Single Retrieval:** Download single certificates with sanitized filenames or download a consolidated ZIP archive containing all successful certificates.
- **Crash Recovery & Idempotency:** Any jobs left in `PENDING` or `PROCESSING` due to an unexpected server restart are automatically recovered on application startup without re-generating already completed certificates.
- **Deterministic Testing:** Includes a `SYNC_MODE` configuration switch allowing test suites and debugging runs to execute synchronously without sleeping or polling.

---

## 2. Tech Stack

- **Python:** 3.11+ (tested on Python 3.12)
- **FastAPI:** Modern, high-performance web framework for request routing, dependency injection, and OpenAPI documentation
- **Uvicorn:** ASGI production server
- **SQLAlchemy 2.x:** Relational ORM configured with SQLite (WAL mode, multi-threaded connection pooling, and swappable PostgreSQL support via environment variable)
- **Pydantic v2 & Pydantic-Settings:** Data validation, strict request/response serialization, and environment configuration
- **ReportLab:** Pure-Python vector PDF rendering engine for landscape A4 canvas generation
- **email-validator:** RFC-compliant email validation and normalization
- **pytest & httpx:** Comprehensive test suite with isolated environments

---

## 3. Setup & Installation

### Prerequisites
- Python 3.11 or higher
- Git

### 1. Clone & create virtual environment
```bash
git clone <repo-url>
cd bulk-certificate-generator

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Linux / macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
.\.venv\Scripts\activate.bat
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment configuration
Copy the example environment configuration file:
```bash
# On Linux / macOS:
cp .env.example .env
# On Windows:
copy .env.example .env
```

Configuration variables in `.env`:
| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | SQLAlchemy database connection URI |
| `STORAGE_DIR` | `./storage` | Filesystem path for generated PDFs and archives |
| `WORKER_THREADS` | `4` | Number of concurrent worker threads in thread pool |
| `MAX_RECIPIENTS_PER_JOB` | `1000` | Maximum recipient entries allowed per bulk job |
| `SYNC_MODE` | `false` | When `true`, processes jobs inline in the POST request |

---

## 4. Running the Application

Start the development server with Uvicorn:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Or via Makefile:
```bash
make run
```

### Interactive API Documentation (Swagger)
Once the server is running, navigate to:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

## 5. Running Tests

Run the test suite with verbose output:
```bash
pytest -v
```
Or via Makefile:
```bash
make test
```

All tests execute in isolated temporary environments (fresh SQLite databases and storage directories per test) with `SYNC_MODE=true` to guarantee deterministic, non-flaky execution.

---

## 6. Submitting a Generation Request

### Using `curl`
```bash
curl -X POST http://localhost:8000/api/v1/certificate-jobs \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "Cloud Native Architecture Bootcamp 2026",
    "issuer_name": "Acme Academy",
    "issue_date": "2026-10-01",
    "recipients": [
      {"name": "Asha Verma", "email": "asha@example.com"},
      {"name": "Rohan Das", "email": "rohan@example.com"},
      {"name": "", "email": "missing-name@example.com"},
      {"name": "Duplicate Person", "email": "asha@example.com"},
      {"name": "Bad Email User", "email": "not-an-email"}
    ]
  }'
```

**Response (`202 Accepted`):**
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "PENDING",
  "total_count": 5,
  "status_url": "/api/v1/certificate-jobs/9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
}
```

### Using Python (`requests`)
```python
import time
import requests

BASE_URL = "http://localhost:8000"

payload = {
    "event_name": "Python & Distributed Systems Workshop",
    "issuer_name": "Acme Engineering",
    "issue_date": "2026-10-01",
    "recipients": [
        {"name": "Alice Smith", "email": "alice@example.com"},
        {"name": "Bob Jones", "email": "bob@example.com"},
    ],
}

# 1. Submit bulk job
response = requests.post(f"{BASE_URL}/api/v1/certificate-jobs", json=payload)
response.raise_for_status()
job_data = response.json()
job_id = job_data["job_id"]
status_url = f"{BASE_URL}{job_data['status_url']}"
print(f"Submitted Job ID: {job_id}")

# 2. Poll until complete
while True:
    status_resp = requests.get(status_url).json()
    status = status_resp["status"]
    progress = status_resp["progress_percent"]
    print(f"Progress: {progress}% | Status: {status}")
    if status in ["COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"]:
        break
    time.sleep(0.5)

print(f"Job finished: {status_resp}")
```

---

## 7. Checking Status & Retrieving Certificates

### 1. Check Job Status & Progress
```bash
curl http://localhost:8000/api/v1/certificate-jobs/<job_id>
```
**Example Response:**
```json
{
  "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "event_name": "Cloud Native Architecture Bootcamp 2026",
  "issuer_name": "Acme Academy",
  "issue_date": "2026-10-01",
  "status": "COMPLETED_WITH_ERRORS",
  "total_count": 5,
  "success_count": 2,
  "failed_count": 3,
  "pending_count": 0,
  "progress_percent": 100,
  "created_at": "2026-10-07T15:30:00.000000Z",
  "started_at": "2026-10-07T15:30:00.100000Z",
  "completed_at": "2026-10-07T15:30:00.500000Z",
  "download_all_url": "/api/v1/certificate-jobs/9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d/download"
}
```

### 2. Inspect Recipient Items & Failure Reasons
```bash
# Fetch paginated items (defaults: limit=50, offset=0)
curl "http://localhost:8000/api/v1/certificate-jobs/<job_id>/certificates?limit=50&offset=0"

# Filter by status (SUCCESS, FAILED, PENDING)
curl "http://localhost:8000/api/v1/certificate-jobs/<job_id>/certificates?status=FAILED"
```

### 3. Download an Individual Certificate PDF
```bash
curl -OJ "http://localhost:8000/api/v1/certificate-jobs/<job_id>/certificates/<certificate_id>/download"
```
*(The `-OJ` flag saves the file using the server-provided `Content-Disposition` filename, e.g., `certificate_asha-verma.pdf`.)*

### 4. Download All Certificates as a ZIP Archive
```bash
curl -OJ "http://localhost:8000/api/v1/certificate-jobs/<job_id>/download"
# Or specifying filename explicitly:
curl -o certificates.zip "http://localhost:8000/api/v1/certificate-jobs/<job_id>/download"
```

---

## 8. API Reference Table

| Method | Path | Purpose | Success Status | Error Statuses |
|---|---|---|---|---|
| `GET` | `/health` | Liveness & health check | `200 OK` | — |
| `POST` | `/api/v1/certificate-jobs` | Submit a bulk generation job | `202 Accepted` | `422 Unprocessable Entity` |
| `GET` | `/api/v1/certificate-jobs/{job_id}` | Retrieve job progress & status | `200 OK` | `404 Not Found` |
| `GET` | `/api/v1/certificate-jobs/{job_id}/certificates` | List recipient items (paginated) | `200 OK` | `404 Not Found` |
| `GET` | `/api/v1/certificate-jobs/{job_id}/certificates/{certificate_id}/download` | Download individual certificate PDF | `200 OK` | `404 Not Found`, `409 Conflict` |
| `GET` | `/api/v1/certificate-jobs/{job_id}/download` | Download ZIP archive of certificates | `200 OK` | `404 Not Found`, `409 Conflict` |
| `GET` | `/api/v1/certificates/verify/{verification_code}` | Public certificate verification | `200 OK` | `404 Not Found` |
| `POST` | `/api/v1/certificate-jobs/{job_id}/retry-failed` | Retry items failed during generation | `200 OK` | `404 Not Found` |

---

## 9. Design Decisions & Architecture

### 1. In-Process Asynchronous Background Processing
- **Why chosen:** Bulk certificate requests can contain hundreds or thousands of recipients. Synchronous PDF generation inside a single HTTP request would quickly exceed gateway/client timeout limits (e.g. 30–60s) and block client threads. An in-process `ThreadPoolExecutor` provides true concurrency without the heavy operational burden, configuration, and infrastructure dependencies of an external message broker (Celery, RabbitMQ, or Redis).
- **Trade-offs:** Jobs are bound to the host application process. Horizontal scaling across multiple nodes is not possible without an external message broker and shared storage.
- **Production Transition:** In a horizontally scaled production deployment, this model would naturally transition to a distributed task queue (Celery or RQ) backed by Redis or RabbitMQ, with shared object storage (AWS S3 / Google Cloud Storage) and PostgreSQL.

### 2. Per-Item Isolation & Granular Database Transactions
- Each recipient certificate is processed in its own `try/except` block and committed in an individual database transaction.
- If one recipient fails (e.g. invalid name, font rendering issue, or corrupted data), that item is marked `FAILED` with its specific error message, while all remaining valid items continue unaffected.
- Committing after each item ensures that external clients polling `GET /api/v1/certificate-jobs/{job_id}` see live, real-time increments in `progress_percent`, `success_count`, and `failed_count`.

### 3. Lenient Recipient Validation vs. Strict Request Validation
- **Request-Level Strictness (HTTP 422):** Fundamental contract violations—such as missing `event_name`, blank `event_name`, `event_name` exceeding 150 characters, empty `recipients` array, or exceeding `MAX_RECIPIENTS_PER_JOB`—immediately reject the entire request with `422 Unprocessable Entity` before any database records are written.
- **Recipient-Level Leniency (HTTP 202):** Malformed individual items (e.g., missing name, invalid email format, duplicates) do not fail the batch. Instead, they are parsed leniently, stored as `FAILED` items with clear error messages, and returned in the job details.
- **Why create the job even if ALL recipients fail?** If a user uploads a batch of 50 recipients and all 50 fail validation, creating the job and returning `202 Accepted` allows the user to inspect the exact failure reason for every single item via the API rather than receiving a generic top-level error.

### 4. Job Status Derivation Rules
Job status transitions strictly adhere to clear state rules:
- `PENDING`: Job created; processing not yet initiated.
- `PROCESSING`: Worker thread actively generating certificates.
- `COMPLETED`: All items successfully generated (`success_count == total_count`).
- `COMPLETED_WITH_ERRORS`: At least one item succeeded, and at least one item failed (`success_count > 0` and `failed_count > 0`).
- `FAILED`: Zero items succeeded (`success_count == 0` and `failed_count == total_count`).

### 5. Storage Layout & Path Traversal Prevention
- Storage layout follows a strict identifier structure: `storage/<job_id>/<certificate_id>.pdf`.
- File paths on disk are generated strictly using server-assigned UUIDs, completely preventing directory traversal vulnerabilities (`../../etc/passwd`).
- User-supplied recipient names are only used in the `Content-Disposition` header after regex sanitization (`[^a-zA-Z0-9]+` converted to hyphens).

### 6. Thread Safety, Session Handling & SQLite WAL Mode
- SQLAlchemy sessions are **never** shared across threads. Every worker thread and background job task obtains its own isolated session via the `get_db_session()` context manager.
- SQLite is configured with `check_same_thread=False` and automatically initializes `PRAGMA journal_mode=WAL` (Write-Ahead Logging), `PRAGMA synchronous=NORMAL`, and `PRAGMA foreign_keys=ON` on every connection. WAL mode allows concurrent readers to proceed without blocking writers and vice versa.

### 7. Startup Recovery & Idempotency
- When the FastAPI application boots up, the lifespan handler scans the database for any jobs left in `PENDING` or `PROCESSING` state (such as after an unexpected server crash or restart).
- Incomplete jobs are automatically re-enqueued to the worker pool.
- Items already marked `SUCCESS` are skipped, ensuring that recovery runs are completely idempotent and never re-generate existing files.

### 8. Duplicate Email Policy
- If the same email address appears multiple times within the same request payload (case-insensitively), the **first occurrence wins**.
- Subsequent duplicate occurrences are marked `FAILED` with an informative error: `"duplicate email in this request (first seen at index {first_idx})"`.

### 9. Request Size Limits (`MAX_RECIPIENTS_PER_JOB`)
- Governed by `settings.MAX_RECIPIENTS_PER_JOB` (default 1,000).
- Exceeding this limit immediately raises an HTTP 422 error detailing the exact limit, safeguarding server memory and thread queue capacity.

### 10. Unicode Font Handling & Graceful Fallback
- Bundles the open-source **DejaVu Sans** TrueType font in `app/assets/fonts/DejaVuSans.ttf` (licensed under the Bitstream Vera / DejaVu Font License).
- ReportLab registers DejaVu Sans at startup, providing native support for accented Latin characters, extended scripts, and non-ASCII names.
- If the font file is missing, the renderer logs a warning and falls back to standard `Helvetica`.
- Before drawing strings, font encoding compatibility is checked; if unsupported glyphs exist, that single certificate fails gracefully rather than crashing the worker thread.

---

## 10. Known Limitations & Production Roadmap

If migrating this backend from a single-node take-home implementation to a high-scale production enterprise service:

1. **Distributed Task Queue:** Replace the in-process `ThreadPoolExecutor` with **Celery**, **RQ**, or **Temporal** using **Redis** or **RabbitMQ** as the message broker, allowing worker nodes to autoscale independently from web nodes.
2. **Distributed Object Storage:** Replace local filesystem storage (`./storage`) with cloud object storage (**AWS S3**, **Google Cloud Storage**, or **Azure Blob Storage**) with signed URLs for direct client downloads.
3. **Database Migration:** Switch from SQLite to managed **PostgreSQL** (already supported via changing `DATABASE_URL` in `.env`) with **Alembic** database migrations.
4. **Authentication & Multi-Tenancy:** Implement OAuth2 / JWT authentication (or API keys) with tenant isolation so organizations can only access their own jobs and certificates.
5. **Rate Limiting:** Protect generation endpoints with token-bucket rate limiting (e.g. `slowapi` or Redis-based rate limiting).
6. **Webhooks / Event Notifications:** Send HTTP POST webhooks to the client's notification URL once a bulk job transitions to `COMPLETED` or `COMPLETED_WITH_ERRORS`.

---

## 11. Project Structure

```
bulk/
├── .env.example                  # Environment configuration template
├── .gitignore                    # Git ignore file (storage, db, cache)
├── Makefile                      # Developer shortcuts (install, run, test, clean)
├── README.md                     # Architecture, documentation, and user guide
├── pytest.ini                    # Pytest configuration
├── requirements.txt              # Pinned production and test dependencies
├── app/
│   ├── __init__.py
│   ├── main.py                   # App factory, lifespan, health check, recovery
│   ├── settings.py               # Pydantic-settings configuration
│   ├── database.py               # SQLAlchemy engine, WAL pragma, session management
│   ├── models.py                 # SQLAlchemy ORM models (CertificateJob, CertificateItem)
│   ├── schemas.py                # Pydantic v2 request & response schemas
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py             # Thin FastAPI route handlers
│   ├── services/
│   │   ├── __init__.py
│   │   ├── job_service.py        # Lenient validation, job creation, querying
│   │   ├── processor.py          # Worker pool, per-item execution, crash recovery
│   │   ├── certificate_renderer.py # ReportLab canvas, auto-scaling, atomic writes
│   │   └── zip_builder.py        # Streaming ZIP archive packaging
│   └── assets/
│       └── fonts/
│           ├── DejaVuSans.ttf    # Bundled Unicode TrueType font
│           └── LICENSE           # DejaVu font license
└── tests/
    ├── __init__.py
    ├── conftest.py               # Isolated temp DB & storage fixtures, TestClient
    ├── test_async_processing.py  # Asynchronous background thread execution test
    ├── test_certificate_generation.py # PDF generation, header & layout verification
    ├── test_create_job.py        # Job creation & health check tests
    ├── test_failure_handling.py  # Per-item error isolation & monkeypatched failures
    ├── test_job_status.py        # Progress tracking & final status derivation
    ├── test_recovery_and_extras.py # Idempotency, crash recovery & verification endpoint
    ├── test_retrieval.py         # PDF download, ZIP download, pagination, filters
    └── test_validation.py        # Request-level & recipient-level validation rules
```

---

## 12. License
This project is open-source. Bundled fonts in `app/assets/fonts/` are subject to the DejaVu Fonts License (see [app/assets/fonts/LICENSE](app/assets/fonts/LICENSE)).
