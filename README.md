# Atelier — AI Tutor Platform

An adaptive learning platform powered by a multi-agent AI system. A **Strands
orchestrator** LLM-routes each chat turn to specialist agents — doubt, quiz,
curriculum, progress, assistant — each with on-demand **skills** and streaming
**live reasoning** to the frontend via Server-Sent Events.

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
| Strands multi-agent | A pure orchestrator LLM-routes each turn to one or more specialist agents |
| Agents-as-orchestrator | Structured-output routing → ordered specialist run → single streamed voice |
| Progressive-disclosure skills | Specialists load `SKILL.md` instructions on demand via a `load_skill` tool |
| Reasoning stream | The agent's `<reasoning>` note is streamed as "thinking" — never the raw tool workflow |
| Persistent thread memory | A chat thread keeps durable, cross-specialist memory (Strands sessions) |
| Adaptive curriculum | Elo proficiency drives Bloom-calibrated content and quiz difficulty |
| Elo-based progress | Rating updates after every quiz; mastery threshold at 700 |
| Guardrails | Input/output safety filtering on every agent call |
| Online evals | Random-sampled DeepEval metrics judged by NVIDIA NIM, stored in MongoDB |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                          │
│  Landing → Onboarding → Dashboard → Courses → ModulePlayer       │
│  Ask Atelier (chat) → Quiz → Progress → Interview → Job Tracker  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS / Socket.IO / SSE
┌───────────────────────────▼─────────────────────────────────────┐
│                    FastAPI Backend (Python)                      │
│                                                                  │
│  /api/v1  ── auth, learner, quiz, doubts, progress, courses,     │
│              jobs, evals, feed, leaderboard, profile, session    │
│  /api/v1/chat  ── POST (SSE, Strands agent stream)               │
│                                                                  │
│  ┌───────────────────────── Strands agents ────────────────────┐ │
│  │                                                             │ │
│  │  handler.run_chat                                           │ │
│  │     └─ orchestrator.route  ──LLM (structured output)──▶     │ │
│  │            RoutePlan(agents=[…], reason)                    │ │
│  │     └─ build_specialist(key, session_id)  (per request)     │ │
│  │            └─ stream_async → stream_adapter.translate_event │ │
│  │                 → reasoning / token / action / done         │ │
│  │                                                             │ │
│  │  pipelines/ (course_gen · quiz_gen · interview_review ·     │ │
│  │              jd_analyze)  → emit `step` events              │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌───────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │  NVIDIA NIM   │  │ tool registry│  │  HF Inference         │  │
│  │ (OpenAIModel) │  │ (@tool adapt)│  │  (Together / NVIDIA)  │  │
│  └───────────────┘  └──────────────┘  └───────────────────────┘  │
│                                                                  │
│  SQLite (users / sessions)      MongoDB (evals + progress)       │
└─────────────────────────────────────────────────────────────────┘
```

Everything agent-related lives in one package, `backend/app/agents/`, built on
the **Strands Agents SDK**. All models come from `agents/model.py::get_nim_model`
(NVIDIA NIM via the OpenAI-compatible endpoint); nothing else constructs a Strands
`Agent`. (The former LangGraph v1 graph, the `agents_v2` ReAct package, and the
plan-execute workflow framework have all been removed.)

---

## Agent System

### Orchestrator (routing)

Every chat turn goes through `orchestrator.route`. A tool-less Strands `Agent`
makes **one** LLM call and returns a structured `RoutePlan` — an *ordered* list of
specialist keys plus a one-line reason. This is the single always-on routing
decision; the handler then streams the chosen specialist(s) directly, so the
learner hears one voice. A deterministic keyword heuristic is kept **only** as a
fallback when the routing call errors or returns nothing valid.

> Routing model: `qwen/qwen3-next-80b-a3b-instruct` on NVIDIA NIM. Do **not** swap
> the orchestrator to `mistralai/mistral-nemotron` — it can't reliably invoke the
> structured-output tool, which breaks multi-intent routing.

### Specialist Agents

Each specialist is a Strands `Agent` composed of a role system-prompt
(`prompts/react_agent.yaml` → `roles:`), its skills catalog block, the `load_skill`
tool, a curated set of domain tools, the shared NIM specialist model, and a
`GuardrailHook`. Specialists are built **per request** — Strands agents accumulate
conversation state on the instance, so only the *model* is cached, never the agent.

| Agent | Role | Skills | Domain tools |
|---|---|---|---|
| **doubt** | Conceptual questions / doubts | `explanation`, `web-research` | `check_guardrail`, `get_proficiency`, `generate_explanation`, `web_search` |
| **quiz** | Adaptive, Bloom-calibrated quizzes | `quiz-authoring` | `get_proficiency`, `score_difficulty`, `generate_quiz`, `save_quiz` |
| **curriculum** | Personalized learning paths | `curriculum-design`, `web-research` | `classify_topic`, `get_topic_graph`, `get_proficiency`, `web_search` |
| **progress** | Elo update + mood, progress reports | `progress-tracking` | `get_proficiency`, `calculate_elo`, `analyze_sentiment`, `save_progress` |
| **assistant** | General-purpose fallback | `explanation`, `web-research` | all 14 tools |

### Skills (progressive disclosure)

Skills follow the Agent Skills spec. Each lives in
`app/agents/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`)
and a Markdown instruction body. Only the name + description are injected into a
specialist's system prompt (an `<available_skills>` block); the full body is loaded
on demand when the agent calls the **`load_skill`** tool.

> A `SKILL.md` runs only if a specialist lists it in `SPECIALISTS[...].skills`.
> `interview-coaching` and `job-analysis` currently exist on disk but are
> **orphaned** — the live interview runtime is the YAML prompts
> (`prompts/course_planner.yaml` + `prompts/interview_scorer.yaml`), not the SKILL.md.

### Reasoning stream (not a tool workflow)

The mechanical agent trace — tool names, args, results, latencies — is **never**
shown to learners. Specialists are instructed (`react_agent.yaml`
`reasoning_protocol`) to open each reply with a short first-person
`<reasoning>…</reasoning>` note. `stream_adapter.translate_event` splits that out
of the token stream into `reasoning` events (the answer is everything else), and
only side-effect tools (`save_quiz`, `save_progress`) still emit an `action` card.
Generation pipelines emit `step` events written as first-person reasoning. The
frontend renders both via `components/agents/ReasoningStream.tsx`.

### Persistent thread memory

When a request carries a chat-thread id (`X-Session-Id`), the specialist is wired
to that thread's persisted conversation via a Strands `FileSessionManager`, and all
specialists in the thread share one `agent_id` — so memory carries **across**
specialists (e.g. "quiz me on that" after a doubt turn). A `SlidingWindow`
(`CHAT_MEMORY_WINDOW`, default 40 messages) bounds context. Without a thread id the
agent is stateless (the generation pipelines that reuse the builder stay memoryless).

### Elo & Bloom mapping

```
Elo   0–300   → Bloom 1: Remember
Elo 300–450   → Bloom 2: Understand
Elo 450–600   → Bloom 3: Apply
Elo 600–720   → Bloom 4: Analyze
Elo 720–870   → Bloom 5: Evaluate
Elo 870–1000  → Bloom 6: Create

