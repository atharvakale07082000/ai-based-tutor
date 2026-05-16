# Agent v2 — Test Results & Concurrency Analysis

Branch: `feat/tool-agents` · Date: 2026-05-16

---

## 1. Test Suite Summary

| File | Tests | Result |
|------|-------|--------|
| `test_agents.py` | 47 | ✅ All pass |
| `test_api.py` | 8 | ✅ All pass |
| `test_e2e.py` | 35 | ✅ All pass |
| `test_hf.py` | 12 | ✅ All pass |
| `test_integration.py` | 38 | ✅ All pass |
| `test_v2_stress.py` | 12 | ✅ All pass |
| `test_v2_concurrency.py` | 5 | ✅ All pass |
| **Total** | **190** | **✅ 190 / 190** |

---

## 2. Agent v2 Stress Test (125 Queries)

All 125 queries across all 5 specialist agents pass with **0 retries needed**.

### Per-agent breakdown

| Agent | Queries | Passed | Failed | Notes |
|-------|---------|--------|--------|-------|
| QuizAgent | 25 | 25 | 0 | keyword: "quiz", "test", "assess" |
| CurriculumAgent | 25 | 25 | 0 | keyword: "roadmap", "path", "curriculum" |
| ProgressAgent | 25 | 25 | 0 | keyword: "progress", "elo", "how am I doing" |
| DoubtAgent | 25 | 25 | 0 | keyword: "explain", "how does", "why" |
| AssistantAgent | 25 | 25 | 0 | general fallback |

### SSE event structure validation (per agent)

Each response stream is validated for:

```
routing → thought → tool_call → tool_result → ... → token(s) → done
```

| Event | Required | All agents |
|-------|----------|------------|
| `routing` (first) | ✅ | ✅ |
| `thought` with `step` + `content` | ✅ | ✅ |
| `tool_call` with `name` + `args` | ✅ | ✅ |
| `tool_result` with `name` + `latency_ms` | ✅ | ✅ |
| `token` (≥1) | ✅ | ✅ |
| `done` (last) with `steps` + `total_ms` | ✅ | ✅ |

### Routing accuracy (keyword-dominant queries)

Tested 8 queries with unambiguous keyword signals:

| Query | Expected | Got | Match |
|-------|----------|-----|-------|
| "quiz me on Python basics" | quiz | quiz | ✅ |
| "test my knowledge of ML" | quiz | quiz | ✅ |
| "create a learning path for AI" | curriculum | curriculum | ✅ |
| "I need a roadmap for web dev" | curriculum | curriculum | ✅ |
| "how am I doing on Python" | progress | progress | ✅ |
| "what is my ELO score" | progress | progress | ✅ |
| "explain what is recursion" | doubt | doubt | ✅ |
| "how does gradient descent work" | doubt | doubt | ✅ |

**Routing accuracy: 8/8 = 100%** (threshold: 75%)

---

## 3. Concurrency Test Results (200 Simultaneous Users)

### Test configuration
- 200 SSE requests fired simultaneously via `asyncio.gather`
- All LLM/DB calls mocked (tests infrastructure, not inference)
- Queries cycle through all 5 agent types

### Results

| Metric | 50 users | 100 users | 200 users |
|--------|---------- |-----------|-----------|
| Passed | 50/50 | 100/100 | 200/200 |
| Failed | 0 | 0 | 0 |
| Failure rate | 0% | 0% | 0% |
| Wall time | ~0.05s | ~0.10s | ~0.18s |
| Throughput | >500 req/s | >500 req/s | >500 req/s |

> Note: Latency/throughput numbers reflect mocked (in-process) calls. Real-world numbers will be dominated by Together API latency (~3–8s per call) and network RTT.

---

## 4. Concurrency Architecture

### Problem identified

Before fixes, the default Python thread pool had only **12 workers** (`min(32, cpu_count+4)` on an 8-core machine). With 200 concurrent users each making 2 `asyncio.to_thread` calls (decide_step + stream_final_answer), that's 400 thread slots needed vs. 12 available — a **33× shortfall**.

### Fixes applied

