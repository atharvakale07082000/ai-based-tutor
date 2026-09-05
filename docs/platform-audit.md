# Platform Audit — Atelier (ai-tutor)

Read-only audit of stack, AI layer, backend, frontend UX, and product copy.
Companion document: [platform-plan.md](platform-plan.md).

**Scope:** all four surfaces (chat, interviews, learn/quiz, tracker/admin) weighted equally.
Out of scope by request: `e2e/`, `backend/scripts/`, and test quality as a subject (test
*coverage* on paths the plan touches is still assessed).

**Severity:** P0 blocks users · P1 hurts daily use · P2 friction · P3 polish.
**Effort:** S <½ day · M ½–2 days · L 3–5 days.
Rows marked ⚠ are model-facing — behaviour changes there are silent and cannot be caught by
a deterministic assertion.

---

## Executive summary

The backend is in good shape. Zero bare `except`, zero `print`, zero TODO/FIXME markers,
consistent `to_thread` offloading of blocking SDK calls, no secrets in source, and a prompt
layer that is genuinely externalised and versioned per file. That is better hygiene than most
codebases this size.

The debt is concentrated in two seams.

**The transport seam.** There are three different SSE readers in the browser and two SSE
emitters on the server. The differences between them are where all three reported pains come
from: one reader corrupts text, one drops frames, none of them refresh an expired token, and
one leaks raw exception strings to the client.

**The copy seam.** The product names its core object nine different ways, speaks in three
voices, and states three things on screen that the code contradicts — including two numbers
on the landing page. This is the layer users actually read, and it is the reason the platform
reads as unfinished despite the engineering underneath being sound.

Headline risks, in order: text corruption visible to learners (A3), streams that die silently
when a 30-minute token expires (A1), a graded Elo rating shipped with no accuracy caveat
anywhere in the product (C13), and no frontend test or type-checking net under any of it.

---

# Phase 1 — Inventory

## Stack

| Layer | Reality | Evidence |
|---|---|---|
| Backend | FastAPI ≥0.138, Python **3.13**, **uv** (`requirements.txt` is a stub pointing at uv) | `backend/pyproject.toml:6`, `backend/requirements.txt:1` |
| Async model | Async throughout; blocking SDK calls wrapped in `asyncio.to_thread` across 27 modules. Zero `time.sleep`/`requests`/`subprocess` in `app/` | grep |
| Entrypoint | `app.main:socket_app` — a Socket.IO ASGI app wrapping FastAPI | `backend/app/main.py:291` |
| Frontend | **React 18 + Vite 5 + TypeScript 5.4, one SPA. No Next.js** | `frontend/package.json` |
| Routing / state / data | react-router-dom 6, Zustand (6 stores), TanStack Query v5 (19 files) | `App.tsx:159-186`, `src/stores/` |
| FE↔BE contract | Hand-written TS interfaces, no codegen. **89 routes, 15 with `response_model`** | `frontend/src/lib/api.ts` |
| Deploy | Vercel (frontend) + Render Docker, free plan (backend); `docker-compose.yml` for local | `render.yaml` |
| Gates | ruff `E,F,W,I` + pre-commit. **No mypy.** 255 backend tests, **0 frontend tests** | `ruff.toml`, `.pre-commit-config.yaml` |

21.8k LOC Python / 13.9k LOC frontend / 266 tracked files.

**Frontend apps: one.** Not a multi-app split. The split is *inside* the app (see below).

## AI layer

| Concern | Where it lives | Notes |
|---|---|---|
| Prompts | 16 × `app/prompts/*.yaml` + 11 × `agents/skills/*/SKILL.md` | Externalised and versioned per file. The healthiest part of the system. |
| Providers | **Two stacks**: Strands→NIM (`agents/model.py:110`) and HF/Together/NVIDIA (`hf/client.py:61`, `hf/generation_client.py`) | 20 modules import `app.hf.*` from outside `app/hf/` |
| Model IDs | 4 settings, all `nvidia/nemotron-3-super-120b-a12b` | `config.py:42,63,64,91` |
| Tools | **Two registries**: `agents/tools.py` (`@tool`) and `app/tools/registry.py` + `implementations/` | |
| Retrieval / vectors | **None.** Embeddings computed + TTL-cached; `goal_vector` is a stored field, not an index | 0 hits for faiss/chroma/pinecone/`$vectorSearch` |
| Workers | Celery + Redis + beat schedule defined; **no worker service in `render.yaml`**; one live caller | `tasks/celery_app.py`, `admin.py:171` |
| Streaming | SSE only. Shared framing in `app/sse.py`; chat + doubts hand-roll their own | `chat.py:230`, `doubts.py:122` |
| Output parsing | Centralised in `agents/json_utils.py` — 29 call sites | one stray `json.loads` at `stream_adapter.py:94` |
| Resilience | `app/resilience.py` (retry + breaker), `HF_SEMAPHORE` (40 concurrent), `_RpmBucket` (NIM RPM), slowapi | |
| Observability | Langfuse root spans + Strands auto-instrumentation; optional OTel; structlog JSON with correlation + trace ids | `observability.py` |
| Token / cost | **No app-side accounting.** Only what Langfuse derives after the fact | 1 module touches `prompt_tokens` |
| Evals | Offline Strands trajectory evals, Langfuse server-side judges, and a DeepEval suite deliberately not installed | `pyproject.toml:41-49` |
| Secrets | pydantic-settings only; `render.yaml` uses `sync: false`; readiness reports key *presence* | `config.py`, `render.yaml` |

