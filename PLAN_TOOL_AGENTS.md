# Tool-Agents Architecture — Implementation Plan

Branch: `feat/tool-agents`  
Current branch: `main` is untouched.

---

## 1. Problem with the Current Architecture

| Issue | Where |
|---|---|
| Agents are LangGraph nodes — no concept of "which tool belongs to which agent" | `app/agents/*.py` |
| Tool registry is a flat dict of callables, no schemas, no descriptions | `app/agents/tools.py` |
| Supervisor routes blindly — user can't see why or where their query went | `app/agents/supervisor.py` |
| No internal reasoning visible — LLM decides silently, frontend only sees final text | all |
| SSE streams only raw tokens — no structured events for tool calls or thoughts | `app/routers/doubts.py`, `app/routers/assistant.py` |

---

## 2. Target Architecture

```
User query
    │
    ▼
┌─────────────────────────────────────────────┐
│  AgentRouter  (fast rule-based + LLM fallback) │
│  → emits:  {type: "routing", agent, reason}   │
└─────────────────────────┬───────────────────┘
                          │ picks one of:
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
  CurriculumAgent    QuizAgent        DoubtAgent
  ProgressAgent      AssistantAgent   (future)

Each agent runs a ReAct loop:
  ┌──────────────────────────────────────┐
  │  Step N                              │
  │  1. think(query + history + obs)     │  → {type: "thought", step, content}
  │  2. pick_action()                    │  → {type: "tool_call", step, name, args}
  │  3. execute tool from registry       │  → {type: "tool_result", step, name, result, ms}
  │  4. if done: stream final answer     │  → {type: "token", content}*
  └──────────────────────────────────────┘

Master Tool Registry
  ┌─────────────────────────────────────────────────┐
  │  classify_topic   analyze_sentiment  score_diff  │
  │  generate_quiz    get_embeddings     calc_elo    │
  │  get_proficiency  save_quiz          save_prog   │
  │  check_guardrail  get_topic_graph               │
  └─────────────────────────────────────────────────┘
  Each agent declares a whitelist of tool names it may call.
```

### SSE Event Envelope

Every event is a JSON line prefixed `data: `:

```jsonc
{"type": "routing",     "agent": "QuizAgent",    "reason": "query contains 'quiz me'"}
{"type": "thought",     "step": 1, "content": "The learner wants a quiz on PCA at apply level."}
{"type": "tool_call",   "step": 1, "name": "score_difficulty", "args": {"text": "PCA"}}
{"type": "tool_result", "step": 1, "name": "score_difficulty", "result": {"score": 0.72}, "latency_ms": 340}
{"type": "thought",     "step": 2, "content": "Difficulty is 0.72, so I'll keep bloom at apply."}
{"type": "tool_call",   "step": 2, "name": "generate_quiz",    "args": {"topic": "PCA", "bloom_level": "apply", "count": 5}}
{"type": "tool_result", "step": 2, "name": "generate_quiz",    "result": {"questions": [...]},  "latency_ms": 1800}
{"type": "thought",     "step": 3, "content": "Quiz ready. I'll save it and present it to the learner."}
{"type": "tool_call",   "step": 3, "name": "save_quiz",        "args": {"topic": "PCA", "bloom_level": "apply"}}
{"type": "tool_result", "step": 3, "name": "save_quiz",        "result": {"quiz_id": "abc123"}, "latency_ms": 45}
{"type": "token",       "content": "Here"}
{"type": "token",       "content": " is your"}
...
{"type": "action",      "kind": "quiz_created",  "payload": {"quiz_id": "abc123", "topic": "PCA", "url": "/quiz/abc123"}}
{"type": "done",        "steps": 3, "total_ms": 4200}
```

---

## 3. Backend File Map

```
backend/app/
├── tools/                          ← NEW
│   ├── __init__.py
│   ├── registry.py                 # ToolRegistry class + global instance
│   ├── schemas.py                  # Tool, ToolResult dataclasses
│   └── implementations/
│       ├── __init__.py
│       ├── hf_tools.py             # HF-backed: classify_topic, analyze_sentiment, score_difficulty, generate_quiz, get_embeddings
│       ├── db_tools.py             # DB-backed:  get_proficiency, save_quiz, save_progress, get_topic_graph
│       └── logic_tools.py         # Pure-logic: calculate_elo, check_guardrail
│
├── agents_v2/                      ← NEW
│   ├── __init__.py
│   ├── base.py                     # BaseAgent: ReAct loop, streaming, max_steps guard
│   ├── router.py                   # AgentRouter: rule-based + Qwen LLM fallback
│   ├── curriculum_agent.py         # CurriculumAgent (tools: classify_topic, get_topic_graph, get_proficiency)
│   ├── quiz_agent.py               # QuizAgent     (tools: score_difficulty, generate_quiz, get_proficiency, save_quiz)
│   ├── progress_agent.py           # ProgressAgent (tools: calculate_elo, analyze_sentiment, get_proficiency, save_progress)
│   ├── doubt_agent.py              # DoubtAgent    (tools: check_guardrail, get_proficiency — then streams LLM directly)
│   └── assistant_agent.py          # AssistantAgent (all tools — orchestrates other agents via tool calls)
│
└── routers/
    └── v2/
        ├── __init__.py
        └── chat.py                 # POST /api/v2/chat — SSE stream endpoint
```