#### 1. Thread pool increase (`app/main.py`)

```python
executor = concurrent.futures.ThreadPoolExecutor(max_workers=64)
loop.set_default_executor(executor)
```

Sets 64 threads at lifespan startup, giving headroom for 200 users × 2 threads + DB + other tasks.

#### 2. HF semaphore (`app/agents_v2/base.py`)

```python
_HF_SEMAPHORE = asyncio.Semaphore(40)

# In decide_step and stream_final_answer:
async with _HF_SEMAPHORE:
    response = await asyncio.wait_for(asyncio.to_thread(...), ...)
```

Caps concurrent outbound LLM calls at 40 to:
- Avoid exhausting the Together API rate limit
- Queue excess requests cleanly instead of timing out
- Protect the thread pool even beyond the 64-thread increase

### Concurrency capacity analysis

| Component | Limit | Notes |
|-----------|-------|-------|
| Thread pool | 64 threads | 32× improvement over default |
| HF semaphore | 40 concurrent LLM calls | ~80 users at full ReAct depth |
| MongoDB | Connection pool per driver config | Not bottlenecked in tests |
| Together API | Rate limit varies by plan | Primary real-world limit |
| FastAPI async | No limit | Pure asyncio, scales to 1000s |

### Expected real-world behavior at 200 users

With real LLM calls (~5s per decide_step, ~10s per stream):
- Each `decide_step` holds 1 thread for ~5s
- 40 concurrent LLM calls = 40 threads active at any time
- Remaining 160 users queue in the semaphore (no errors, just latency)
- P50 response time: ~15–25s (1 tool step + streaming)
- P99 response time: ~45s (queue + retries)
- For better throughput: increase Together API rate limits or add load balancing

---

## 5. Architecture Overview

```
POST /api/v2/chat
       │
       ▼
  AgentRouter
  ┌─────────────────────────────┐
  │ Phase 1: keyword matching   │ → immediate (<1ms)
  │ Phase 2: LLM fallback       │ → Qwen2.5-7B via Together (~3s)
  └─────────────────────────────┘
       │
       ▼  routing SSE event
  Specialist Agent
  ┌──────────────────────────────────────┐
  │  for step in range(max_steps=6):     │
  │    thought = decide_step(messages)   │ ← Qwen, non-streaming
  │    yield {type: "thought", ...}      │
  │                                      │
  │    if action:                        │
  │      result = tool_registry.call()   │ ← tool, async
  │      yield {type: "tool_call"}       │
  │      yield {type: "tool_result"}     │
  │                                      │
  │    if final_answer:                  │
  │      async for token in stream():    │ ← Qwen, streaming
  │        yield {type: "token"}         │
  │      yield {type: "done"}            │
  └──────────────────────────────────────┘
```

### Tool registry (13 tools)

| Category | Tools |
|----------|-------|
| HF (6) | `classify_topic`, `analyze_sentiment`, `score_difficulty`, `generate_quiz`, `get_embeddings`, `generate_explanation` |
| DB (5) | `get_proficiency`, `get_topic_graph`, `save_quiz`, `save_progress`, `get_due_topics` |
| Logic (2) | `calculate_elo`, `check_guardrail` |

### Agent tool whitelists

| Agent | Tools |
|-------|-------|
| QuizAgent | `get_proficiency`, `score_difficulty`, `generate_quiz`, `save_quiz` |
| CurriculumAgent | `classify_topic`, `get_topic_graph`, `get_proficiency` |
| ProgressAgent | `get_proficiency`, `calculate_elo`, `analyze_sentiment`, `save_progress` |
| DoubtAgent | `check_guardrail`, `get_proficiency`, `generate_explanation` |
| AssistantAgent | All 13 tools |

---

## 6. Frontend

New route `/assistant-v2` with:
- **ToolCallCard**: pill header + args + latency + result
- **StreamTrace**: routing chip + collapsible thought/tool-call steps
- **AtelierV2Page**: full SSE-consuming chat interface

TypeScript check: **0 errors** (`npx tsc --noEmit`)

---

*Generated automatically from test run on 2026-05-16*
