# ForgeAI — Setup Guide

## 1. Complete Folder Tree

```
forgeai/
├── .env.example
├── docker-compose.yml
├── SAD.md
├── SETUP.md
├── scripts/
│   └── init-test-db.sql
│
├── backend/
│   ├── .env.example
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── Dockerfile
│   │
│   ├── alembic/
│   │   ├── versions/              ← auto-generated migration files
│   │   ├── env.py
│   │   └── script.py.mako
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py          ← pydantic-settings
│   │   │   ├── security.py        ← JWT + bcrypt
│   │   │   ├── exceptions.py      ← domain exception hierarchy
│   │   │   └── logging.py         ← structlog
│   │   │
│   │   ├── domain/                ← Layer 1: zero deps
│   │   │   ├── entities/
│   │   │   │   ├── user.py
│   │   │   │   ├── project.py
│   │   │   │   ├── agent_run.py
│   │   │   │   ├── agent_step.py
│   │   │   │   └── artifact.py
│   │   │   └── value_objects/
│   │   │       ├── project_status.py
│   │   │       ├── run_status.py
│   │   │       ├── agent_type.py
│   │   │       └── artifact_type.py
│   │   │
│   │   ├── application/           ← Layer 2: use cases
│   │   │   ├── interfaces/
│   │   │   │   ├── user_repository.py
│   │   │   │   ├── project_repository.py
│   │   │   │   ├── run_repository.py
│   │   │   │   └── artifact_repository.py
│   │   │   └── services/
│   │   │       ├── auth_service.py
│   │   │       └── project_service.py
│   │   │
│   │   ├── infrastructure/        ← Layer 3: framework adapters
│   │   │   ├── database/
│   │   │   │   ├── base.py        ← DeclarativeBase + TimestampMixin
│   │   │   │   ├── session.py     ← async engine + get_db
│   │   │   │   └── models/
│   │   │   │       ├── __init__.py  ← registers all models
│   │   │   │       ├── user.py
│   │   │   │       ├── project.py
│   │   │   │       ├── agent_run.py
│   │   │   │       ├── agent_step.py
│   │   │   │       ├── artifact.py
│   │   │   │       └── llm_call.py
│   │   │   └── repositories/
│   │   │       ├── user_repository.py
│   │   │       ├── project_repository.py
│   │   │       ├── run_repository.py
│   │   │       └── artifact_repository.py
│   │   │
│   │   ├── schemas/               ← Pydantic v2 request/response
│   │   │   ├── common.py
│   │   │   ├── auth.py
│   │   │   ├── user.py
│   │   │   ├── project.py
│   │   │   ├── run.py
│   │   │   └── artifact.py
│   │   │
│   │   └── api/                   ← Layer 4: HTTP boundary
│   │       ├── dependencies.py
│   │       ├── middleware.py
│   │       └── v1/
│   │           └── routes/
│   │               ├── health.py
│   │               ├── auth.py
│   │               ├── users.py
│   │               └── projects.py
│   │
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_health.py
│       ├── test_auth.py
│       └── test_projects.py
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── postcss.config.js
    ├── nginx.conf
    ├── index.html
    ├── Dockerfile
    └── src/
        ├── index.css
        ├── main.tsx
        ├── app/
        │   ├── providers.tsx
        │   └── router.tsx
        ├── features/
        │   ├── auth/
        │   │   ├── api/authApi.ts
        │   │   ├── components/
        │   │   │   ├── LoginForm.tsx
        │   │   │   └── RegisterForm.tsx
        │   │   ├── hooks/
        │   │   │   ├── useLogin.ts
        │   │   │   └── useRegister.ts
        │   │   └── store/authStore.ts
        │   └── projects/
        │       ├── api/projectsApi.ts
        │       ├── components/
        │       │   ├── ProjectCard.tsx
        │       │   ├── ProjectForm.tsx
        │       │   └── ProjectList.tsx
        │       └── hooks/
        │           ├── useCreateProject.ts
        │           └── useProjects.ts
        ├── pages/
        │   ├── LoginPage.tsx
        │   ├── RegisterPage.tsx
        │   ├── DashboardPage.tsx
        │   ├── NewProjectPage.tsx
        │   └── ProjectDetailPage.tsx
        └── shared/
            ├── components/
            │   ├── Layout.tsx
            │   ├── ProtectedRoute.tsx
            │   └── ui/
            │       ├── Badge.tsx
            │       ├── Button.tsx
            │       ├── Input.tsx
            │       └── Spinner.tsx
            ├── lib/
            │   ├── axios.ts
            │   └── utils.ts
            └── types/
                └── index.ts
```

---

## 2. Commands to Run the Project

### Option A — Docker Compose (recommended, all services)

```bash
# 1. Clone / navigate to project root
cd "ForgeAI – Enterprise Multi-Agent Software Engineering Platform"

# 2. Create environment file
cp .env.example .env
# Edit .env and set a real SECRET_KEY:
#   python -c "import secrets; print(secrets.token_hex(32))"

# 3. Start all services (postgres → backend → frontend)
docker compose up --build

# Services available at:
#   API:      http://localhost:8000
#   Docs:     http://localhost:8000/api/docs
#   Frontend: http://localhost:5173
#   DB:       localhost:5432
```

### Option B — Local Development (no Docker)