## UI

22 lazy-loaded routes, all guarded by `PrivateRoute + ErrorBoundary + PageWrapper` except the
four public ones (`App.tsx:159-186`).

Shared component reuse: `Icon` 28 files, `Button` 21, `Badge` 18, `Progress` 17, `Card` 14,
`ReasoningStream` 7, `Skeleton`/`EmptyState` 6. **`Tabs`, `Tooltip`, `Divider`, `Kbd` are
exported from `ui/index.ts` with zero consumers.**

Styling is split three ways: **1,131 inline `style={{}}` vs 643 `className`**, over a
729-line `index.css` token layer. Tailwind is the minority system.

Accessibility baseline: 18 `<label>` elements with **0 `htmlFor`**; **1 `aria-live` in the
entire app** across four streaming surfaces; 32 `aria-label`, 20 `role=`.

Largest files: `InterviewRunner.tsx` 1,479 LOC · `lib/api.ts` 976 · `AtelierV2Page.tsx` 942.

## The same problem solved more than one way

| # | Problem | Ways | Evidence |
|---|---|---|---|
| 1 | Consume an SSE stream in the browser | **3** — `streamChat` (no buffer), `streamSSE` (buffers), DoubtChat inline (no buffer, no abort, raw localStorage token) | `api.ts:889`, `api.ts:947`, `DoubtChatPage.tsx:93` |
| 2 | Emit an SSE response | **2** — `app/sse.py` helper vs hand-rolled `StreamingResponse` | `chat.py:230`, `doubts.py:122` |
| 3 | Call an LLM | **2** provider stacks | `agents/model.py` vs `hf/client.py` |
| 4 | Define a tool | **2** registries | `agents/tools.py` vs `app/tools/registry.py` |
| 5 | Define request/response schemas | **2** homes — `app/schemas/*` (5 modules) vs **16 inline `BaseModel`s in routers** | grep |
| 6 | Style a component | **3** systems | inline / Tailwind / CSS custom properties |
| 7 | Background work | **2** — Celery (unshipped) vs `asyncio.create_task` | `tasks/`, `middleware/activity_logger.py` |
| 8 | Real-time transport | **2** mounted — Socket.IO (0 emitters, 0 clients) + SSE | `main.py:46,291` |
| 9 | **Name the core product object** | **9** — see C1 below | `Sidebar.tsx`, `CommandPalette.tsx`, toasts |

## Dormant / stale artifacts

- `backend/ai_tutor.db` — 233 KB SQLite file, **zero code references**, contradicts the
  MongoDB-only invariant.
- `pyproject.toml:4` and `main.py:117` ship **"LangGraph + Hugging Face"** as the public
  OpenAPI description; LangGraph was deleted.
- `backend/pytest.ini` duplicates `[tool.pytest.ini_options]` in `pyproject.toml`.
- Zero `TODO`/`FIXME`/`HACK` markers repo-wide.

---

# Phase 2 — Findings

## Pain #1 (confirmed) — "chat text looks wrong / truncated"

