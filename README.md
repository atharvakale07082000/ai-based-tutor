# Atelier — AI Tutor Platform

An adaptive learning platform powered by a multi-agent AI system. Specialised ReAct agents handle curriculum planning, quiz generation, progress tracking, and doubt resolution — each streaming live reasoning steps to the frontend via Server-Sent Events.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Agent System](#agent-system)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)

---

## Overview

| Feature | Description |
|---|---|
| Adaptive curriculum | Planner agent selects topics based on learner Elo / Bloom's level |
| ReAct agents (v2) | Keyword + LLM routing → specialist agent → tool calls → streamed answer |
| SSE streaming | Every thought, tool call, and token streamed in real time |
| Elo-based progress | Rating updates after every quiz; mastery threshold at 700 |
| 13-tool registry | HF, DB, and logic tools; each agent gets a curated whitelist |
| Concurrency | 64-thread pool + HF semaphore (40) supports 200 simultaneous users |
| Guardrails | Input/output safety filtering on every agent call |
| Observability | Langfuse tracing on every node and tool call |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                         │
│  Landing → Onboarding → Dashboard → Courses → ModulePlayer      │
│  DoubtChat → Quiz → Progress → Assistant → AtelierV2            │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS / Socket.IO / SSE
┌───────────────────────────▼─────────────────────────────────────┐
│                   FastAPI Backend (Python)                       │
│                                                                  │
│  /api/v1  ── auth, learner, quiz, doubts, progress, courses     │
│  /api/v2  ── POST /chat  (SSE, ReAct agent stream)              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  Agent v2 (ReAct)                       │    │
│  │                                                         │    │
│  │   AgentRouter ──keyword──▶ Specialist Agent             │    │
│  │        └────── LLM ──────▶ (fallback)                   │    │
│  │                                                         │    │
│  │   for step in range(max_steps=6):                       │    │
│  │     decide_step()  →  SSE: thought                      │    │
│  │     tool_registry.call()  →  SSE: tool_call/tool_result │    │
│  │     stream_final_answer()  →  SSE: token … done         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────────┐   │
│  │ LangGraph  │  │  Tool        │  │   HF Inference         │   │
│  │ (v1 graph) │  │  Registry    │  │   (Together API)       │   │
│  └────────────┘  └──────────────┘  └────────────────────────┘   │
│                                                                  │
│  SQLite (users/sessions)     MongoDB (evals + progress)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent System

### Agent v2 — ReAct Architecture

Each request to `POST /api/v2/chat` is routed to a specialist agent via a two-phase router:

1. **Keyword phase** — instant (`<1 ms`), matches trigger words to an agent
2. **LLM fallback** — Qwen2.5-7B via Together API (`~3 s`) when keywords are ambiguous

The agent then runs a ReAct loop (up to 6 steps), streaming every event:

```
routing → thought → tool_call → tool_result → ... → token(s) → done
```

### Specialist Agents

| Agent | Trigger keywords | Tool whitelist |
|---|---|---|
| **QuizAgent** | quiz, test, assess | `get_proficiency`, `score_difficulty`, `generate_quiz`, `save_quiz` |
| **CurriculumAgent** | roadmap, path, curriculum | `classify_topic`, `get_topic_graph`, `get_proficiency` |
| **ProgressAgent** | progress, elo, how am I doing | `get_proficiency`, `calculate_elo`, `analyze_sentiment`, `save_progress` |
| **DoubtAgent** | explain, how does, why | `check_guardrail`, `get_proficiency`, `generate_explanation` |
| **AssistantAgent** | (fallback) | all 13 tools |

### Tool Registry (13 tools)

| Category | Tools |
|---|---|
| HF (6) | `classify_topic`, `analyze_sentiment`, `score_difficulty`, `generate_quiz`, `get_embeddings`, `generate_explanation` |
| DB (5) | `get_proficiency`, `get_topic_graph`, `save_quiz`, `save_progress`, `get_due_topics` |
| Logic (2) | `calculate_elo`, `check_guardrail` |

### Elo & Bloom's Mapping

```
Elo 0–500    → Bloom Level 1: Remember
Elo 500–580  → Bloom Level 2: Understand
Elo 580–640  → Bloom Level 3: Apply
Elo 640–690  → Bloom Level 4: Analyse
Elo 690–730  → Bloom Level 5: Evaluate
Elo 730+     → Bloom Level 6: Create

Mastery threshold: 700 Elo
Update formula:    new_elo = current + 32 × (score − 0.5)
```

### Concurrency

| Component | Limit | Notes |
|---|---|---|
| Thread pool | 64 threads | Set at lifespan startup |
| HF semaphore | 40 concurrent LLM calls | Queues excess cleanly |
| FastAPI async | No limit | Pure asyncio |
| Together API | Plan rate limit | Primary real-world ceiling |

---

## Tech Stack

### Backend

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115 + Uvicorn |
| AI (v2) | ReAct agents, Together API (Qwen2.5-7B) |
| AI (v1) | LangGraph StateGraph + LangChain |
| Inference | Hugging Face Hub (HF tools) |
| Database | SQLite via SQLAlchemy async + aiosqlite |
| Eval storage | MongoDB via Motor (async) |
| Real-time | Socket.IO + SSE (`text/event-stream`) |
| Observability | Langfuse |
| Auth | JWT (python-jose) + bcrypt |
| Runtime | Python 3.13, deployed via Docker |

### Frontend

| Layer | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| State | Zustand + TanStack Query |
| Real-time | Socket.io-client + native `EventSource` (SSE) |
| Styling | CSS custom properties (design tokens) |

---

## Project Structure

```
ai-tutor/
├── backend/
│   ├── app/
│   │   ├── agents/          # v1 LangGraph agents
│   │   ├── agents_v2/       # v2 ReAct agents
│   │   │   ├── base.py      # BaseAgent, ReAct loop, HF semaphore
│   │   │   ├── router.py    # AgentRouter (keyword + LLM)
│   │   │   ├── quiz_agent.py
│   │   │   ├── curriculum_agent.py
│   │   │   ├── progress_agent.py
│   │   │   ├── doubt_agent.py
│   │   │   └── assistant_agent.py
│   │   ├── tools/           # Tool registry (13 tools)
│   │   │   ├── registry.py
│   │   │   ├── schemas.py
│   │   │   └── implementations/
│   │   │       ├── hf_tools.py
│   │   │       ├── db_tools.py
│   │   │       └── logic_tools.py
│   │   ├── routers/
│   │   │   ├── v2/chat.py   # SSE endpoint
│   │   │   ├── auth.py
│   │   │   ├── quiz.py
│   │   │   ├── doubts.py
│   │   │   ├── progress.py
│   │   │   └── courses.py
│   │   ├── evals/           # MongoDB eval storage
│   │   ├── guardrails.py
│   │   └── main.py
│   ├── tests/
│   │   ├── test_agents.py        # 47 unit tests
│   │   ├── test_api.py           # 8 API tests
│   │   ├── test_e2e.py           # 35 E2E tests
│   │   ├── test_hf.py            # 12 HF tool tests
│   │   ├── test_integration.py   # 38 integration tests
│   │   ├── test_v2_stress.py     # 12 stress tests (125 queries)
│   │   └── test_v2_concurrency.py  # 5 concurrency tests (200 users)
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── LandingPage.tsx
│   │   │   ├── OnboardingPage.tsx
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── AssistantPage.tsx
│   │   │   ├── AtelierV2Page.tsx   # v2 SSE chat interface
│   │   │   ├── DoubtChatPage.tsx
│   │   │   ├── QuizPage.tsx
│   │   │   ├── ProgressPage.tsx
│   │   │   ├── CoursePlannerPage.tsx
│   │   │   ├── CourseDetailPage.tsx
│   │   │   ├── ModulePlayerPage.tsx
│   │   │   ├── ModuleInterviewPage.tsx
│   │   │   └── FlashcardsPage.tsx
│   │   ├── components/
│   │   │   ├── agents/       # StreamTrace, ToolCallCard, AgentStatusBar
│   │   │   ├── layout/       # Sidebar, TopBar, CommandPalette
│   │   │   └── ui/           # Button, Badge, MarkdownMessage, …
│   │   ├── stores/           # Zustand stores
│   │   ├── hooks/
│   │   └── lib/api.ts
│   └── package.json
├── render.yaml               # Render deployment config
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.13+
- Node.js 18+
- MongoDB (local or Atlas)
- A Hugging Face API token (`hf_...`)
- A Together API key (for Qwen2.5-7B inference)

### Backend

```bash
cd backend

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
# or: uv sync

cp .env.sample .env
# Fill in HF_TOKEN, TOGETHER_API_KEY, MONGO_URL, SECRET_KEY

python -m alembic upgrade head

uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

### Docker (backend only)

```bash
cd backend
docker build -t ai-tutor-backend .
docker run -p 8000:8000 --env-file .env ai-tutor-backend
```

---

## API Reference

Docs available at `http://localhost:8000/docs`.

### v2 Chat (SSE)

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/v2/chat` | Stream a ReAct agent response |

Request body:
```json
{ "message": "explain gradient descent", "learner_id": "abc123" }
```

SSE event stream:
```
data: {"type": "routing", "agent": "doubt"}
data: {"type": "thought", "step": 1, "content": "I should explain..."}
data: {"type": "tool_call", "name": "generate_explanation", "args": {...}}
data: {"type": "tool_result", "name": "generate_explanation", "latency_ms": 312}
data: {"type": "token", "content": "Gradient descent"}
data: {"type": "done", "steps": 2, "total_ms": 4210}
```

### v1 Routes (prefixed `/api/v1`)

| Group | Routes |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh` |
| Learner | `GET/POST /learner-profile`, `POST /learner/onboard` |
| Quiz | `POST /quiz/generate`, `POST /quiz/{id}/submit`, `GET /quiz/{id}` |
| Doubts | `POST /doubts/stream` (SSE) |
| Progress | `GET /progress` |
| Courses | `GET/POST /courses`, `GET /courses/{id}` |
| Evals | `GET /evals`, `GET /evals/summary` |

---

## Testing

```bash
cd backend

# Full suite (190 tests)
pytest

# Individual suites
pytest tests/test_agents.py          # 47 unit tests
pytest tests/test_integration.py     # 38 integration tests
pytest tests/test_e2e.py             # 35 E2E tests
pytest tests/test_v2_stress.py       # stress: 125 queries across 5 agents
pytest tests/test_v2_concurrency.py  # concurrency: 200 simultaneous users

pytest --cov=app --cov-report=term-missing
```

### Test Summary

| Suite | Count | What it covers |
|---|---|---|
| `test_agents.py` | 47 | Agent functions in isolation, mocked tools |
| `test_api.py` | 8 | Core API contract tests |
| `test_e2e.py` | 35 | Full HTTP flow — auth through quiz submission |
| `test_hf.py` | 12 | HF tool implementations |
| `test_integration.py` | 38 | Multi-agent workflows, eval record creation |
| `test_v2_stress.py` | 12 | 125 queries, SSE event structure, routing accuracy |
| `test_v2_concurrency.py` | 5 | 200 concurrent SSE requests |
| **Total** | **190** | **190 / 190 passing** |

---

## Environment Variables

Copy `backend/.env.sample` to `backend/.env`:

```ini
# Database
DATABASE_URL=sqlite+aiosqlite:///./ai_tutor.db
DATABASE_SYNC_URL=sqlite:///./ai_tutor.db

# MongoDB (evals + progress)
MONGO_URL=mongodb://localhost:27017
MONGO_DATABASE=ai_tutor

# JWT
SECRET_KEY=<256-bit random string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# Inference
HF_TOKEN=hf_<your_token>
TOGETHER_API_KEY=<your_key>

# CORS
CORS_ORIGINS=http://localhost:5173

# Langfuse tracing (optional — leave empty to disable)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

> Never commit `.env`. It is listed in `.gitignore`.

---

## Deployment

The backend is configured for [Render](https://render.com) via `render.yaml` (Docker runtime). Set the following env vars in the Render dashboard: `MONGO_URL`, `HF_TOKEN`, `TOGETHER_API_KEY`, `SECRET_KEY`, `CORS_ORIGINS`.

The frontend can be deployed to any static host (Vercel, Netlify, Render static site). Set `VITE_API_BASE_URL` to your backend URL.

---

*Built with FastAPI, ReAct agents, and React.*