#### Backend

```bash
cd backend

# Create and activate virtualenv
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"          # or: pip install .

# Set up environment
cp .env.example .env
# Edit .env: set DATABASE_URL to your local postgres instance and SECRET_KEY

# Run migrations (requires running PostgreSQL)
alembic upgrade head

# Start the API (with hot-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend

```bash
cd frontend
npm install
npm run dev
# Available at: http://localhost:5173
```

### Generate the first Alembic migration

```bash
cd backend
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

---

## 3. Environment Variables

### Backend (`backend/.env`)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://forgeai:forgeai@localhost:5432/forgeai` | Async PostgreSQL DSN |
| `SECRET_KEY` | *(no default in prod)* | 64-char hex — **must be set in production** |
| `ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token TTL |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `DEBUG` | `false` | Enables SQLAlchemy query echo |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array of allowed origins |

### Root `.env` (used by Docker Compose)

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `dev-insecure-secret-key-…` | Passed into the backend container |
| `ENVIRONMENT` | `development` | App environment |
| `LOG_LEVEL` | `INFO` | Log level |

### Test Database

The test suite expects a database named `forgeai_test`. The `scripts/init-test-db.sql` file
creates it automatically when the Docker container starts. For local runs:

```bash
createdb forgeai_test
# Or set TEST_DATABASE_URL in your shell:
export TEST_DATABASE_URL=postgresql+asyncpg://forgeai:forgeai@localhost:5432/forgeai_test
```

---

## 4. Verification Checklist

Run these steps in order to confirm the full stack is working.

### ✅ Database & Migrations

```bash
# Confirm migrations applied cleanly
alembic current          # should show the latest revision hash
alembic check            # should output: No new upgrade operations detected.

# Confirm tables exist
psql -U forgeai -d forgeai -c "\dt"
# Expected tables: users, projects, agent_runs, agent_steps, artifacts, llm_calls
```

### ✅ Health Endpoints

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","service":"ForgeAI","version":"0.1.0"}

curl http://localhost:8000/api/v1/health/ready
# {"status":"ready","database":"connected"}
```

### ✅ Authentication Flow

```bash
# Register
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@forge.ai","password":"Dev12345","full_name":"Dev User"}' | jq .

# Login — capture access_token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@forge.ai","password":"Dev12345"}' | jq -r .access_token)

echo "Token: $TOKEN"

# Access protected route
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/users/me | jq .
```

### ✅ Project CRUD

```bash
# Create project
PROJECT_ID=$(curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Project",
    "requirements": "Build a REST API with CRUD operations for managing tasks."
  }' | jq -r .id)

echo "Project ID: $PROJECT_ID"

# List projects
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/projects | jq .

# Get by ID
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/projects/$PROJECT_ID" | jq .

# Update
curl -s -X PUT "http://localhost:8000/api/v1/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Project Name"}' | jq .name

# Delete
curl -s -X DELETE "http://localhost:8000/api/v1/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### ✅ Automated Test Suite

```bash
cd backend

# Ensure forgeai_test database exists (see above)
# Run all tests with coverage
pytest tests/ -v --tb=short --cov=app --cov-report=term-missing

# Expected output:
# tests/test_health.py::test_health_liveness         PASSED
# tests/test_health.py::test_health_readiness        PASSED
# tests/test_auth.py::test_register_creates_user     PASSED
# tests/test_auth.py::test_register_duplicate_…      PASSED
# tests/test_auth.py::test_register_weak_password_…  PASSED
# tests/test_auth.py::test_login_returns_tokens      PASSED
# tests/test_auth.py::test_login_wrong_password_…    PASSED
# tests/test_auth.py::test_login_unknown_email_…     PASSED
# tests/test_auth.py::test_get_me_authenticated      PASSED
# tests/test_auth.py::test_get_me_unauthenticated_…  PASSED
# tests/test_auth.py::test_refresh_token_works       PASSED
# tests/test_auth.py::test_invalid_token_returns_401 PASSED
# tests/test_projects.py::test_create_project        PASSED
# tests/test_projects.py::test_create_project_req…   PASSED
# (... all 17 tests pass)
```

### ✅ Frontend

```bash
# Typecheck (zero errors expected)
cd frontend && npm run typecheck

# Build succeeds
npm run build
# dist/ directory created with bundled assets

# Dev server runs
npm run dev
# Navigate to http://localhost:5173
# - / redirects to /dashboard
# - /dashboard redirects to /login (unauthenticated)
# - Register at /register, login at /login
# - Dashboard shows project list after login
# - Create project at /projects/new
# - Protected routes redirect unauthenticated users to /login
```

### ✅ Docker Compose

```bash
# All containers start healthy
docker compose up --build -d
docker compose ps
# forgeai_postgres   running (healthy)
# forgeai_backend    running (healthy)
# forgeai_frontend   running

# Migrations run automatically in backend startup command
docker compose logs backend | grep "Running upgrade"
# Running upgrade  -> <revision_hash>, initial schema

# Tear down cleanly
docker compose down -v   # -v removes postgres_data volume
```

---

## API Documentation

When `ENVIRONMENT=development`, Swagger UI is available at:

```
http://localhost:8000/api/docs
```

OpenAPI JSON at: `http://localhost:8000/api/openapi.json`
