# ForgeAI — Software Architecture Document (SAD)

**Version:** 1.0  
**Status:** FROZEN — Implementation Reference  
**Author:** Staff Engineer  
**Date:** 2026-07-08

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Folder Structure](#2-folder-structure)
3. [Database Schema](#3-database-schema)
4. [Clean Architecture Layers](#4-clean-architecture-layers)
5. [Agent Workflow](#5-agent-workflow)
6. [API Endpoint Design](#6-api-endpoint-design)
7. [Data Flow Diagram](#7-data-flow-diagram)
8. [Class & Module Responsibilities](#8-class--module-responsibilities)
9. [Development Roadmap](#9-development-roadmap)

---

## 1. System Overview

ForgeAI is an enterprise-grade, multi-agent software engineering platform. Users describe a software project in natural language; ForgeAI routes that description through a coordinated pipeline of specialized AI agents that produce a complete, production-ready codebase as output.

### Core User Journey

```
User submits requirements (text)
        │
        ▼
Agent pipeline activates (LangGraph)
        │
        ├─► Requirements Analysis
        ├─► Architecture Design
        ├─► Code Generation
        ├─► Test Generation
        ├─► Code Review (with optional refinement loop)
        └─► Documentation + Packaging
        │
        ▼
User downloads generated project (zip) or browses artifacts in-app
```

### Key Design Principles

- **Clean Architecture** — dependency rule strictly enforced inward (domain has no deps)
- **Agent-first** — LangGraph orchestrates all AI work; no ad-hoc LLM calls in services
- **Audit by default** — every LLM call, token count, and cost is logged
- **Streaming-first** — UI receives real-time events via Server-Sent Events (SSE)
- **Multi-model ready** — LiteLLM abstracts provider; swap GPT-4 / Claude / Gemini via config

---

## 2. Folder Structure

### 2.1 Backend

```
backend/
├── app/
│   │
│   ├── api/                            # Layer 4: HTTP boundary
│   │   ├── v1/
│   │   │   ├── routes/
│   │   │   │   ├── auth.py             # /auth endpoints
│   │   │   │   ├── projects.py         # /projects CRUD + trigger
│   │   │   │   ├── runs.py             # /runs + SSE stream
│   │   │   │   ├── steps.py            # /steps detail
│   │   │   │   ├── artifacts.py        # /artifacts + download
│   │   │   │   ├── users.py            # /users profile
│   │   │   │   └── admin.py            # /admin (superuser only)
│   │   │   └── __init__.py
│   │   ├── dependencies.py             # FastAPI DI: db session, current user, etc.
│   │   └── middleware.py               # CORS, request ID, logging
│   │
│   ├── core/                           # Cross-cutting concerns
│   │   ├── config.py                   # Settings via pydantic-settings
│   │   ├── security.py                 # JWT encode/decode, password hashing
│   │   ├── exceptions.py               # Domain exception hierarchy
│   │   ├── logging.py                  # Structured JSON logger (structlog)
│   │   └── constants.py                # Enums, magic strings
│   │
│   ├── domain/                         # Layer 1: Pure business rules, zero deps
│   │   ├── entities/
│   │   │   ├── user.py                 # User entity (dataclass)
│   │   │   ├── project.py              # Project entity
│   │   │   ├── agent_run.py            # AgentRun entity
│   │   │   ├── agent_step.py           # AgentStep entity
│   │   │   └── artifact.py             # Artifact entity
│   │   ├── value_objects/
│   │   │   ├── project_status.py       # Enum: pending|running|completed|failed
│   │   │   ├── run_status.py           # Enum: queued|running|completed|failed|cancelled
│   │   │   ├── agent_type.py           # Enum: all agent node names
│   │   │   └── artifact_type.py        # Enum: source_code|test|config|doc|archive
│   │   └── events/
│   │       ├── project_events.py       # ProjectCreated, ProjectCompleted, etc.
│   │       └── run_events.py           # RunStarted, StepCompleted, RunFailed, etc.
│   │
│   ├── application/                    # Layer 2: Use cases, ports
│   │   ├── interfaces/                 # Abstract repository ports (depend on domain only)
│   │   │   ├── user_repository.py
│   │   │   ├── project_repository.py
│   │   │   ├── run_repository.py
│   │   │   └── artifact_repository.py
│   │   ├── services/                   # Orchestrate domain entities + repos
│   │   │   ├── auth_service.py         # Register, login, token refresh
│   │   │   ├── project_service.py      # Create, update, delete, trigger run
│   │   │   ├── run_service.py          # Get run, cancel run, stream events
│   │   │   └── artifact_service.py     # List, fetch, zip artifacts
│   │   └── dto/                        # Internal data transfer objects
│   │       ├── auth_dto.py
│   │       ├── project_dto.py
│   │       └── run_dto.py
│   │
│   ├── infrastructure/                 # Layer 3: Framework & external adapters
│   │   ├── database/
│   │   │   ├── base.py                 # DeclarativeBase, TimestampMixin
│   │   │   ├── session.py              # Async engine, get_db dependency
│   │   │   └── models/                 # SQLAlchemy ORM table definitions
│   │   │       ├── user.py
│   │   │       ├── project.py
│   │   │       ├── agent_run.py
│   │   │       ├── agent_step.py
│   │   │       ├── artifact.py
│   │   │       └── llm_call.py
│   │   ├── repositories/               # Concrete repo implementations (SQLAlchemy)
│   │   │   ├── user_repository.py
│   │   │   ├── project_repository.py
│   │   │   ├── run_repository.py
│   │   │   └── artifact_repository.py
│   │   ├── llm/
│   │   │   ├── litellm_client.py       # Thin async wrapper around LiteLLM
│   │   │   └── prompt_templates/       # Jinja2 / f-string prompt builders
│   │   │       ├── requirements_analyst.py
│   │   │       ├── architect.py
│   │   │       ├── code_generator.py
│   │   │       ├── test_writer.py
│   │   │       ├── reviewer.py
│   │   │       └── doc_writer.py
│   │   └── storage/
│   │       └── artifact_store.py       # Read/write artifact content (local FS or S3)
│   │
│   ├── agents/                         # LangGraph node implementations
│   │   ├── base_agent.py               # BaseAgent ABC with shared plumbing
│   │   ├── requirements_analyst.py     # Node: parse & structure requirements
│   │   ├── architect.py                # Node: design architecture
│   │   ├── code_generator.py           # Node: generate source files
│   │   ├── test_writer.py              # Node: generate tests
│   │   ├── reviewer.py                 # Node: review code, emit pass/fail
│   │   ├── refiner.py                  # Node: apply reviewer feedback
│   │   └── doc_writer.py              # Node: README + inline docs + packager
│   │
│   ├── workflows/                      # LangGraph graph definitions
│   │   ├── forge_workflow.py           # StateGraph: wires all agent nodes + edges
│   │   ├── states.py                   # ForgeState TypedDict (shared graph state)
│   │   └── checkpointer.py             # PostgreSQL-backed LangGraph checkpointer
│   │
│   └── schemas/                        # Pydantic v2 request/response schemas
│       ├── auth.py
│       ├── project.py
│       ├── run.py
│       ├── step.py
│       ├── artifact.py
│       └── common.py                   # Pagination, error response, etc.
│
├── alembic/
│   ├── versions/                       # Auto-generated migration files
│   └── env.py
│
├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   ├── application/
│   │   └── agents/
│   ├── integration/
│   │   ├── api/
│   │   └── workflows/
│   └── conftest.py                     # Fixtures: test DB, mock LLM, test client
│
├── pyproject.toml
├── alembic.ini
├── Dockerfile
├── .env.example
└── README.md
```

### 2.2 Frontend

```
frontend/
├── src/
│   ├── app/
│   │   ├── App.tsx                     # Root component
│   │   ├── router.tsx                  # React Router v6 route tree
│   │   └── providers.tsx               # QueryClient, Router, global stores
│   │
│   ├── features/                       # Vertical slices by domain feature
│   │   ├── auth/
│   │   │   ├── components/
│   │   │   │   ├── LoginForm.tsx
│   │   │   │   └── RegisterForm.tsx
│   │   │   ├── hooks/
│   │   │   │   └── useLogin.ts
│   │   │   ├── store/
│   │   │   │   └── authStore.ts        # Zustand: token, user, hydration
│   │   │   └── api/
│   │   │       └── authApi.ts
│   │   │
│   │   ├── projects/
│   │   │   ├── components/
│   │   │   │   ├── ProjectList.tsx
│   │   │   │   ├── ProjectCard.tsx
│   │   │   │   └── ProjectForm.tsx     # Create / edit project + requirements editor
│   │   │   ├── hooks/
│   │   │   │   ├── useProjects.ts
│   │   │   │   └── useCreateProject.ts
│   │   │   └── api/
│   │   │       └── projectsApi.ts
│   │   │
│   │   ├── runs/
│   │   │   ├── components/
│   │   │   │   ├── AgentTimeline.tsx   # Visual step-by-step pipeline view
│   │   │   │   ├── StepCard.tsx        # Single agent step: status, tokens, duration
│   │   │   │   ├── LogStream.tsx       # SSE-fed live log panel
│   │   │   │   └── RunControls.tsx     # Cancel button, re-run button
│   │   │   ├── hooks/
│   │   │   │   ├── useRun.ts
│   │   │   │   └── useRunStream.ts     # Manages EventSource lifecycle
│   │   │   └── api/
│   │   │       └── runsApi.ts
│   │   │
│   │   └── artifacts/
│   │       ├── components/
│   │       │   ├── FileTree.tsx        # Generated file tree explorer
│   │       │   ├── CodeViewer.tsx      # Syntax-highlighted file content
│   │       │   └── DownloadPanel.tsx   # Download individual files or zip
│   │       ├── hooks/
│   │       │   └── useArtifacts.ts
│   │       └── api/
│   │           └── artifactsApi.ts
│   │
│   ├── shared/
│   │   ├── components/
│   │   │   ├── ui/                     # Primitives: Button, Badge, Spinner, Modal
│   │   │   ├── Layout.tsx              # App shell: sidebar + topbar
│   │   │   ├── ProtectedRoute.tsx
│   │   │   └── ErrorBoundary.tsx
│   │   ├── hooks/
│   │   │   └── useToast.ts
│   │   ├── lib/
│   │   │   ├── axios.ts                # Axios instance: base URL, auth interceptors
│   │   │   └── utils.ts
│   │   └── types/
│   │       └── index.ts                # Shared TypeScript interfaces (Project, Run, etc.)
│   │
│   └── pages/
│       ├── DashboardPage.tsx           # Project list + usage summary
│       ├── ProjectDetailPage.tsx       # Project info + run history
│       ├── RunDetailPage.tsx           # Live pipeline view + artifacts
│       ├── NewProjectPage.tsx          # Requirements input
│       └── LoginPage.tsx
│
├── public/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── Dockerfile
└── package.json
```

### 2.3 Infrastructure / Deployment

```
forgeai/                                # Monorepo root
├── backend/
├── frontend/
├── docker-compose.yml                  # Dev: api, frontend, postgres, redis
├── docker-compose.prod.yml             # Prod overrides
├── .env.example
└── README.md
```

---

## 3. Database Schema

All tables use `UUID` primary keys. `created_at` / `updated_at` are managed by a mixin. Async SQLAlchemy 2.0 with `asyncpg` driver.

```sql
-- ─────────────────────────────────────────────
-- users
-- ─────────────────────────────────────────────
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(255),
    is_active       BOOLEAN DEFAULT TRUE,
    is_superuser    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- projects
-- ─────────────────────────────────────────────
CREATE TABLE projects (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    requirements TEXT NOT NULL,          -- raw natural-language spec
    tech_stack   JSONB DEFAULT '{}',     -- user-specified overrides (optional)
    status       VARCHAR(50)  NOT NULL DEFAULT 'pending',
                 -- pending | running | completed | failed
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_projects_owner ON projects(owner_id);
CREATE INDEX idx_projects_status ON projects(status);

-- ─────────────────────────────────────────────
-- agent_runs  (one pipeline execution per row)
-- ─────────────────────────────────────────────
CREATE TABLE agent_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status        VARCHAR(50)  NOT NULL DEFAULT 'queued',
                  -- queued | running | completed | failed | cancelled
    trigger       VARCHAR(50)  NOT NULL DEFAULT 'manual',
                  -- manual | retry | scheduled
    graph_state   JSONB DEFAULT '{}',   -- LangGraph checkpoint snapshot
    error_message TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_runs_project ON agent_runs(project_id);
CREATE INDEX idx_runs_status  ON agent_runs(status);

-- ─────────────────────────────────────────────
-- agent_steps  (one row per agent node execution)
-- ─────────────────────────────────────────────
CREATE TABLE agent_steps (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    agent_type   VARCHAR(100) NOT NULL,
                 -- requirements_analyst | architect | code_generator |
                 --   test_writer | reviewer | refiner | doc_writer
    sequence     INTEGER NOT NULL,        -- execution order (0-indexed)
    status       VARCHAR(50)  NOT NULL DEFAULT 'pending',
                 -- pending | running | completed | failed | skipped
    input        JSONB DEFAULT '{}',      -- snapshot of state passed in
    output       JSONB DEFAULT '{}',      -- structured output produced
    tokens_used  INTEGER DEFAULT 0,
    cost_usd     NUMERIC(12, 8) DEFAULT 0,
    duration_ms  INTEGER,
    error_message TEXT,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_steps_run      ON agent_steps(run_id);
CREATE INDEX idx_steps_sequence ON agent_steps(run_id, sequence);

-- ─────────────────────────────────────────────
-- artifacts  (generated files)
-- ─────────────────────────────────────────────
CREATE TABLE artifacts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id        UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    step_id       UUID REFERENCES agent_steps(id) ON DELETE SET NULL,
    artifact_type VARCHAR(100) NOT NULL,
                  -- source_code | test | config | documentation | archive
    file_path     VARCHAR(1024) NOT NULL,  -- relative path within generated project
    language      VARCHAR(50),             -- python | typescript | sql | markdown | …
    size_bytes    INTEGER DEFAULT 0,
    checksum      VARCHAR(64),             -- SHA-256 of content
    storage_key   VARCHAR(1024),           -- key in object store (if not inline)
    content       TEXT,                    -- inline for small files
    metadata      JSONB DEFAULT '{}',      -- arbitrary extra info
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_artifacts_project ON artifacts(project_id);
CREATE INDEX idx_artifacts_run     ON artifacts(run_id);

-- ─────────────────────────────────────────────
-- llm_calls  (full audit log, one row per API call)
-- ─────────────────────────────────────────────
CREATE TABLE llm_calls (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    step_id           UUID REFERENCES agent_steps(id) ON DELETE CASCADE,
    model             VARCHAR(255) NOT NULL,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens      INTEGER DEFAULT 0,
    cost_usd          NUMERIC(12, 8) DEFAULT 0,
    latency_ms        INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_calls_step ON llm_calls(step_id);
```

### 3.1 Entity Relationship Summary

```
users ──< projects ──< agent_runs ──< agent_steps ──< llm_calls
                   │              │
                   └──< artifacts ┘
```

---

## 4. Clean Architecture Layers

The dependency rule: inner layers never import from outer layers.

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4 — Interface Adapters (API)                         │
│  FastAPI routes, Pydantic schemas, middleware, DI wiring    │
│  ↓ calls into ↓                                             │
├─────────────────────────────────────────────────────────────┤
│  Layer 3 — Infrastructure                                   │
│  SQLAlchemy models, concrete repos, LiteLLM client,         │
│  artifact storage, LangGraph checkpointer                   │
│  ↓ implements interfaces from ↓                             │
├─────────────────────────────────────────────────────────────┤
│  Layer 2 — Application (Use Cases)                          │
│  Services, repository interfaces (ports), DTOs              │
│  ↓ uses entities from ↓                                     │
├─────────────────────────────────────────────────────────────┤
│  Layer 1 — Domain                                           │
│  Entities, Value Objects, Domain Events                     │
│  No external imports whatsoever                             │
└─────────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

| Layer | Contains | Allowed deps |
|---|---|---|
| Domain | Entities, VOs, events | stdlib only |
| Application | Services, interfaces, DTOs | Domain |
| Infrastructure | ORM models, repos, LLM client | Domain + Application interfaces |
| API | Routes, schemas, middleware | Application services (via DI) |
| Agents / Workflows | LangGraph nodes and graph | Application services, Infrastructure LLM client |

> **Agents** sit between Application and Infrastructure. They are orchestrated by the workflow engine and call application services to persist state, but directly call the LLM client for generation work.

---

## 5. Agent Workflow

### 5.1 ForgeState (Shared Graph State)

```python
class ForgeState(TypedDict):
    # Identity
    run_id: str
    project_id: str

    # Raw input
    requirements: str
    tech_stack_overrides: dict

    # Agent outputs (accumulated as pipeline progresses)
    analysis: RequirementsAnalysis | None       # from RequirementsAnalystAgent
    architecture: ArchitectureSpec | None       # from ArchitectAgent
    generated_files: list[GeneratedFile]        # from CodeGeneratorAgent
    test_files: list[GeneratedFile]             # from TestWriterAgent
    review_result: ReviewResult | None          # from ReviewerAgent
    refinement_notes: str | None                # from RefinerAgent
    docs: list[GeneratedFile]                   # from DocWriterAgent

    # Control flow
    review_iterations: int                      # current retry count
    max_review_iterations: int                  # default 2
    errors: list[str]                           # accumulated non-fatal errors

    # Telemetry
    total_tokens: int
    total_cost_usd: float
```

### 5.2 Agent Node Definitions

**RequirementsAnalystAgent**
- Input: `requirements`, `tech_stack_overrides`
- Prompt: Extracts structured specification — features list, constraints, recommended stack, scale requirements, open questions
- Output: `RequirementsAnalysis(features, constraints, tech_stack, clarifications)`

**ArchitectAgent**
- Input: `analysis`
- Prompt: Produces full architecture blueprint — folder tree, DB schema, API contract, component diagram (text), data flow, tech choices with rationale
- Output: `ArchitectureSpec(folder_tree, db_schema, api_contracts, design_decisions)`

**CodeGeneratorAgent**
- Input: `analysis`, `architecture`
- Iterates file-by-file through the architecture's folder tree
- Each LLM call produces one complete file with imports, logic, and doc strings
- Output: `generated_files: list[GeneratedFile(path, content, language)]`
- Side effect: persists each file as an `Artifact` record immediately (streaming artifact creation)

**TestWriterAgent**
- Input: `analysis`, `architecture`, `generated_files`
- Generates unit tests for each service/module and integration tests for API routes
- Output: `test_files: list[GeneratedFile]`

**ReviewerAgent**
- Input: `generated_files`, `test_files`, `architecture`
- Holistic review across: correctness, security (OWASP Top 10), architecture compliance, test coverage, code style
- Output: `ReviewResult(passed: bool, score: int, issues: list[Issue], feedback: str)`

**RefinerAgent** (conditional node)
- Activated when: `review_result.passed == False` and `review_iterations < max_review_iterations`
- Input: `generated_files`, `review_result`
- Applies targeted patches to flagged files based on reviewer feedback
- Output: updated `generated_files`, incremented `review_iterations`

**DocWriterAgent**
- Input: full state
- Generates: `README.md`, `CONTRIBUTING.md`, inline docstrings pass, `openapi.yaml`, `docker-compose.yml`
- Output: `docs: list[GeneratedFile]`
- Also packages everything into a zip artifact

### 5.3 Graph Topology

```
START
  │
  ▼
[requirements_analyst]
  │
  ▼
[architect]
  │
  ▼
[code_generator]
  │
  ▼
[test_writer]
  │
  ▼
[reviewer]
  │
  ├──(passed OR iterations >= max)──► [doc_writer] ──► END
  │
  └──(failed AND iterations < max)──► [refiner] ──► [code_generator]
                                           ▲              │
                                           └──────────────┘
                                              (loop back)
```

### 5.4 LangGraph Implementation Notes

- Graph compiled with `PostgresSaver` checkpointer for durability and resume-on-failure
- Each node wraps execution in a try/except; errors are appended to `state.errors` and the node marks the step as failed without crashing the graph (graceful degradation)
- `interrupt_before` can be set on any node for human-in-the-loop workflows (future milestone)
- Streaming: LangGraph's `.astream_events()` feeds the SSE endpoint in real time

---

## 6. API Endpoint Design

All routes are under `/api/v1`. Authentication via `Authorization: Bearer <JWT>`.

### 6.1 Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Returns `access_token` + `refresh_token` |
| POST | `/auth/refresh` | Exchange refresh token for new access token |
| POST | `/auth/logout` | Invalidate refresh token |

### 6.2 Users

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users/me` | User | Get own profile |
| PUT | `/users/me` | User | Update profile |
| GET | `/users/{id}` | Admin | Get any user |
| GET | `/users` | Admin | List users (paginated) |

### 6.3 Projects

| Method | Path | Description |
|---|---|---|
| GET | `/projects` | List caller's projects (paginated, filterable by status) |
| POST | `/projects` | Create project (body: name, description, requirements, tech_stack) |
| GET | `/projects/{id}` | Get project detail + latest run summary |
| PUT | `/projects/{id}` | Update project metadata |
| DELETE | `/projects/{id}` | Soft-delete project |
| POST | `/projects/{id}/run` | Trigger a new agent pipeline run |

### 6.4 Runs

| Method | Path | Description |
|---|---|---|
| GET | `/runs` | List runs (filter by project_id, status) |
| GET | `/runs/{id}` | Get run detail including all steps |
| GET | `/runs/{id}/stream` | **SSE** — real-time event stream for this run |
| POST | `/runs/{id}/cancel` | Cancel a queued or running pipeline |

### 6.5 Steps

| Method | Path | Description |
|---|---|---|
| GET | `/steps/{id}` | Step detail: input, output, token usage, cost |

### 6.6 Artifacts

| Method | Path | Description |
|---|---|---|
| GET | `/artifacts` | List artifacts (filter by project_id, run_id, type) |
| GET | `/artifacts/{id}` | Single artifact metadata |
| GET | `/artifacts/{id}/content` | Raw file content (text/plain) |
| GET | `/artifacts/{id}/download` | Binary download with correct Content-Type |
| GET | `/runs/{id}/archive` | Download all artifacts for a run as `.zip` |

### 6.7 Admin

| Method | Path | Description |
|---|---|---|
| GET | `/admin/users` | All users |
| GET | `/admin/runs` | All runs system-wide |
| GET | `/admin/metrics` | Aggregate: total runs, tokens, cost, active users |

### 6.8 SSE Event Schema

Events emitted on `GET /runs/{id}/stream`:

```json
{ "event": "run.started",      "data": { "run_id": "..." } }
{ "event": "step.started",     "data": { "step_id": "...", "agent_type": "architect", "sequence": 1 } }
{ "event": "step.log",         "data": { "step_id": "...", "message": "Generating file src/main.py..." } }
{ "event": "step.completed",   "data": { "step_id": "...", "tokens_used": 1240, "cost_usd": 0.0062 } }
{ "event": "artifact.created", "data": { "artifact_id": "...", "file_path": "src/main.py" } }
{ "event": "step.failed",      "data": { "step_id": "...", "error": "..." } }
{ "event": "run.completed",    "data": { "run_id": "...", "total_cost_usd": 0.18 } }
{ "event": "run.failed",       "data": { "run_id": "...", "error": "..." } }
```

---

## 7. Data Flow Diagram

```
╔══════════════════════════════════════════════════════════════════╗
║  Browser (React)                                                 ║
║                                                                  ║
║  [NewProjectPage]                                                ║
║     └─ POST /api/v1/projects ──────────────────────────────────╗ ║
║                                                                 ║ ║
║  POST /api/v1/projects/{id}/run ───────────────────────────────╫─╫─────────────────────┐
║                                                                 ║ ║                     │
║  [RunDetailPage]                                                ║ ║                     │
║     └─ GET /runs/{id}/stream (EventSource) ◄────────SSE────────╫─╫──────┐              │
║     └─ GET /artifacts (polling / push)     ◄────────────────────╝ ║      │              │
╚═════════════════════════════════════════════════════════════════════╝      │              │
                                                                             │              │
╔════════════════════════════════╗                                            │              │
║  FastAPI (API Layer)           ║ ◄──────────────────────────────────────────┘              │
║                                ║                                                           │
║  auth_middleware               ║  validates JWT                                            │
║  projects.router               ║  calls ProjectService                                     │
║  runs.router + SSE generator   ║  pipes LangGraph astream_events() → EventSource          │
╚══════════════╦═════════════════╝                                                           │
               │                                                                             │
╔══════════════▼═════════════════╗                                                           │
║  Application Services          ║                                                           │
║                                ║                                                           │
║  ProjectService.trigger_run()  ║  creates AgentRun record                                  │
║                                ║  invokes ForgeWorkflow.arun(state)                        │
║  RunService.stream_events()    ║  wraps LangGraph event iterator                           │
║  ArtifactService               ║  zip assembly, retrieval                                  │
╚══════════════╦═════════════════╝                                                           │
               │                                                                             │
╔══════════════▼═════════════════════════════════════════════════╗                          │
║  ForgeWorkflow (LangGraph StateGraph)                           ║ ◄────────────────────────┘
║                                                                 ║
║  ┌─────────────────────────────────────────────────────────┐   ║
║  │  ForgeState (shared across all nodes)                   │   ║
║  └─────────────────────────────────────────────────────────┘   ║
║                                                                 ║
║  [requirements_analyst] ──► [architect] ──► [code_generator]   ║
║        │                                         │              ║
║        │                                   [test_writer]        ║
║        │                                         │              ║
║        │                                   [reviewer]           ║
║        │                                    │       │           ║
║        │                               pass │  fail │           ║
║        │                                    │       ▼           ║
║        │                                    │  [refiner]──┐     ║
║        │                                    │             │     ║
║        │                                    ▼        ─────┘     ║
║        │                              [doc_writer] ──► END       ║
║        └─ Each node calls RunRepository.update_step() ──────────╫──┐
╚═════════════════════════════════════════════════════════════════╝  │
               │                                                      │
╔══════════════▼═══════════════════════════════════════════════════╗ │
║  Infrastructure Layer                                             ║ │
║                                                                   ║ │
║  LiteLLMClient ──► OpenAI / Anthropic / Gemini APIs              ║ │
║  PostgreSQL ◄──── SQLAlchemy async sessions                       ║ ◄┘
║  ArtifactStore ──► local FS (dev) / S3-compatible (prod)         ║
║  LangGraph PostgresSaver ──► persists graph checkpoints           ║
╚═══════════════════════════════════════════════════════════════════╝
```

---

## 8. Class & Module Responsibilities

### 8.1 Domain Entities

| Class | Responsibility |
|---|---|
| `User` | Identity entity. Owns projects. Has `is_active`, `is_superuser` flags. |
| `Project` | Core aggregate. Holds raw requirements and status. Emits `ProjectCreated`, `ProjectStatusChanged`. |
| `AgentRun` | One pipeline execution. Tracks status, timing, LangGraph checkpoint. |
| `AgentStep` | Single agent node execution within a run. Owns input/output snapshots and cost data. |
| `Artifact` | A generated file. Knows its path, language, content or storage key. |

### 8.2 Application Services

| Class | Key Methods | Responsibility |
|---|---|---|
| `AuthService` | `register`, `login`, `refresh_token` | Password hashing, JWT issuance, refresh token rotation |
| `ProjectService` | `create`, `update`, `delete`, `trigger_run` | Project CRUD; creates AgentRun and launches workflow |
| `RunService` | `get_run`, `cancel_run`, `stream_events` | Run retrieval; cancellation (sets status + signals graph); wraps SSE |
| `ArtifactService` | `list_artifacts`, `get_content`, `build_archive` | Artifact retrieval; in-memory zip assembly for downloads |

### 8.3 Repository Interfaces (Ports)

```python
class ProjectRepository(ABC):
    async def get_by_id(self, id: UUID) -> Project | None: ...
    async def list_by_owner(self, owner_id: UUID, ...) -> list[Project]: ...
    async def create(self, project: Project) -> Project: ...
    async def update(self, project: Project) -> Project: ...
    async def delete(self, id: UUID) -> None: ...

class RunRepository(ABC):
    async def get_by_id(self, id: UUID) -> AgentRun | None: ...
    async def list_by_project(self, project_id: UUID) -> list[AgentRun]: ...
    async def create(self, run: AgentRun) -> AgentRun: ...
    async def update_status(self, id: UUID, status: RunStatus) -> None: ...
    async def upsert_step(self, step: AgentStep) -> AgentStep: ...
```

### 8.4 Agent Nodes

| Class | Input keys consumed | Output keys produced |
|---|---|---|
| `RequirementsAnalystAgent` | `requirements`, `tech_stack_overrides` | `analysis` |
| `ArchitectAgent` | `analysis` | `architecture` |
| `CodeGeneratorAgent` | `analysis`, `architecture` | `generated_files` |
| `TestWriterAgent` | `analysis`, `architecture`, `generated_files` | `test_files` |
| `ReviewerAgent` | `generated_files`, `test_files`, `architecture` | `review_result` |
| `RefinerAgent` | `generated_files`, `review_result` | `generated_files` (updated), `review_iterations` |
| `DocWriterAgent` | full state | `docs`, final artifact zip |

Each agent inherits `BaseAgent`:

```python
class BaseAgent(ABC):
    def __init__(self, llm_client: LiteLLMClient, run_repo: RunRepository): ...

    async def __call__(self, state: ForgeState) -> dict:
        step = await self._start_step(state)
        try:
            result = await self.execute(state)
            await self._complete_step(step, result)
            return result
        except Exception as e:
            await self._fail_step(step, e)
            raise

    @abstractmethod
    async def execute(self, state: ForgeState) -> dict: ...
```

### 8.5 ForgeWorkflow

```python
class ForgeWorkflow:
    """Compiles and runs the LangGraph StateGraph for a single project run."""

    def compile(self) -> CompiledGraph:
        graph = StateGraph(ForgeState)
        graph.add_node("requirements_analyst", RequirementsAnalystAgent(...))
        graph.add_node("architect",            ArchitectAgent(...))
        graph.add_node("code_generator",       CodeGeneratorAgent(...))
        graph.add_node("test_writer",          TestWriterAgent(...))
        graph.add_node("reviewer",             ReviewerAgent(...))
        graph.add_node("refiner",              RefinerAgent(...))
        graph.add_node("doc_writer",           DocWriterAgent(...))

        graph.set_entry_point("requirements_analyst")
        graph.add_edge("requirements_analyst", "architect")
        graph.add_edge("architect",            "code_generator")
        graph.add_edge("code_generator",       "test_writer")
        graph.add_edge("test_writer",          "reviewer")
        graph.add_conditional_edges(
            "reviewer",
            should_refine,       # returns "refiner" or "doc_writer"
            {"refiner": "refiner", "doc_writer": "doc_writer"}
        )
        graph.add_edge("refiner",    "code_generator")
        graph.add_edge("doc_writer", END)

        return graph.compile(checkpointer=PostgresSaver(...))
```

### 8.6 LiteLLMClient

```python
class LiteLLMClient:
    """Thin async wrapper. Handles model routing, retries, cost tracking."""

    async def complete(
        self,
        model: str,
        messages: list[dict],
        response_format: type[BaseModel] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse: ...

    async def stream(self, ...) -> AsyncIterator[str]: ...
```

### 8.7 Pydantic Schemas (API layer)

Key request/response schemas:

```python
# Request
class CreateProjectRequest(BaseModel):
    name: str
    description: str | None
    requirements: str
    tech_stack: dict = {}

# Response
class ProjectResponse(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    latest_run: RunSummary | None

class RunDetailResponse(BaseModel):
    id: UUID
    status: str
    steps: list[StepResponse]
    total_tokens: int
    total_cost_usd: float
    started_at: datetime | None
    completed_at: datetime | None

class StepResponse(BaseModel):
    id: UUID
    agent_type: str
    sequence: int
    status: str
    tokens_used: int
    cost_usd: float
    duration_ms: int | None
```

---

## 9. Development Roadmap

### Milestone 0 — Repo Bootstrap (Day 1–2)

- Initialize monorepo: `backend/`, `frontend/`, `docker-compose.yml`
- Configure `pyproject.toml`, `alembic.ini`, `vite.config.ts`
- Set up pre-commit hooks: `ruff`, `mypy`, `prettier`, `eslint`
- Create `.env.example` with all required secrets
- Docker Compose: `postgres:16`, `redis:7`, `api` (hot-reload), `frontend` (Vite dev)
- CI pipeline skeleton: lint → typecheck → test (GitHub Actions)

**Exit criteria:** `docker compose up` brings all services online.

---

### Milestone 1 — Core Infrastructure (Week 1)

- SQLAlchemy async setup: `session.py`, `base.py`, `TimestampMixin`
- All 6 ORM models implemented
- Alembic initial migration (`0001_initial.py`)
- Domain entities and value objects (pure Python)
- Repository interfaces + concrete SQLAlchemy implementations
- Dependency injection wiring in `api/dependencies.py`
- Structured logging (`structlog`) and settings (`pydantic-settings`)

**Exit criteria:** Alembic `upgrade head` succeeds; repos are unit-testable with a real test DB.

---

### Milestone 2 — Authentication (Week 1–2)

- `AuthService`: register, login, refresh, logout
- Password hashing with `bcrypt`
- JWT (`python-jose`): short-lived access token (15 min) + long-lived refresh token (7 days)
- Refresh token stored in DB or Redis (invalidatable)
- API routes: `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`
- Protected route middleware (`get_current_user` dependency)
- Frontend: `authStore` (Zustand), `LoginPage`, `ProtectedRoute`, Axios interceptors

**Exit criteria:** Full register → login → access protected route flow works end-to-end.

---

### Milestone 3 — Project CRUD (Week 2)

- `ProjectService`: create, list, get, update, delete
- API routes: `GET/POST /projects`, `GET/PUT/DELETE /projects/{id}`
- Pydantic schemas for project request/response with validation
- Frontend: `DashboardPage` (project list), `NewProjectPage` (requirements form), `ProjectDetailPage` (skeleton)
- Pagination helper (cursor-based)

**Exit criteria:** Users can create and manage projects via the UI.

---

### Milestone 4 — Agent Framework (Week 3)

- `BaseAgent` ABC with step lifecycle management
- `LiteLLMClient` with async completion and streaming
- All prompt templates (Jinja2 or f-strings)
- `ForgeState` TypedDict
- `ForgeWorkflow` StateGraph compiled (with mock agent nodes that return hardcoded data)
- `RunService.trigger_run()` creates DB record and starts workflow
- `RunRepository.upsert_step()` for step-level persistence
- Unit tests for each agent node in isolation (mock LLM)

**Exit criteria:** A pipeline run can be triggered, progresses through all nodes (mocked), and every step is persisted in DB.

---

### Milestone 5 — Real Agents (Week 4–6)

Implement each agent's actual LLM logic in order:

1. `RequirementsAnalystAgent` — structured output via Pydantic response format
2. `ArchitectAgent` — generates `ArchitectureSpec` with folder tree + DB schema
3. `CodeGeneratorAgent` — iterates files, persists artifacts progressively
4. `TestWriterAgent` — generates test files
5. `ReviewerAgent` — holistic review, structured `ReviewResult`
6. `RefinerAgent` + loop logic (`should_refine` conditional)
7. `DocWriterAgent` — README, zip packaging

Each agent: write prompt → test with real LLM → evaluate output quality → refine prompt → integration test.

**Exit criteria:** End-to-end run produces a downloadable, coherent codebase for a simple "to-do API" input.

---

### Milestone 6 — Streaming & Real-time UI (Week 6–7)

- SSE endpoint: `GET /runs/{id}/stream` using `fastapi.responses.StreamingResponse`
- `ForgeWorkflow` emits named events via LangGraph's `astream_events()`
- Frontend: `useRunStream` hook (`EventSource`)
- `AgentTimeline` component: live step cards with status badges and token counts
- `LogStream` component: scrolling log panel fed by SSE
- `ArtifactCreated` events trigger incremental `FileTree` updates

**Exit criteria:** Users watch the pipeline execute in real-time with no manual refresh.

---

### Milestone 7 — Artifacts & Download (Week 7–8)

- `ArtifactService.build_archive()`: in-memory zip of all run artifacts
- API: `GET /artifacts/{id}/content`, `GET /runs/{id}/archive`
- Frontend: `FileTree` explorer, `CodeViewer` (syntax highlighting via `highlight.js`), `DownloadPanel`
- Admin endpoints: user list, run list, aggregate metrics

**Exit criteria:** Users can browse and download all generated files.

---

### Milestone 8 — Hardening & Quality (Week 9–10)

- Integration test suite: auth flow, project CRUD, full pipeline run (against real DB, mock LLM)
- Error handling audit: every external call has a timeout + retry + structured error response
- Rate limiting (`slowapi`) on auth and run-trigger endpoints
- Input validation: requirements length caps, sanitization
- Security review: SQL injection (ORM mitigates), IDOR checks, JWT secret rotation
- Performance: add DB indexes, profile slow queries with `EXPLAIN ANALYZE`
- Cost guardrails: per-run token budget cap, user-level monthly cost cap

**Exit criteria:** Test suite passes at >80% coverage; no P0 security findings.

---

### Milestone 9 — Production Readiness (Week 11–12)

- `docker-compose.prod.yml`: Gunicorn + Uvicorn workers, Nginx reverse proxy
- Health check endpoints: `GET /health`, `GET /ready`
- Environment-based config validation at startup (fail fast)
- Alembic migration CI gate (fails if unapplied migrations exist in prod)
- Monitoring hooks: structured logs to stdout (ship to Datadog / Loki)
- `README.md`: local dev setup, env vars, architecture overview, contribution guide
- Optional: LangGraph `interrupt_before` nodes for human-in-the-loop review UI

**Exit criteria:** Platform deploys cleanly to a single VM via Docker Compose; health checks green; a non-trivial project generates runnable output.

---

## Appendix A — Technology Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Async runtime | `asyncio` + `asyncpg` | Non-blocking I/O critical for streaming + concurrent LLM calls |
| LLM abstraction | LiteLLM | Single interface to swap GPT-4 / Claude / Gemini without code changes |
| Agent orchestration | LangGraph | Native support for cyclic graphs (review loop), checkpointing, streaming |
| DB | PostgreSQL | JSONB for flexible agent state; `asyncpg` for high throughput |
| Migrations | Alembic | De-facto standard with SQLAlchemy; auto-generates migrations |
| Frontend state | Zustand | Minimal boilerplate, excellent TypeScript support |
| Real-time | SSE over WebSocket | SSE is simpler for server-push; no need for bidirectional in MVP |
| Auth | JWT (HS256) + refresh tokens | Stateless access tokens; refresh tokens enable revocation |

## Appendix B — Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/forgeai

# Security
SECRET_KEY=<64-char random hex>
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# LLM
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_MODEL=gpt-4o
REVIEW_MODEL=gpt-4o
MAX_TOKENS_PER_RUN=200000
MAX_COST_USD_PER_RUN=2.00

# Storage
ARTIFACT_STORAGE_BACKEND=local       # local | s3
ARTIFACT_LOCAL_PATH=/data/artifacts
# AWS_S3_BUCKET=forgeai-artifacts     # if backend=s3

# App
ENVIRONMENT=development              # development | production
LOG_LEVEL=INFO
CORS_ORIGINS=["http://localhost:5173"]
```