| ID | Finding | Evidence | Why it matters | Blast radius | Sev | Eff |
|---|---|---|---|---|---|---|
| **A3** | **Doubt chat renders the literal string `undefined` into the answer.** The reader destructures `{ token }` from every frame and does `full += token`. The backend's error frame is `{"error": …}` — no `token` key — so `undefined` is appended to the visible answer, *and the error itself is never surfaced*. | `DoubtChatPage.tsx:105-106` + `doubts.py:119` | Visible text corruption plus a swallowed failure. | Doubt chat | **P0** | S |
| **A4** | **The chat SSE reader has no partial-frame buffer.** `streamChat` splits each network chunk on `\n` and silently discards unparseable lines. `streamSSE`, 50 lines below, keeps a `buffer` for exactly this case. A token frame split across two TCP reads vanishes. | `api.ts:895-903` vs `api.ts:949-966` | Silent, non-reproducible text loss in the main chat. | Atelier chat | **P1** | S |
| **A1** | **All three SSE paths bypass the 401 refresh interceptor.** Silent refresh-and-retry exists only on the axios instance; every stream uses raw `fetch`. Access tokens expire in 30 minutes. | `api.ts:145-170` vs `api.ts:874`, `api.ts:933`, `DoubtChatPage.tsx:78`; `config.py:27` | A stream started after expiry dies with a bare "Stream failed" and no re-login prompt. Interviews routinely run past the boundary. | Chat, doubt chat, quiz submit, every interview turn, JD analysis, course plan, loop setup/debrief | **P1** | S |

## Pain #2 (confirmed) — "Thinking… never shows anything"

| ID | Finding | Evidence | Why it matters | Sev | Eff |
|---|---|---|---|---|---|
| **A5** | **The backend already streams a chat progress timeline and the UI throws it away.** `chat.py` emits `step` events (`route` → `work` → `answer`) on every turn. `AtelierV2Page`'s event switch has no `case 'step'` — it falls through to `default: return msg`. Separately, the current model will not emit the `<reasoning>` block once tools are bound, and `ReasoningStream` returns `null` when empty. Net: nothing renders for the entire multi-second tool phase. | `chat.py:151-152`, `steps.py:68-72`, `AtelierV2Page.tsx:283`, `config.py:60-62`, `ReasoningStream.tsx:35` | The most visible "is it working?" signal is silent. **The fix needs no model change — the data is already on the wire.** | **P1** | S |

## Pain #3 (confirmed) — "errors are vague"

| ID | Finding | Evidence | Why it matters | Sev | Eff |
|---|---|---|---|---|---|
| **U1** | **A blocked prompt silently deletes the learner's message.** The backend sends `{"type":"guardrail", …}` with a written explanation, then returns without a `done`. The UI has no `guardrail` case, so the text is discarded; the `finally` block then sees an empty bubble and drops it. | `chat.py:102` vs `AtelierV2Page.tsx:266-284`, `AtelierV2Page.tsx:304-305` | The question visibly vanishes with no reason given. The explanation was written and never shown. | **P1** | S |
| **U1b** | **Flat error taxonomy.** 66 `toast.error` sites; none distinguish 429 rate-limit, timeout, model refusal, or empty result. | grep | Users can't tell "wait a minute" from "rephrase" from "we're broken". | **P1** | M |
| **A2** | **Doubt chat leaks raw exception text to the client** (`str(e)`), where chat sends a generic message. | `doubts.py:119` vs `chat.py:217` | Information disclosure — connection strings and provider errors appear in exception text. | **P1** | S |

## AI-layer architecture

| ID | Finding | Evidence | Sev | Eff |
|---|---|---|---|---|
| A6 ⚠ | **Two provider stacks.** Swapping a model means touching 4 settings across 2 client implementations with different retry/breaker/`extra_body` semantics. | `agents/model.py:110`, `hf/client.py:61`, `config.py:42,63,64,91` | P2 | M |
| A13 | **No app-side token/cost accounting or budget.** No per-learner cap, no runaway-spend circuit. | grep | P2 | M |
| A14 | `POST /chat` — the most expensive endpoint — has **no `@limiter.limit`**, only the global 200/min. Every other LLM endpoint is explicitly limited (3/hour, 6/hour, 20/hour). | `chat.py:41` vs `courses.py:89`, `quiz.py:42`, `doubts.py:35` | P2 | S |
| A15 | **Positive:** the prompt layer is healthy — externalised, per-file versioned, house-styled, brace rules documented. No sprawl finding. | `app/prompts/`, `agents/skills/` | — | — |

## Python backend