---

## 4. Tool Registry Design

### `app/tools/schemas.py`

```python
@dataclass
class Tool:
    name: str
    description: str          # shown to LLM in system prompt
    parameters: dict          # JSON Schema for args
    handler: Callable         # async function
    category: str             # "hf" | "db" | "logic"
    timeout_s: float = 30.0

@dataclass
class ToolResult:
    name: str
    args: dict
    result: dict | None
    error: str | None
    latency_ms: int
```

### `app/tools/registry.py`

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None
    def get(self, name: str) -> Tool              # raises KeyError if unknown
    def subset(self, names: list[str]) -> list[Tool]  # for agent system prompt
    async def call(self, name: str, args: dict) -> ToolResult
```

### Tool Catalogue (13 tools)

| Name | Category | Handler | Agent(s) |
|---|---|---|---|
| `classify_topic` | hf | `hf/topic_classifier.py` | Curriculum, Assistant |
| `analyze_sentiment` | hf | `hf/sentiment.py` | Progress, Assistant |
| `score_difficulty` | hf | `hf/difficulty_scorer.py` | Quiz, Assistant |
| `generate_quiz` | hf | `hf/quiz_generator.py` | Quiz, Assistant |
| `get_embeddings` | hf | `hf/embeddings.py` | Doubt, Assistant |
| `generate_explanation` | hf | `hf/doubt_solver.py` (single-shot) | Doubt |
| `get_proficiency` | db | `col_learners` read | All agents |
| `get_topic_graph` | db | prompts config read | Curriculum, Assistant |
| `save_quiz` | db | `col_quizzes` write | Quiz |
| `save_progress` | db | `col_learners` + `col_progress` write | Progress |
| `calculate_elo` | logic | `progress_agent.calculate_elo_update` | Progress |
| `check_guardrail` | logic | `guardrails.check_input` | Doubt, All |
| `get_due_topics` | db | `hf/spaced_repetition.compute_due_topics` | Assistant |

---

## 5. Base Agent — ReAct Loop

```
BaseAgent.run(query, context, emit_fn)
│
├─ build_system_prompt()          # agent name + role + available tools with schemas
│
├─ LOOP (max_steps = 6):
│   ├─ decide_step(messages)
│   │   └─ Qwen2.5-7B-Instruct (non-streaming, JSON mode)
│   │      Returns: {"thought": str, "action": {"tool": str, "args": dict}}
│   │            OR {"thought": str, "final_answer": str, "side_effects": [...]}
│   │
│   ├─ emit({type: "thought", step, content: thought})
│   │
│   ├─ if action:
│   │   ├─ emit({type: "tool_call", step, name, args})
│   │   ├─ result = await registry.call(name, args)
│   │   ├─ emit({type: "tool_result", step, name, result, latency_ms})
│   │   └─ append observation to messages
│   │
│   └─ if final_answer:
│       ├─ stream_answer(final_answer)   # token-by-token via Qwen streaming
│       │   └─ emit({type: "token", content}) per token
│       ├─ for each side_effect:
│       │   └─ emit({type: "action", kind, payload})
│       └─ emit({type: "done", steps, total_ms})
│           BREAK
│
└─ if max_steps reached without final_answer:
    └─ emit({type: "error", message: "max steps reached"})