Default proficiency: 500 Elo
Mastery threshold:   700 Elo
Update formula:      new_elo = clamp(current + 32 × (score − expected), 0, 1000)
                     (expected defaults to 0.5)
```

### Concurrency & throttles

| Component | Limit | Notes |
|---|---|---|
| Thread pool | 64 threads | Set at lifespan startup |
| `HF_SEMAPHORE` | Global cap | Bounds concurrent outbound LLM calls |
| NIM RPM bucket | `NIM_RPM_LIMIT` (40) | Sliding-window token bucket for the NVIDIA free tier |
| Model cache | `@lru_cache` | The NIM *model* is cached; *agents* are built per request |

---

## Tech Stack

### Backend

| Layer | Technology |
|---|---|
| Framework | FastAPI + Uvicorn |
| Agents | **Strands Agents SDK** (orchestrator + specialists + skills) |
| Agent model | NVIDIA NIM via `OpenAIModel` (`qwen/qwen3-next-80b-a3b-instruct`) |
| Heavy generation | Hugging Face Inference (Together / NVIDIA fallback) |
| Database | SQLite via SQLAlchemy async + aiosqlite (users / sessions) |
| Eval + progress store | MongoDB via Motor (async) |
| Real-time | Socket.IO + SSE (`text/event-stream`) |
| Evals | DeepEval, NVIDIA-judged, online-sampled |
| Logging | structlog (JSON) |
| Auth | JWT (python-jose) + bcrypt |
| Tooling | `uv` (locked via `pyproject.toml` / `uv.lock`), `ruff` |
| Runtime | Python 3.13 |

### Frontend

| Layer | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| State | Zustand + TanStack Query |
| Real-time | socket.io-client + native `EventSource` (SSE) |
| Styling | Tailwind CSS + `@tailwindcss/typography` |
| Motion | framer-motion |
| Markdown / charts / code | react-markdown + remark-gfm, recharts, Monaco editor |
| Design system | "Atelier, re-rated" — Space Grotesk, terracotta + amber-signal, ink-blue dark |

---

## Project Structure

```
ai-tutor/
├── backend/
│   ├── app/
│   │   ├── agents/                 # single Strands agents package
│   │   │   ├── handler.py          # AgentHandler singleton — run_chat entry point
│   │   │   ├── orchestrator.py     # LLM router (RoutePlan) + heuristic fallback
│   │   │   ├── specialists.py      # SPECIALISTS registry + build_specialist
│   │   │   ├── model.py            # get_nim_model (NVIDIA NIM, semaphore + RPM bucket)
│   │   │   ├── tools.py            # @tool adapters over the master tool registry
│   │   │   ├── skills.py           # SKILL.md loader + load_skill tool
│   │   │   ├── skills/*/SKILL.md   # progressive-disclosure skill instructions
│   │   │   ├── hooks.py            # GuardrailHook
│   │   │   ├── stream_adapter.py   # Strands events → SSE wire contract
│   │   │   ├── steps.py            # STEP_PLANS for pipeline `step` events
│   │   │   ├── session.py          # quiz/interview session state + Bloom mapping
│   │   │   ├── pipelines/          # course_gen · quiz_gen · interview_review · jd_analyze
│   │   │   ├── course_planner.py   # interview_scorer.py · skill_gap.py · progress.py
│   │   ├── routers/                # chat.py (SSE) + auth, quiz, doubts, progress, courses, jobs, evals, …
│   │   ├── tools/                  # master tool registry + implementations (hf/db/logic)
│   │   ├── prompts/*.yaml          # externalized LLM prompts (SaaS house style)
│   │   ├── evals/                  # DeepEval metrics + MongoDB storage
│   │   ├── guardrails.py           # input/output safety
│   │   ├── config.py
│   │   └── main.py                 # FastAPI app + Socket.IO → socket_app
│   ├── tests/                      # unit / integration / e2e / evals
│   ├── pyproject.toml              # deps (uv) — requirements.txt is a generated export
│   └── render.yaml
├── frontend/
│   ├── src/
│   │   ├── pages/                  # AtelierV2Page (chat), Quiz, Progress, CoursePlanner, Interview, JobTracker, …
│   │   ├── components/
│   │   │   ├── agents/             # ReasoningStream, AgentStatusBar
│   │   │   ├── layout/             # Sidebar, TopBar, CommandPalette
│   │   │   └── ui/                 # Button, Badge, MarkdownMessage, …
│   │   ├── stores/                 # Zustand stores
│   │   ├── hooks/
│   │   └── lib/api.ts
│   └── package.json
├── e2e/                            # Playwright harnesses (smoke.py, full.py, api_coverage.py)
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.13+
- Node.js 18+
- MongoDB (local or Atlas)
- An NVIDIA NIM API key (for the Strands agents)
- A Hugging Face API token (`hf_...`) for heavy generation

### Backend

Managed by [`uv`](https://docs.astral.sh/uv/) — do **not** use `pip`; deps are
locked in `uv.lock`.

```bash
cd backend

uv sync --all-groups                 # install (incl. dev tools)

cp .env.sample .env
# Fill in NVIDIA_API_KEY, HF_TOKEN, MONGO_URL, SECRET_KEY

uv run alembic upgrade head          # migrate SQLite

# Run the Socket.IO-wrapped ASGI app — NOT app.main:app (that drops Socket.IO)
uv run uvicorn app.main:socket_app --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

Default local login: `admin@test.com` / `admin@1234` (the `/login` page
auto-registers unknown accounts).

---

## API Reference

Interactive docs at `http://localhost:8000/docs`.

### Chat (SSE)

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/v1/chat` | Stream a Strands agent response |

Request body:
```json
{
  "message": "explain gradient descent",
  "context": { "current_topic": "optimization" },
  "history": [{ "role": "user", "content": "…" }]
}
```

Headers:

| Header | Purpose |
|---|---|
| `X-Session-Id` | Stable chat-thread id → enables persistent per-thread memory |
| `X-Correlation-Id` | Request correlation for structured logs |

SSE event stream (the wire contract the frontend consumes):
```
data: {"type": "routing", "agent": "doubt", "display_name": "Doubt Solver", "reason": "…"}
data: {"type": "step", ...}                       # live step timeline
data: {"type": "reasoning", "content": "Let me break this down…"}
data: {"type": "token", "content": "Gradient descent"}
data: {"type": "action", "kind": "quiz_generated", "payload": {...}}
data: {"type": "done", "steps": 2, "total_ms": 4210}
```

Additional event types: `error` (generic client-safe message; full detail stays in
server logs) and `guardrail` (input blocked before any LLM call).

### v1 REST routes (prefixed `/api/v1`)

| Group | Routes |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh` |
| Learner | `GET/POST /learner/*` |
| Curriculum / Courses | `GET/POST /curriculum/*`, `GET/POST /courses/*` |
| Quiz | `POST /quiz/generate`, `POST /quiz/{id}/submit`, `GET /quiz/{id}` |
| Doubts | `POST /doubts/*` (SSE) |
| Progress | `GET /progress`, session flows under `/session/*` |
| Jobs | `GET/POST /jobs/*` (skill-gap / JD analysis) |
| Content / Feed / Leaderboard / Profile | `/content/*`, `/feed/*`, `/leaderboard/*`, `/profile/*` |
| Evals (superuser) | `/evals/*` |
| Admin | `/admin/*` |

---

## Testing

```bash
cd backend

uv run pytest                                  # full suite
uv run pytest tests/test_strands_agents.py     # single file
uv run pytest --cov=app --cov-report=term-missing
```

### Test suites

| Suite | Collected | What it covers |
|---|---|---|
| `test_strands_agents.py` | 15 | Orchestrator routing, specialists, skills, tool adapters |
| `test_api.py` | 16 | Core API contract |
| `test_e2e.py` | 38 | Full HTTP flow — auth through quiz submission |
| `test_hf.py` | 32 | HF tool implementations |
| `test_evals.py` | 33 | DeepEval metrics + eval record creation |
| `test_session.py` | 11 | Quiz/interview session state machine |
| `test_steps.py` | 7 | `step` event timeline protocol |
| `test_code_runner.py` | 6 | Sandboxed code execution (Piston) |
| `test_jobs.py` | 5 | Job Tracker / skill-gap flows |
| **Total** | **~163** | collected across the suite |

---

## Environment Variables

Copy `backend/.env.sample` to `backend/.env`:

```ini
# App
APP_ENV=development
SECRET_KEY=<256-bit random string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# Databases
DATABASE_URL=sqlite+aiosqlite:///./ai_tutor.db
DATABASE_SYNC_URL=sqlite:///./ai_tutor.db
MONGO_URL=mongodb://localhost:27017
MONGO_DATABASE=ai_tutor

# NVIDIA NIM — Strands agents (orchestrator + specialists)
NVIDIA_API_KEY=<your_key>
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NIM_ORCHESTRATOR_MODEL=qwen/qwen3-next-80b-a3b-instruct
NIM_SPECIALIST_MODEL=qwen/qwen3-next-80b-a3b-instruct
NIM_RPM_LIMIT=40
AGENT_SESSIONS_DIR=            # empty → OS temp dir; point at a volume for durable memory
CHAT_MEMORY_WINDOW=40

# Hugging Face — heavy generation
HF_TOKEN=hf_<your_token>

# Evals (DeepEval, NVIDIA-judged)
EVAL_JUDGE_MODEL=qwen/qwen3-next-80b-a3b-instruct
EVALS_ONLINE_SAMPLING=true

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

- **Frontend** → Vercel. Set `VITE_API_BASE_URL` to the backend URL.
- **Backend** → Render via `render.yaml`. Set `NVIDIA_API_KEY`, `HF_TOKEN`,
  `MONGO_URL`, `SECRET_KEY`, `CORS_ORIGINS` (and, for durable thread memory,
  `AGENT_SESSIONS_DIR` on a persistent disk).

---

*Built with FastAPI, the Strands Agents SDK on NVIDIA NIM, and React.*
</content>