| ID | Finding | Evidence | Sev | Eff |
|---|---|---|---|---|
| A7 | **Sync Celery `.delay()` inside an async handler**, against a Redis that `render.yaml` never provisions. Blocks the event loop until broker timeout. | `admin.py:171`, `render.yaml` | P2 | S |
| A8 | **Socket.IO mounted with zero emitters and zero frontend clients.** Keeps `python-socketio` a dependency and forces the `socket_app` entrypoint footgun. | `websocket.py`, `main.py:46,291` | P2 | S |
| A9 | **74 of 89 routes have no `response_model`**, while the TS types mirroring them are hand-maintained. Drift is invisible until runtime. | grep | P2 | M |
| A10 | Schemas live in two homes: `app/schemas/*` and 16 inline `BaseModel`s in routers. | grep | P3 | S |
| A11 | **No mypy, no type-checking gate.** ruff runs `E,F,W,I` only. | `ruff.toml` | P2 | M |
| A12 | Dead artifacts: `ai_tutor.db`, the "LangGraph" OpenAPI description, duplicate `pytest.ini`. | listed above | P3 | S |
| A16 | **Positive:** 0 bare `except`, 0 `print`, 0 TODO markers, consistent `to_thread` offloading, no secrets in source. | grep | — | — |

## Frontend UX

| ID | Finding | Evidence | Why it matters | Sev | Eff |
|---|---|---|---|---|---|
| U2 | **Two chat surfaces, opposite affordances.** Atelier has stop, regenerate, and edit-and-resend; doubt chat has none — no `AbortController` at all, so a stuck answer can only be escaped by leaving the page. | `AtelierV2Page.tsx:154,328,357` vs `DoubtChatPage.tsx` | Same mental model, different capabilities. | P1 | M |
| U3 | **Streamed text is unannounced and labels are unbound.** 18 `<label>`, **0 `htmlFor`**. **1 `aria-live`** across four streaming surfaces. | grep | Screen-reader users get neither the answer nor form labels. | P1 | M |
| U4 | **The majority styling system can't express breakpoints.** 1,131 inline `style={{}}` vs 643 `className`; 5 `@media` rules + 63 responsive utilities is the entire responsive surface for 22 routes. | grep | This is the mechanism behind mobile layout problems, not a preference. | P2 | L |
| U5 | **Destructive actions without confirmation** — delete a job application, delete a chat thread. Only "clear activity logs" confirms. | `JobTrackerPage.tsx:193`, `AtelierV2Page.tsx:559` vs `ActivityLogSection.tsx:93` | Irreversible, one click, no undo. | P2 | S |
| U6 | **4 exported UI primitives with zero consumers.** `Input` used in only 3 files while forms are hand-rolled elsewhere. | `ui/index.ts` + grep | The design system isn't the path of least resistance. | P2 | S |
| U7 | `InterviewRunner.tsx` — **1,479 LOC, 157 inline styles**, owning voice, Monaco, resume, recovery, and scoring. | file | Highest-risk file in the repo; drives 3 of 4 streaming paths. | P2 | M |
| U8 | Doubt chat reads the JWT straight from `localStorage`, bypassing the token module. | `DoubtChatPage.tsx:81` | P3 | S |
| U9 | **Zero frontend tests.** | `find` = 0 | Blocks safe shared-UI consolidation. | P2 | M |

## Copy, vocabulary & product surface

Every user-facing string was audited: nav labels, empty states, placeholders, button labels,
38 error messages, 30 success toasts, landing page. The standard applied: *does the interface
speak with one voice, name things the way a user would, and say what to do next?*