```

**Why non-streaming for think steps?**  
The think step must produce valid JSON to parse the action. Streaming a JSON object token-by-token makes parsing fragile. Using a non-streaming call for the think step (< 200 tokens, fast) and a streaming call for the final answer (can be long) gives clean separation.

---

## 6. Agent Definitions

### CurriculumAgent
- **Role**: Analyze learner goals, map to topic graph, output an ordered learning path.
- **Tools**: `classify_topic`, `get_topic_graph`, `get_proficiency`
- **Trigger phrases**: "what should I learn", "plan my curriculum", "learning path", "roadmap"
- **Output**: Structured learning path + optional `{type: "action", kind: "plan_created"}`

### QuizAgent
- **Role**: Generate a Bloom-calibrated quiz for a topic, adapted to learner's current Elo.
- **Tools**: `get_proficiency`, `score_difficulty`, `generate_quiz`, `save_quiz`
- **Trigger phrases**: "quiz me", "test me", "generate questions", "quiz on"
- **Output**: Streaming answer confirming quiz ready + `{type: "action", kind: "quiz_created"}`

### ProgressAgent
- **Role**: After a quiz, update Elo and capture mood from reflection text.
- **Tools**: `get_proficiency`, `calculate_elo`, `analyze_sentiment`, `save_progress`
- **Trigger phrases**: "my score was", "I got X%", "update my progress", internal session advance
- **Output**: Streaming summary of Elo change + mood + `{type: "action", kind: "progress_updated"}`

### DoubtAgent
- **Role**: Answer a learner's conceptual question with guardrail checks.
- **Tools**: `check_guardrail`, `get_proficiency`, `get_embeddings` (for context retrieval)
- **Special**: After tool calls, streams the final answer directly via `stream_doubt_response()` for high-quality, long-form output — does not use `generate_explanation` tool.
- **Trigger phrases**: "explain", "what is", "how does", "why does", "I don't understand"

### AssistantAgent
- **Role**: General meta-agent. Has access to all tools. Handles anything that doesn't cleanly fit one specialist.
- **Tools**: all 13
- **Trigger**: fallback when router isn't confident

---

## 7. AgentRouter

```
AgentRouter.route(query: str, context: dict) → (agent_name: str, reason: str)

Phase 1 — Rule-based (zero latency):
  keyword sets:
    quiz:        {"quiz", "test me", "question", "assess"}
    curriculum:  {"learn", "path", "roadmap", "curriculum", "plan", "goal"}
    progress:    {"score", "elo", "my progress", "how am i doing", "update"}
    doubt:       {"explain", "what is", "how does", "why", "understand", "confused"}

Phase 2 — LLM fallback (only when Phase 1 gives no confident match):
  Single non-streaming call to Qwen2.5-7B-Instruct:
  "Given this query: '{query}', which agent should handle it?
   Options: quiz | curriculum | progress | doubt | assistant
   Reply with JSON: {\"agent\": \"...\", \"reason\": \"...\"}"
  Timeout: 5s. On timeout → assistant.
```

---

## 8. SSE Endpoint

```
POST /api/v2/chat
Authorization: Bearer <token>

Body:
{
  "message": "Quiz me on PCA",
  "history": [{"role": "user", "content": "..."}, ...],  // optional, last 6 turns
  "context": {"current_topic": "...", "bloom_level": "..."}  // optional
}

Response: text/event-stream
Content-Type: text/event-stream
X-Accel-Buffering: no

Stream:
  data: {"type": "routing", ...}\n\n
  data: {"type": "thought", ...}\n\n
  ...
  data: [DONE]\n\n
```

Implementation in `app/routers/v2/chat.py`:
1. Auth check → get `learner_id`
2. Build `context` dict from learner's MongoDB profile (proficiency, topic)
3. Route via `AgentRouter`
4. Emit `routing` event
5. Call `agent.run(message, context, emit_fn)` — async generator
6. For each event from agent: `yield f"data: {json.dumps(event)}\n\n"`
7. On exception: `yield data: {"type": "error", ...}\n\n`
8. Always end with `data: [DONE]\n\n`

---

## 9. Frontend — AtelierV2Page

New page at `/assistant-v2`. The existing `/assistant` page is untouched.

### Component tree

```
AtelierV2Page
├── Left rail (agent status, tool palette) — same as AssistantPage
└── Main thread
    ├── MessageList
    │   ├── UserMessage (plain text bubble)
    │   └── AssistantMessage
    │       ├── StreamTrace (collapsible)
    │       │   ├── RoutingChip: "→ QuizAgent · quiz requested"
    │       │   └── Step N:
    │       │       ├── ThoughtBubble: italic text
    │       │       └── ToolCallCard
    │       │           ├── Header: "🔧 generate_quiz"
    │       │           ├── Args:   collapsible JSON
    │       │           ├── Result: collapsible JSON
    │       │           └── Badge:  "1.8s"
    │       ├── MarkdownMessage (final answer, streaming)
    │       └── ActionCardView (quiz_created / plan_created cards)
    └── Composer (same as AssistantPage)
```

### New components needed

| Component | File | Purpose |
|---|---|---|
| `StreamTrace` | `src/components/agents/StreamTrace.tsx` | Wrapper for the full trace (routing + steps) |
| `ThoughtBubble` | inside StreamTrace | Renders one thought step |
| `ToolCallCard` | `src/components/agents/ToolCallCard.tsx` | Renders one tool call + result |
| `RoutingChip` | inside StreamTrace | "→ QuizAgent" badge |

### State model per message

```typescript
interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string              // final answer (streamed)
  streaming: boolean
  routing?: { agent: string; reason: string }
  steps: AgentStep[]           // populated as stream arrives
  actions: ActionCard[]
}

