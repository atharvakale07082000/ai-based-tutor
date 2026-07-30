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
| Resumable interviews | A reloaded tab rejoins a live module interview instead of losing it |
| Adaptive curriculum | Elo proficiency drives Bloom-calibrated content and quiz difficulty |
| Elo-based progress | Rating updates after every quiz; mastery threshold at 700 |
| Guardrails | Input/output safety filtering on every agent call |
| Online evals | Random-sampled DeepEval metrics judged by NVIDIA NIM, stored in MongoDB (**opt-in extra** — see [Evals](#evals)) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                          │
│  Landing → Onboarding → Dashboard → Courses → ModulePlayer       │
│  Ask Atelier (chat) → Quiz → Progress → Interview → Job Tracker  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS / SSE
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
│                     MongoDB (all persistence)                    │
└─────────────────────────────────────────────────────────────────┘
```

Everything agent-related lives in one package, `backend/app/agents/`, built on
the **Strands Agents SDK**. All models come from `agents/model.py::get_nim_model`
(NVIDIA NIM via the OpenAI-compatible endpoint); nothing else constructs a Strands
`Agent`. (The former LangGraph v1 graph, the `agents_v2` ReAct package, and the
plan-execute workflow framework have all been removed.)

> **One datastore.** MongoDB holds everything — users, sessions, quizzes,
> progress, interviews, evals. There is no SQL database: no SQLAlchemy, no
> SQLite, no Alembic, no migration step. Earlier revisions of this README
> described a SQLite/Alembic setup that never existed in the code.

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
| **assistant** | General-purpose fallback, chat mock interviews | `explanation`, `web-research`, `interview-coaching` | all 14 tools |

### Skills (progressive disclosure)

Skills follow the Agent Skills spec. Each lives in
`app/agents/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`)
and a Markdown instruction body. Only the name + description are injected into a
specialist's system prompt (an `<available_skills>` block); the full body is loaded
on demand when the agent calls the **`load_skill`** tool.

> A `SKILL.md` runs only if a specialist lists it in `SPECIALISTS[...].skills`.
> `interview-coaching` is live twice over — it backs the **assistant** specialist's
> chat mock interviews, and its body is the rubric loaded by the module interview
> agent. **`job-analysis` is the only orphaned skill** (present on disk, listed by
> no specialist).

### Reasoning stream (not a tool workflow)

The mechanical agent trace — tool names, args, results, latencies — is **never**
shown to learners. Specialists are instructed (`react_agent.yaml`
`reasoning_protocol`) to open each reply with a short first-person
`<reasoning>…</reasoning>` note. `stream_adapter.translate_event` splits that out
of the token stream into `reasoning` events (the answer is everything else), and
only side-effect tools (`save_quiz`, `save_progress`) still emit an `action` card.
Generation pipelines emit `step` events written as first-person reasoning. The
frontend renders both via `components/agents/ReasoningStream.tsx`.

Tool results are still captured for evaluation even though they never reach the
UI: `TraceState.grounding` accumulates them inside the adapter (bounded to 8
entries × 1500 chars) and `routers/chat.py` passes them as `retrieval_context`, so
DeepEval can attach its `FaithfulnessMetric` — when DeepEval is installed (see
[Evals](#evals)).

### Persistent thread memory

When a request carries a chat-thread id (`X-Session-Id`), the specialist is wired
to that thread's persisted conversation via a Strands `FileSessionManager`, and all
specialists in the thread share one `agent_id` — so memory carries **across**
specialists (e.g. "quiz me on that" after a doubt turn). A `SlidingWindow`
(`CHAT_MEMORY_WINDOW`, default 40 messages) bounds context. Without a thread id the
agent is stateless (the generation pipelines that reuse the builder stay memoryless).

> **Known limitation.** When `X-Session-Id` is present the client's `history` array
> is ignored entirely — the session *is* the model's context. Chat "regenerate" and
> "edit & resend" are therefore presentation-level rewinds: the superseded turn stays
> in the model's memory, and the UI says so inline. A true rewind needs a backend
> session-truncation path, which does not exist yet.

### Live module interview

The module interview is an interrupt-driven Strands agent: one adaptive question
per turn, paused between HTTP turns via a Strands **interrupt** persisted to a
`FileSessionManager` session. `interview/start` and `interview/{id}/answer` are SSE.
The agent only *chooses* questions — the tuned YAML rubrics still own all grading.

Because all state is server-side, an interrupted interview is **resumable**:
`GET .../interview/{interview_id}` returns a whitelisted projection with a status
ladder (`awaiting_answer` / `awaiting_final` / `complete` / `in_progress`), and the
frontend keeps the id in `localStorage`. Internal calibration state (Elo,
interrupt ids) and the grader's per-question rationale are deliberately withheld.

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

When the RPM bucket makes a request wait, the delay is announced rather than
stalling silently — `model.py` exposes a `throttle_notices` sink that the chat
handler surfaces as a `reasoning` event and the pipelines as a `capacity` `step`.

---

## Tech Stack

### Backend

| Layer | Technology |
|---|---|
| Framework | FastAPI + Uvicorn |
| Agents | **Strands Agents SDK** (orchestrator + specialists + skills) |
| Agent model | NVIDIA NIM via `OpenAIModel` (`qwen/qwen3-next-80b-a3b-instruct`) |
| Heavy generation | Hugging Face Inference (Together / NVIDIA fallback) |
| Database | MongoDB via Motor (async) — the only datastore |
| Real-time | SSE (`text/event-stream`) |
| Evals | DeepEval, NVIDIA-judged, online-sampled |
| Logging | structlog (JSON) |
| Auth | JWT (python-jose) + bcrypt |
| Tooling | `uv` (locked via `pyproject.toml` / `uv.lock`), `ruff` |
| Runtime | Python 3.13+ |

> A Socket.IO server is still mounted (hence `app.main:socket_app`), but nothing
> uses it — all real-time traffic is SSE.

### Frontend

| Layer | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| State | Zustand + TanStack Query |
| Real-time | `fetch` + `ReadableStream` SSE, abortable |
| Styling | Tailwind CSS + `@tailwindcss/typography`, CSS custom properties |
| Markdown / code | react-markdown + remark-gfm, react-syntax-highlighter (`PrismLight`), Monaco (lazy) |
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
│   │   │   ├── model.py            # get_nim_model (NIM, semaphore + RPM bucket + throttle sink)
│   │   │   ├── tools.py            # @tool adapters over the master tool registry
│   │   │   ├── skills.py           # SKILL.md loader + load_skill tool
│   │   │   ├── skills/*/SKILL.md   # progressive-disclosure skill instructions
│   │   │   ├── hooks.py            # GuardrailHook
│   │   │   ├── stream_adapter.py   # Strands events → SSE wire contract + eval grounding
│   │   │   ├── steps.py            # STEP_PLANS + step_emitter for pipeline `step` events
│   │   │   ├── interview_agent.py  # interrupt-driven live interview
│   │   │   ├── session.py          # quiz/interview session state + Bloom mapping
│   │   │   ├── pipelines/          # course_gen · quiz_gen · interview_review · jd_analyze
│   │   │   └── course_planner.py   # interview_scorer.py · skill_gap.py · progress.py
│   │   ├── routers/                # chat.py (SSE), health.py + auth, quiz, courses, jobs, evals, …
│   │   ├── tools/                  # master tool registry + implementations (hf/db/logic)
│   │   ├── prompts/*.yaml          # externalized LLM prompts (SaaS house style)
│   │   ├── evals/                  # DeepEval metrics + MongoDB storage
│   │   ├── db/mongo.py             # all collection accessors
│   │   ├── guardrails.py           # input/output safety
│   │   ├── config.py
│   │   └── main.py                 # FastAPI app + Socket.IO → socket_app
│   ├── tests/                      # unit / integration / e2e / evals
│   └── pyproject.toml              # deps (uv) — requirements.txt is a generated export
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
│   ├── .eslintrc.cjs
│   └── package.json
├── e2e/                            # Playwright harnesses (smoke.py, full.py, api_coverage.py)
├── render.yaml                     # backend deploy blueprint
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

# Run the Socket.IO-wrapped ASGI app — NOT app.main:app (that drops Socket.IO)
uv run uvicorn app.main:socket_app --port 8000 --reload
```

There is no migration step. MongoDB collections are created on first write.

`backend/.env.sample` is kept as an exact 1:1 mirror of `app/config.py` — every
setting, no extras.

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

Default local login: `admin@test.com` / `admin@1234`. `POST /auth/login`
auto-registers an unknown email on first call, so there is no separate signup
endpoint. Sign-in lives on the landing page (`/`); `/login` just redirects there.

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
data: {"type": "step", "id": "work", "label": "…", "status": "active"}
data: {"type": "reasoning", "content": "Let me break this down…"}
data: {"type": "token", "content": "Gradient descent"}
data: {"type": "action", "kind": "quiz_generated", "payload": {...}}
data: {"type": "done", "steps": 2, "total_ms": 4210}
data: [DONE]
```

Additional event types: `error` (generic client-safe message; full detail stays in
server logs) and `guardrail` (input blocked before any LLM call). `tool_call` and
`tool_result` are **not** part of the contract — the mechanical workflow is never
sent to the client.

### Operations

| Method | Route | Description |
|---|---|---|
| `GET` | `/health` | Liveness — always 200 |
| `GET` | `/ready` | Readiness for load balancers — 200 or 503 |
| `GET` | `/health/ready` | Same report, always 200, for debugging |
| `GET` | `/.well-known/agent-card.json` | Agent card |

Readiness reports booleans only (Mongo reachable, `NVIDIA_API_KEY` set,
`HF_TOKEN` set) — never the secret values.

### v1 REST routes (prefixed `/api/v1`)

| Group | Routes |
|---|---|
| Auth | `POST /auth/login` (auto-registers), `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/reset-request`, `POST /auth/reset-confirm` |
| Learner | `GET /learner/roles`, `GET|PUT /learner/profile`, `POST /learner/onboard` |
| Curriculum | `GET /curriculum`, `POST /curriculum/generate`, `GET /curriculum/graph` |
| Courses | `GET /courses/`, `GET /courses/{plan_id}`, `POST /courses/plan`, `POST /courses/plan/stream` |
| Interview | `POST .../interview/start` (SSE), `GET .../interview/{id}`, `POST .../interview/{id}/answer` (SSE), `POST .../interview/{id}/complete[/stream]`, `POST .../interview/{id}/run-code`, `GET /courses/run-code/languages` |
| Quiz | `POST /quiz/generate`, `GET /quiz/{id}`, `POST /quiz/{id}/submit`, `POST /quiz/{id}/submit/stream`, `POST /quiz/{id}/explain`, `GET /quiz/flashcards` |
| Doubts | `POST /doubts/stream` (SSE), `POST /doubts/transcribe`, `POST /doubts/caption`, `GET /doubts/sessions[/{id}]` |
| Progress | `GET /progress`, `GET /progress/due-topics`, `GET /progress/report`, `POST /progress/study-session` |
| Session | `POST /session/start`, `POST /session/advance` |
| Jobs | `GET|POST /jobs`, `GET|PATCH|DELETE /jobs/{id}`, `POST /jobs/analyze/stream`, `POST /jobs/{id}/reanalyze/stream` |
| Content | `GET /content`, `GET /content/{id}`, `POST /content/{id}/regenerate` |
| Feed | `GET /feed`, `GET /feed/trending`, `GET /feed/scheduled`, `POST /feed/run-discovery`, `POST /feed/{id}/snooze|schedule`, `DELETE /feed/{id}/interaction` |
| Leaderboard / Profile | `GET /leaderboard`, `GET /profile/activity-logs`, `GET /profile/activity-stats`, `DELETE /profile/activity-logs` |
| HF | `POST /hf/sentiment`, `GET /hf/status`, `POST /hf/test/{model_key}` |
| Evals (superuser) | `GET /evals/dashboard|results|summary`, `POST /evals/run`, `POST /evals/batch/quiz` |
| Admin | `GET /admin/learners`, `GET|PUT /admin/config`, `POST /admin/send-digest` |

**Quiz submit note:** an answer index of `-1` means "never answered" (timer expired,
or the learner set the question aside). It is graded incorrect, not rejected.

---

## Testing

```bash
cd backend                                     # run from backend/, not the repo root

uv run pytest                                  # full suite
uv run pytest tests/test_strands_agents.py     # single file
uv run pytest --cov=app --cov-report=term-missing
```

### Test suites

| Suite | Collected | What it covers |
|---|---|---|
| `test_e2e.py` | 40 | Full HTTP flow — auth through quiz submission |
| `test_evals.py` | 33 | DeepEval metrics + eval record creation |
| `test_hf.py` | 32 | HF tool implementations |
| `test_strands_agents.py` | 19 | Orchestrator routing, specialists, skills, tool adapters, eval grounding |
| `test_api.py` | 16 | Core API contract |
| `test_steps.py` | 11 | `step` event protocol + pipeline throttle notices |
| `test_session.py` | 11 | Quiz/interview session state machine |
| `test_interview_agent.py` | 11 | Live interview agent + resume endpoint |
| `test_code_runner.py` | 6 | Sandboxed code execution (Piston) |
| `test_jobs.py` | 5 | Job Tracker / skill-gap flows |
| **Total** | **184** | 184 passed, plus 2 modules skipped (DeepEval not installed) |

### Evals

**DeepEval is intentionally not a project dependency.** Its transitive pins
(`tenacity<=9.0`, `click<8.4`) conflict with this project's `tenacity>=9.1` and
`huggingface-hub>=1.20`, which would make `uv sync` unresolvable. So on a default
install:

- `tests/test_deepeval_judge.py` and `tests/evals/test_quality.py` skip at import.
- Online eval sampling in `routers/chat.py` is **fire-and-forget and silently
  no-ops** — including the `FaithfulnessMetric` described above.

To actually run evals:

```bash
uv pip install "deepeval>=4" "instructor>=1.6"
RUN_EVALS=1 uv run pytest -m evals
```

Frontend checks (from `frontend/`):

```bash
npm run lint     # eslint, --max-warnings 0, zero per-file overrides
npx tsc --noEmit
npm run build
```

---

## Environment Variables

`backend/.env.sample` is the authoritative list — it mirrors `app/config.py`
exactly. Copy it and fill in the secrets:

```bash
cp backend/.env.sample backend/.env
```

The ones you must set:

```ini
SECRET_KEY=<256-bit random string>
MONGO_URL=mongodb://localhost:27017
NVIDIA_API_KEY=<your_key>
HF_TOKEN=hf_<your_token>
CORS_ORIGINS=http://localhost:5173
```

Frequently tuned:

```ini
NIM_ORCHESTRATOR_MODEL=qwen/qwen3-next-80b-a3b-instruct
NIM_SPECIALIST_MODEL=qwen/qwen3-next-80b-a3b-instruct
NIM_RPM_LIMIT=40               # NVIDIA free-tier requests/minute
AGENT_SESSIONS_DIR=            # empty → OS temp dir; point at a volume for durable memory
CHAT_MEMORY_WINDOW=40          # messages kept per thread
INTERVIEW_MAX_QUESTIONS=8
EVAL_JUDGE_MODEL=qwen/qwen3-next-80b-a3b-instruct
EVALS_ONLINE_SAMPLING=true
LANGFUSE_PUBLIC_KEY=           # optional tracing; empty disables
```

> Never commit `.env`. It is listed in `.gitignore`.

---

## Deployment

- **Frontend** → Vercel. Set `VITE_API_BASE_URL` to the backend URL.
- **Backend** → Render via `render.yaml` (repo root). Set `NVIDIA_API_KEY`,
  `HF_TOKEN`, `MONGO_URL`, `SECRET_KEY`, `CORS_ORIGINS`.

`AGENT_SESSIONS_DIR` left empty means chat thread memory lives in the OS temp
directory and resets on every redeploy; durable memory needs a mounted persistent
disk (a paid Render plan).

---

*Built with FastAPI, the Strands Agents SDK on NVIDIA NIM, and React.*