| ID | Finding | Evidence | Why it matters | Sev | Eff |
|---|---|---|---|---|---|
| **C1** | **One object has nine names.** "curriculum" (11 uses), "career path" (6), "learning path" (7), "learning plan" (2), "course plan" (2), "study plan", "learning roadmap", "course", "path". The nav says **Career Paths**, ⌘K says **My Courses** and **Plan a new course** tagged **Learning Path**, one toast says "Your learning plan is ready!" and another "Building your personalised curriculum…". | `Sidebar.tsx:31`, `CommandPalette.tsx:15,25`, grep counts | A user cannot build a mental model of a product that renames its core object every screen. The single biggest reason the platform reads as unpolished. | **P1** | M |
| **C2** | **Sidebar and command palette disagree on 3 of 8 destinations.** `/learn` = "Career Feed" vs "Go to Today"; `/courses` = "Career Paths" vs "My Courses"; `/doubts` = "Career Coach" vs "Open Doubt Chat" vs "Ask a doubt…" vs "No coaching sessions yet". | `Sidebar.tsx:22-33` vs `CommandPalette.tsx:11-27`, `DashboardPage.tsx:277` | ⌘K is the power-user path; teaching a second vocabulary there actively unteaches the product. | **P1** | S |
| **C3** | **The landing page states two numbers the code contradicts.** "**32** sub-skills rated" — the topic graph holds ~108 sub-topics across 15 domains and proficiency is a free-form map with no fixed 32. "**6** agents on call" — `SPECIALISTS` contains **5**. | `LandingPage.tsx:299-301` vs `prompts/curriculum.yaml` topic_graph, `specialists.py:37-81` | Unbacked numbers on the highest-traffic page, violating this repo's own "don't ship a number the product can't back" rule. | **P1** | S |
| **C4** | **A promise the system is architected to break.** The module player says "Preparing your content — **this takes about 10 seconds**". The NIM RPM bucket can park a call for up to 60s, and a capacity-notice mechanism already exists to say so. | `ModulePlayerPage.tsx:169` vs `model.py:89-93` | Every throttled generation makes the product look broken rather than busy — and the honest mechanism is bypassed. | **P1** | S |
| **C5** | **The empty leaderboard says "Leaderboard loading…" forever.** The string sits in the `board.length === 0` branch, not a loading branch. | `DashboardPage.tsx:390-392` | A new user's first dashboard shows a permanent fake spinner. | **P1** | S |
| **C6** | **Three narrators in one product.** System voice ("Could not analyze the job", "Agent config updated"), a first-person AI ("I hit a snag — send your question again", "Give me a bit more to work with", "Heard you!"), and a cheerleader ("Quiz ready — good luck!", "That's a detailed one!", "Your content is ready! ✨"). | grep across all toasts | No consistent character, so none of the voices land. | **P1** | M |
| **C7** | **22 of 38 errors restate the failed action with no cause and no recovery** — "Could not analyze the job", "Could not save changes", "Could not write your debrief". "**Discovery failed**" doesn't even name what was discovering. | grep `toast.error` | The copy half of pain #3: the taxonomy fixes *which* error, this fixes *what it says*. | **P1** | M |
| **C8** | **The same message ships two ways, inconsistently punctuated.** "Name must be at least 2 characters" exists both with and without a full stop. "Could not generate quiz" and "Could not generate quiz — try again" both exist. "Failed to…" and "Could not…" are used interchangeably. | grep | Sloppiness users feel without being able to name. | **P2** | S |
| **C9** | **System vocabulary leaks to users** — "Agent config updated", "AI Model Status", "Test Model", "Agent Evals", "Trend discovery started", "Content regeneration started", and an empty state that explains the sampling implementation: "Evals are sampled randomly from live requests." | `Sidebar.tsx:55`, `AdminPage.tsx`, `EvalsDashboardPage.tsx:99` | Names things by how the system is built, not by what the person controls. | **P2** | S |
| **C10** | **Empty states describe emptiness instead of inviting action.** "No goals set yet / Add learning goals to track your progress." and "No coaching sessions yet / Ask your career coach a question" both *name* the action and neither provides a button — `EmptyState` has an `action` prop these callers don't pass. | `ProfilePage.tsx:233`, `DashboardPage.tsx:275`, `EmptyState.tsx:16` | Dead ends on two screens a new user lands on first. | **P2** | S |
| **C11** | **"Restricted"** is the entire message a non-superuser gets on two pages, with no path forward. | `AdminPage.tsx:300`, `EvalsDashboardPage.tsx:73` | Reads as a permissions error, not a product boundary. | **P2** | S |
| **C12** | **Mixed button casing** — "Take Quiz", "Test Model", "View Progress" next to "Save changes", "Save to board", "Sign in". | grep | P2 | S |
| **C13** | **Zero AI limitation disclosure anywhere.** No "can make mistakes", no "verify this" — across a platform that generates lesson content, grades interview answers, and markets an Elo as "A rating for what you know" / "Find out your number." | 0 matches for any caveat phrasing; `LandingPage.tsx:281,414` | A graded score with no accuracy caveat is the platform's largest trust liability. | **P1** | S |

## Preference, not defect

Labelled explicitly so these are not mistaken for bugs:

- **A first-person AI voice is a legitimate choice**, and "I hit a snag — send your question
  again and I'll come right back" is good writing. C6 is a finding because the product uses
  *three* voices, not because it uses that one. Choosing it deliberately and applying it
  everywhere is a valid resolution.
- **"Doubt" as a noun** is regional English but is used consistently within that surface. The
  defect is that the same surface is *also* called "Career Coach" (C2), not the word itself.
- **Inline styles over Tailwind** is defensible on its own. U4 is a finding only because it
  removes breakpoint capability, not because Tailwind is better.
- **`lib/api.ts` at 976 LOC** is large but coherent; splitting it is taste, not debt.
- **6 Zustand stores alongside TanStack Query** is a clean client/server state split, not
  duplication.
