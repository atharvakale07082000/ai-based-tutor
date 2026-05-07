# AI Tutor Platform

An intelligent, adaptive learning platform powered by a multi-agent AI system. The platform personalises every learner's journey — from curriculum planning and content delivery to doubt resolution and progress tracking — using a network of specialised LangGraph agents backed by Hugging Face sub-agents.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Agent System](#agent-system)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Evaluation System](#evaluation-system)
- [Testing](#testing)
- [Environment Variables](#environment-variables)
- [Contributing](#contributing)

---

## Overview

| Feature | Description |
|---|---|
| Adaptive curriculum | Planner agent selects topics based on learner Elo / Bloom's level |
| Multi-agent orchestration | LangGraph graph: planner → curriculum → quiz, fully autonomous |
| Real-time doubt resolution | SSE-streamed answers from a specialised doubt agent |
| Elo-based progress | Rating updates after every quiz; mastery threshold at 700 |
| Guardrails | Input/output filtering before every agent call |
| Observability | Langfuse tracing on every node and tool call |
| Eval storage | MongoDB stores per-run agent eval records |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                         │
│  Landing → Onboarding → Dashboard → LearnFeed → ModulePlayer   │
│          DoubtChat → Quiz → Progress → Admin                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS / Socket.IO
┌───────────────────────────▼─────────────────────────────────────┐
│                  FastAPI Backend (Python)                        │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────┐  │
│  │  /auth   │  │ /session  │  │  /quiz   │  │   /doubts    │  │
│  │ /profile │  │ /progress │  │  /evals  │  │   /admin     │  │
│  └──────────┘  └───────────┘  └──────────┘  └──────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              LangGraph Orchestrator                     │   │
│  │                                                         │   │
│  │   ┌──────────┐   ┌────────────┐   ┌──────────────┐    │   │
│  │   │ Planner  │──▶│ Curriculum │──▶│    Planner   │    │   │
│  │   │  Agent   │   │   Agent    │   │   (re-eval)  │    │   │
│  │   └──────────┘   └────────────┘   └──────┬───────┘    │   │
│  │                                          │             │   │
│  │                                    ┌─────▼──────┐      │   │
│  │                                    │ Quiz Agent │      │   │
│  │                                    └────────────┘      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  Doubt     │  │  Progress    │  │   HF Sub-Agents        │  │
│  │  Agent     │  │  Agent       │  │  (tool registry)       │  │
│  └────────────┘  └──────────────┘  └────────────────────────┘  │
│                                                                 │
│  SQLite (users/sessions)  MongoDB (evals)  Redis (Celery/cache) │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent System

### Orchestration Graph

The LangGraph graph runs autonomously (no human-in-loop):

```
START → planner_node → curriculum_node → planner_node → quiz_node → END
```

The planner decides which topic to teach next based on the learner's current Elo rating. After curriculum delivery, it re-evaluates and routes to quiz generation. All transitions are deterministic — the graph completes in a single run.

### Agent Roles

| Agent | Responsibility |
|---|---|
| **Planner Agent** | Meta-agent — selects the next topic, routes to curriculum or quiz, makes the autonomous learning decisions |
| **Curriculum Agent** | Generates structured learning content for a given topic and difficulty |
| **Quiz Agent** | Produces Bloom's-taxonomy-aligned MCQs; calibrates difficulty to learner Elo |
| **Progress Agent** | Updates Elo ratings after quiz completion; maps Elo to Bloom's level |
| **Doubt Agent** | Resolves learner questions via SSE-streamed, context-aware answers |

### Hugging Face Sub-Agents (Tool Registry)

Agents delegate specialised tasks to HF-hosted sub-agents via `call_tool()` in `app/agents/tools.py`:

| Tool | Model / Purpose |
|---|---|
| `topic_classifier` | Classifies submitted text into a topic category |
| `sentiment` | Sentiment analysis on learner responses |
| `difficulty_scorer` | Scores content difficulty (0–1 float) |
| `quiz_generator` | Generates MCQ options and explanations |
| `embeddings` | Produces sentence embeddings for semantic search |
| `speech_to_text` | Transcribes audio doubt submissions |
| `image_captioner` | Describes uploaded diagram images for doubt context |
| `doubt_solver` | Streams a GPT-style answer to a learner's question |

### Guardrails

Every agent input/output passes through `app/guardrails.py`, which:
- Blocks prompt injection and jailbreak attempts
- Enforces topic relevance (off-topic queries are rejected before LLM call)
- Sanitises personal data from outputs

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

---

## Tech Stack

### Backend

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115 + Uvicorn |
| AI Orchestration | LangGraph (StateGraph) |
| LLM Agents | LangChain + Hugging Face Hub |
| Database (relational) | SQLite via SQLAlchemy async + aiosqlite |
| Database (evals) | MongoDB via Motor (async) |
| Cache / Queue | Redis + Celery |
| Real-time | Socket.IO (python-socketio) |
| Observability | Langfuse (tracing) |
| Auth | JWT (python-jose) + bcrypt |
| Prompts | YAML files, LRU-cached loader |
| Runtime | Python 3.13 |

### Frontend

| Layer | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| State management | Zustand |
| Server state | TanStack Query (React Query) |
| Animations | Framer Motion |
| Charts | Recharts |
| Real-time | Socket.io-client |
| Styling | Tailwind CSS |

---

## Project Structure

```
ai-tutor/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── curriculum_agent.py   # content delivery agent
│   │   │   ├── quiz_agent.py         # MCQ generation agent
│   │   │   ├── progress_agent.py     # Elo update agent
│   │   │   ├── doubt_agent.py        # SSE doubt resolver
│   │   │   ├── planner_agent.py      # meta-agent / orchestrator
│   │   │   └── tools.py              # HF sub-agent tool registry
│   │   ├── evals/
│   │   │   └── mongo.py              # Motor async eval storage
│   │   ├── graph/
│   │   │   └── orchestrator.py       # LangGraph StateGraph definition
│   │   ├── hf/
│   │   │   └── doubt_solver.py       # SSE streaming wrapper
│   │   ├── prompts/                  # YAML prompt templates (LRU cached)
│   │   ├── routers/                  # FastAPI route handlers
│   │   │   ├── auth.py
│   │   │   ├── sessions.py
│   │   │   ├── quiz.py
│   │   │   ├── doubts.py
│   │   │   ├── evals.py
│   │   │   └── progress.py
│   │   ├── config.py                 # Pydantic Settings
│   │   ├── database.py               # SQLAlchemy async engine
│   │   ├── guardrails.py             # Input/output safety filters
│   │   └── main.py                   # FastAPI app factory
│   ├── tests/
│   │   ├── conftest.py               # shared fixtures
│   │   ├── test_agents.py            # 72 unit tests
│   │   ├── test_integration.py       # 38 integration tests + eval report
│   │   └── test_e2e.py               # 38 E2E API tests
│   ├── .env.sample                   # environment variable template
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Landing.tsx
│   │   │   ├── Onboarding.tsx
│   │   │   ├── Dashboard.tsx
│   │   │   ├── LearnFeed.tsx
│   │   │   ├── ModulePlayer.tsx
│   │   │   ├── DoubtChat.tsx
│   │   │   ├── Quiz.tsx
│   │   │   ├── Progress.tsx
│   │   │   └── Admin.tsx
│   │   ├── components/
│   │   ├── store/                    # Zustand stores
│   │   ├── hooks/                    # TanStack Query hooks
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
├── .gitignore
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.13+
- Node.js 18+
- Redis (local or Docker)
- MongoDB (local or Atlas)
- A Hugging Face API token (`hf_...`)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# or with uv:
# uv sync

# Configure environment
cp .env.sample .env
# Edit .env and fill in HF_TOKEN, MONGO_URL, SECRET_KEY, etc.

# Run database migrations
python -m alembic upgrade head
# or for first run:
# python -c "from app.database import create_all_tables; import asyncio; asyncio.run(create_all_tables())"

# Start the server
uvicorn app.main:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend

npm install
npm run dev          # starts Vite dev server on http://localhost:5173
```

### Docker (optional)

```bash
# Start Redis and MongoDB via Docker
docker run -d -p 6379:6379 redis:7-alpine
docker run -d -p 27017:27017 mongo:7

# Then follow the backend/frontend setup steps above
```

---

## API Reference

All routes are prefixed with `/api/v1`. Interactive docs available at `http://localhost:8000/docs`.

### Authentication

| Method | Route | Description |
|---|---|---|
| `POST` | `/auth/register` | Register a new learner account |
| `POST` | `/auth/login` | Obtain JWT access + refresh tokens |
| `POST` | `/auth/refresh` | Rotate refresh token |

### Learner Profile

| Method | Route | Description |
|---|---|---|
| `POST` | `/learner-profile` | Create profile (topics, level) |
| `GET` | `/learner-profile` | Get current learner profile |

### Learning Sessions

| Method | Route | Description |
|---|---|---|
| `POST` | `/sessions` | Start a new learning session (triggers LangGraph run) |
| `GET` | `/sessions` | List all sessions for the authenticated user |
| `GET` | `/sessions/{session_id}` | Get session detail |

### Quiz

| Method | Route | Description |
|---|---|---|
| `POST` | `/quiz/generate` | Generate a quiz for a topic (async, via Celery) |
| `POST` | `/quiz/{quiz_id}/submit` | Submit answers; returns score and Elo delta |
| `GET` | `/quiz/{quiz_id}` | Get quiz questions |

### Doubts

| Method | Route | Description |
|---|---|---|
| `POST` | `/doubts/stream` | Submit a doubt; returns SSE stream (`text/event-stream`) |

SSE format:
```
data: {"token": "Python list comprehensions"}\n\n
data: {"token": " let you build..."}\n\n
data: [DONE]\n\n
```

### Progress

| Method | Route | Description |
|---|---|---|
| `GET` | `/progress` | Get Elo history and Bloom's level for the learner |

### Evaluations

| Method | Route | Description |
|---|---|---|
| `GET` | `/evals` | List agent eval records (filterable by agent/score) |
| `GET` | `/evals/summary` | Aggregated pass-rate and average score per eval type |

---

## Evaluation System

Every agent run writes an eval record to MongoDB:

```json
{
  "session_id": "...",
  "agent": "quiz_agent",
  "eval_type": "quiz_format",
  "score": 1.0,
  "passed": true,
  "details": { "num_options": 4, "has_explanation": true },
  "timestamp": "2026-05-07T10:00:00Z"
}
```

### Eval Types

| Eval Type | Agent | Checks |
|---|---|---|
| `curriculum_ordering` | curriculum_agent | Topics ordered by difficulty |
| `quiz_format` | quiz_agent | 4 options, explanation present, correct answer valid |
| `planner_decision` | planner_agent | Routing decision matches Elo threshold logic |
| `doubt_relevance` | doubt_agent | Answer relevance score ≥ 0.6 |
| `guardrail_triggered` | all | Guardrail fires on injection/off-topic inputs |

### Latest Eval Report

```
OVERALL: 25 eval records | 24 passed | avg score 0.913 | 96% pass rate

curriculum_ordering : 4/4  passed  (100%)
guardrail_triggered : 2/2  passed  (100%)
planner_decision    : 9/9  passed  (100%)
quiz_format         : 7/7  passed  (100%)
doubt_relevance     : 2/3  passed  ( 67%)  ← DA-04 intentionally tests off-topic rejection
```

---

## Testing

```bash
cd backend

# All 148 tests
pytest

# By suite
pytest tests/test_agents.py        # 72 unit tests
pytest tests/test_integration.py   # 38 integration tests (prints eval report)
pytest tests/test_e2e.py           # 38 E2E API tests

# With coverage
pytest --cov=app --cov-report=term-missing
```

### Test Coverage Summary

| Suite | Count | What it covers |
|---|---|---|
| Unit (`test_agents.py`) | 72 | Each agent function in isolation with mocked tools |
| Integration (`test_integration.py`) | 38 | Full agent runs, multi-agent workflows, eval record creation |
| E2E (`test_e2e.py`) | 38 | All HTTP endpoints — auth, sessions, quiz, doubts, evals, progress |

---

## Environment Variables

Copy `backend/.env.sample` to `backend/.env` and fill in the values:

```ini
# Database
DATABASE_URL=sqlite+aiosqlite:///./ai_tutor.db
DATABASE_SYNC_URL=sqlite:///./ai_tutor.db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=<256-bit random string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# Hugging Face
HF_TOKEN=hf_<your_token>

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# App
APP_ENV=development

# Langfuse tracing (leave empty to disable)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# MongoDB (eval storage)
MONGO_URL=mongodb://localhost:27017
MONGO_DATABASE=ai_tutor_evals
MONGO_COLLECTION_EVALS=agent_evals
```

> **Security**: Never commit your `.env` file. It is listed in `.gitignore` by the backend-specific ignore rules.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes, add tests
4. Run the full test suite: `pytest` (all 148 tests must pass)
5. Open a pull request

---

*Built with FastAPI, LangGraph, and React.*