interface AgentStep {
  step: number
  thought?: string
  toolCall?: { name: string; args: Record<string, unknown> }
  toolResult?: { result: unknown; latency_ms: number }
}
```

### Stream parsing logic (in `assistantV2API.streamChat`)

```
reader loop:
  parse SSE line → JSON event
  switch event.type:
    "routing"     → set message.routing
    "thought"     → append/update step[N].thought
    "tool_call"   → set step[N].toolCall
    "tool_result" → set step[N].toolResult
    "token"       → append to message.content
    "action"      → push to message.actions
    "done"        → set streaming=false
    "error"       → show toast, mark message failed
```

---

## 10. Implementation Steps (ordered)

### Phase 1 — Tool Registry (backend, ~2h)
1. `app/tools/schemas.py` — `Tool`, `ToolResult` dataclasses
2. `app/tools/registry.py` — `ToolRegistry` class with `register`, `get`, `subset`, `call`
3. `app/tools/implementations/hf_tools.py` — wrap existing HF modules as `Tool` instances
4. `app/tools/implementations/db_tools.py` — `get_proficiency`, `get_topic_graph`, `save_quiz`, `save_progress`, `get_due_topics`
5. `app/tools/implementations/logic_tools.py` — `calculate_elo`, `check_guardrail`
6. `app/tools/__init__.py` — create global `registry` singleton, register all 13 tools

### Phase 2 — Base Agent + ReAct Loop (backend, ~3h)
7. `app/agents_v2/base.py` — `BaseAgent` with `decide_step()`, `stream_answer()`, `run()` async generator
8. Unit test: mock registry + mock Qwen → verify event sequence emitted

### Phase 3 — Specialist Agents (backend, ~2h)
9. `app/agents_v2/curriculum_agent.py`
10. `app/agents_v2/quiz_agent.py`
11. `app/agents_v2/progress_agent.py`
12. `app/agents_v2/doubt_agent.py`
13. `app/agents_v2/assistant_agent.py`

### Phase 4 — Router + SSE Endpoint (backend, ~2h)
14. `app/agents_v2/router.py` — `AgentRouter`
15. `app/routers/v2/chat.py` — SSE endpoint, auth, context building
16. Register router in `app/main.py` at `/api/v2/...`
17. Backend integration test: mock HF calls, verify full event stream

### Phase 5 — Frontend (frontend, ~3h)
18. `src/lib/api.ts` — add `assistantV2API.streamChat()` with typed event parsing
19. `src/components/agents/ToolCallCard.tsx`
20. `src/components/agents/StreamTrace.tsx`
21. `src/pages/AtelierV2Page.tsx` — full page with stream state machine
22. `src/App.tsx` — add route `/assistant-v2`
23. `src/components/layout/Sidebar.tsx` — add nav link

---

## 11. Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| Non-streaming think step, streaming final answer | ReAct requires structured JSON for action parsing; streaming JSON mid-token is fragile. Final answers are long and benefit from streaming. |
| Per-agent tool whitelist (not just capability registry) | Prevents quiz agent from accidentally calling `save_progress`; makes agents auditable and testable in isolation. |
| Rule-based router first | Avoids burning a Qwen call (300-500ms) for every message on obvious keyword matches. LLM routing only for ambiguous queries. |
| Specialist agents over one general agent | Smaller tool sets per agent = shorter system prompts = faster, more accurate decisions. Assistant agent is the escape hatch. |
| `side_effects` field in final answer JSON | Agents declare structured actions (quiz_created, progress_updated) as data, not as ad-hoc text parsing. Frontend renders action cards from this. |
| `feat/tool-agents` branch | `main` stays stable. New architecture developed and tested independently. |

---

## 12. What Changes vs. What Stays

| Layer | Status |
|---|---|
| `app/agents/` (LangGraph orchestrator) | **Unchanged** — still powers `/api/v1/session` |
| `app/hf/` (HF modules) | **Unchanged** — tools wrap them, don't replace them |
| `app/routers/` (all existing routes) | **Unchanged** |
| Frontend existing pages | **Unchanged** — new page added at `/assistant-v2` |
| Tests for agents, integration, e2e | **Unchanged** — new tests added alongside |

The v2 architecture lives entirely in `app/tools/`, `app/agents_v2/`, `app/routers/v2/`, and frontend `AtelierV2Page`. Zero risk to production.
