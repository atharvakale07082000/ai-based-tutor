# Interview Probe Turns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the interview agent press a candidate on their own claims, and grade whether they defended, extended or abandoned them — so a pasted answer collapses under questioning and an honest learner gets depth feedback.

**Architecture:** A second interrupt tool (`probe_candidate`) reuses the existing Strands interrupt/resume loop wholesale — a probe is a turn like any other, tagged `kind: "probe"`. The agent decides *whether* to probe (prompt guidance); a new tuned YAML rubric decides *how well the probe was answered*, preserving the existing split where the agent never assigns scores. The resulting `defensibility` value is reported beside `final_score`, never subtracted from it.

**Tech Stack:** Python 3.12 · FastAPI · Strands Agents SDK on NVIDIA NIM · MongoDB (Motor) · pytest · React 18 + TypeScript + Vite

**Spec:** `docs/superpowers/specs/2026-08-23-interview-probe-turns-design.md`

## Global Constraints

- Run pytest from `backend/`, never the repo root — root invocation fails collection.
- Use `uv`, not pip. Run the server as `app.main:socket_app`, not `app.main:app`.
- In tests, patch at the **agent-module level** (`app.agents.interview_agent`), not the tools module.
- LLM prompts live in `backend/app/prompts/*.yaml`. Sections rendered via `render_prompt` run `str.format_map`: double any literal JSON braces `{{ }}`, and never add a `{placeholder}` the caller doesn't pass.
- Prompt house style: `## Role` / `## Task` / `## Guidelines` / `## Output format` headers, XML tags for data inputs, the graded person is the **"candidate"** in interview prompts.
- Parse LLM JSON with `app.agents.json_utils.extract_json` — never `re.search(r"\{.*\}")` + `json.loads`.
- Pass thresholds come from `app/agents/bar.py`. Never write a bare `6.0`.
- The agent never assigns a numeric score. Rubrics own grading.
- Frontend lint is `--max-warnings 0`. Every change must keep `npm run build` green.

---

### Task 1: `probe_candidate` tool and the interrupt hook

**Files:**
- Modify: `backend/app/agents/interview_agent.py`
- Test: `backend/tests/test_interview_probes.py` (create)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `probe_candidate` tool; module constant `_INTERRUPT_NAMES: frozenset[str]` replacing `_INTERRUPT_NAME`; `_PROBE_NAME: str = "probe_candidate"`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_interview_probes.py`:

```python
"""Tests for probe turns — the interview agent pressing a candidate on their own claims."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import app.agents.interview_agent as ia


class _FakeInterrupt:
    def __init__(self, id: str, reason: dict, name: str = "ask_candidate") -> None:
        self.id = id
        self.reason = reason
        self.name = name


class _FakeResult:
    def __init__(self, interrupts=None) -> None:
        self.interrupts = interrupts
        self.stop_reason = "interrupt"


class _FakeAgent:
    def __init__(self, events: list) -> None:
        self._events = events

    async def stream_async(self, prompt=None):
        for ev in self._events:
            yield ev


def _mock_col(monkeypatch) -> MagicMock:
    col = MagicMock()
    col.update_one = AsyncMock()
    monkeypatch.setattr(ia, "col_interviews", lambda: col)
    return col


def _interview(**over) -> dict:
    base = {
        "interview_id": "iv-1",
        "module_title": "SQL Joins",
        "module_topics": ["joins"],
        "candidate_proficiency": {},
        "turn_count": 1,
        "current_interrupt_id": None,
        "questions": [{"id": 1, "text": "Explain an INNER JOIN.", "kind": "question"}],
        "answers": [],
    }
    base.update(over)
    return base


def test_probe_tool_exists_and_is_an_interrupt():
    """Both tools must pause the agent; only the name distinguishes them."""
    assert ia._PROBE_NAME == "probe_candidate"
    assert ia._PROBE_NAME in ia._INTERRUPT_NAMES
    assert "ask_candidate" in ia._INTERRUPT_NAMES


def test_hook_pauses_on_either_tool():
    """The hook matched one hardcoded name; it must now match the set."""
    hook = ia.InterviewInterruptHook()
    seen = []

    class _Ev:
        def __init__(self, name):
            self.tool_use = {"name": name}
            self.cancel_tool = None

        def interrupt(self, name, reason=None):
            seen.append(name)
            return {"answer": "x"}

    for name in ("ask_candidate", "probe_candidate"):
        hook._pause_for_answer(_Ev(name))
    assert seen == ["ask_candidate", "probe_candidate"]


def test_hook_ignores_other_tools():
    hook = ia.InterviewInterruptHook()

    class _Ev:
        def __init__(self):
            self.tool_use = {"name": "conclude"}
            self.cancel_tool = None

        def interrupt(self, name, reason=None):
            raise AssertionError("conclude must not interrupt")

    hook._pause_for_answer(_Ev())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: FAIL with `AttributeError: module 'app.agents.interview_agent' has no attribute '_PROBE_NAME'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/agents/interview_agent.py`, replace the `_INTERRUPT_NAME` constant near the top:

```python
_INTERRUPT_NAME = "ask_candidate"
_PROBE_NAME = "probe_candidate"
# Both tools pause the run the same way; only the stored `kind` distinguishes the turns.
_INTERRUPT_NAMES = frozenset({_INTERRUPT_NAME, _PROBE_NAME})
```

Add the tool beside `ask_candidate`:

```python
@tool
def probe_candidate(question: str, targets: str = "") -> str:
    """Press the candidate on something they just claimed, in their own words.

    Use this when an answer was fluent and complete but gave no sign the candidate owns
    the material — no specifics, no trade-offs, no experience behind it. Ask them to go
    one level deeper into a claim THEY made. Someone who understands it will extend it;
    someone reciting will not.

    Args:
        question: The follow-up, quoting their own words where you can.
        targets: The specific claim you are testing. Internal — never shown to them.
    """
    return "Probe delivered."
```

Change the hook's guard:

```python
    def _pause_for_answer(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use.get("name")
        if name not in _INTERRUPT_NAMES:
            return
        question_payload = event.tool_use.get("input") or {}
        response = event.interrupt(name, reason=question_payload)
        event.cancel_tool = _format_answer(response)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/interview_agent.py backend/tests/test_interview_probes.py
git commit -m "feat(interview): add probe_candidate as a second interrupt tool"
```

---

### Task 2: Probe budget and conditional tool registration

**Files:**
- Modify: `backend/app/config.py`, `backend/.env.sample`, `backend/app/agents/interview_agent.py`
- Test: `backend/tests/test_interview_probes.py`

**Interfaces:**
- Consumes: `_PROBE_NAME`, `probe_candidate` (Task 1)
- Produces: `settings.INTERVIEW_MAX_PROBES: int`; `_probe_count(interview: dict) -> int`; `_may_probe(interview: dict) -> bool`; `build_interview_agent` omits `probe_candidate` when the budget is spent

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_interview_probes.py`:

```python
def test_probe_count_counts_only_probe_questions():
    iv = _interview(questions=[
        {"id": 1, "kind": "question"},
        {"id": 2, "kind": "probe", "probes_of": 1},
        {"id": 3, "kind": "probe", "probes_of": 1},
    ])
    assert ia._probe_count(iv) == 2


def test_legacy_questions_without_kind_are_not_probes():
    """Interviews created before this feature have no `kind` field at all."""
    iv = _interview(questions=[{"id": 1, "text": "Q"}, {"id": 2, "text": "Q2"}])
    assert ia._probe_count(iv) == 0


def test_may_probe_is_false_once_the_cap_is_reached(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "INTERVIEW_MAX_PROBES", 2)
    assert ia._may_probe(_interview(questions=[{"id": 1, "kind": "question"}])) is True
    spent = _interview(questions=[
        {"id": 1, "kind": "question"},
        {"id": 2, "kind": "probe", "probes_of": 1},
        {"id": 3, "kind": "probe", "probes_of": 1},
    ])
    assert ia._may_probe(spent) is False


def test_may_probe_is_false_when_the_last_question_was_already_probed():
    """One probe per question — pressing the same answer twice is badgering."""
    iv = _interview(questions=[
        {"id": 1, "kind": "question"},
        {"id": 2, "kind": "probe", "probes_of": 1},
    ])
    assert ia._may_probe(iv) is False


def test_agent_does_not_get_the_probe_tool_when_the_budget_is_spent(monkeypatch):
    """Enforced in code, not prompt text: a model cannot call a tool it does not have."""
    monkeypatch.setattr(ia, "get_nim_model", lambda role: object())
    monkeypatch.setattr(ia, "load_all_skills", lambda names: "")

    captured = {}

    class _Agent:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(ia, "Agent", _Agent)

    ia.build_interview_agent(_interview())
    assert any(getattr(t, "__name__", "") == "probe_candidate" for t in captured["tools"])

    captured.clear()
    ia.build_interview_agent(_interview(questions=[
        {"id": 1, "kind": "question"},
        {"id": 2, "kind": "probe", "probes_of": 1},
    ]))
    assert not any(getattr(t, "__name__", "") == "probe_candidate" for t in captured["tools"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: FAIL with `AttributeError: module 'app.agents.interview_agent' has no attribute '_probe_count'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/config.py`, beside the existing `INTERVIEW_MIN_QUESTIONS` / `INTERVIEW_MAX_QUESTIONS`:

```python
    # Follow-ups the agent may raise per interview. Probes live in their own budget so a
    # probed interview still asks the same number of real questions.
    INTERVIEW_MAX_PROBES: int = 3
```

In `backend/.env.sample`, beside the other `INTERVIEW_` entries (the file is a verified 1:1 mirror of `config.py`):

```
INTERVIEW_MAX_PROBES=3
```

In `backend/app/agents/interview_agent.py`, beside `_max_questions` / `_min_questions`:

```python
def _probe_count(interview: dict) -> int:
    """How many probes this interview has already raised."""
    return sum(
        1 for q in (interview.get("questions") or []) if q.get("kind") == "probe"
    )


def _may_probe(interview: dict) -> bool:
    """Whether a probe is allowed right now.

    Two caps, both enforced here rather than in prompt text — a model that ignored its
    budget could otherwise run an interview indefinitely. The per-question cap also stops
    the agent pressing the same answer repeatedly, which reads as badgering.
    """
    questions = interview.get("questions") or []
    if not questions:
        return False
    if _probe_count(interview) >= settings.INTERVIEW_MAX_PROBES:
        return False
    return questions[-1].get("kind") != "probe"
```

In `build_interview_agent`, make the toolset conditional:

```python
    tools = [ask_candidate, conclude]
    if _may_probe(interview):
        tools.insert(1, probe_candidate)
    return Agent(
        name="InterviewAgent",
        model=get_nim_model("specialist"),
        system_prompt=_system_prompt(interview),
        tools=tools,
        ...
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/.env.sample backend/app/agents/interview_agent.py backend/tests/test_interview_probes.py
git commit -m "feat(interview): probe budget, enforced by withholding the tool"
```

---

### Task 3: `_drive` persists a probe turn without spending a question

**Files:**
- Modify: `backend/app/agents/interview_agent.py`
- Test: `backend/tests/test_interview_probes.py`

**Interfaces:**
- Consumes: `_PROBE_NAME`, `_probe_count` (Tasks 1-2)
- Produces: `question` wire events carrying `kind` and, for probes, `probes_of`; stored question rows with `kind` / `probes_of` / `targets`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_interview_probes.py`:

```python
async def test_probe_interrupt_emits_a_probe_question_without_spending_a_turn(monkeypatch):
    col = _mock_col(monkeypatch)
    interview = _interview(turn_count=1)
    interrupt = _FakeInterrupt(
        "int-2",
        {"question": "You said joins are cheap — when are they not?", "targets": "their claim that joins are cheap"},
        name="probe_candidate",
    )
    agent = _FakeAgent([{"result": _FakeResult([interrupt])}])

    out = [w async for w in ia._drive(agent, "go", interview)]
    q = next(w for w in out if w["type"] == "question")

    assert q["kind"] == "probe"
    assert q["probes_of"] == 1
    # A probe is not a new question: the budget counter must not move.
    assert interview["turn_count"] == 1
    # ...but the interview is now awaiting an answer to it.
    assert interview["current_interrupt_id"] == "int-2"
    pushed = col.update_one.await_args.args[1]["$push"]["questions"]
    assert pushed["kind"] == "probe"
    assert pushed["targets"] == "their claim that joins are cheap"


async def test_targets_never_reach_the_wire(monkeypatch):
    """`targets` is the agent's internal reason for probing, not something to show."""
    _mock_col(monkeypatch)
    interrupt = _FakeInterrupt(
        "int-2", {"question": "Why?", "targets": "secret"}, name="probe_candidate"
    )
    out = [w async for w in ia._drive(_FakeAgent([{"result": _FakeResult([interrupt])}]), "go", _interview())]
    q = next(w for w in out if w["type"] == "question")
    assert "targets" not in q


async def test_a_normal_question_still_increments_turn_count(monkeypatch):
    """Regression guard: the existing path is unchanged."""
    _mock_col(monkeypatch)
    interview = _interview(turn_count=1)
    interrupt = _FakeInterrupt("int-2", {"question": "Next one."}, name="ask_candidate")
    out = [w async for w in ia._drive(_FakeAgent([{"result": _FakeResult([interrupt])}]), "go", interview)]
    q = next(w for w in out if w["type"] == "question")
    assert q["kind"] == "question"
    assert interview["turn_count"] == 2


async def test_a_blank_probe_is_rejected_like_a_blank_question(monkeypatch):
    col = _mock_col(monkeypatch)
    interrupt = _FakeInterrupt("int-2", {"question": "   "}, name="probe_candidate")
    out = [w async for w in ia._drive(_FakeAgent([{"result": _FakeResult([interrupt])}]), "go", _interview())]
    assert [w["type"] for w in out] == ["error"]
    assert col.update_one.await_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: FAIL — `KeyError: 'kind'` on the emitted question

- [ ] **Step 3: Write minimal implementation**

In `_drive`, inside the `if interrupts and not force_finish:` branch, after the existing blank-question guard, replace the id/question construction:

```python
        # Which tool paused us decides whether this costs a question. Strands exposes the
        # tool name on the interrupt; fall back to a normal question if it is absent.
        is_probe = getattr(interrupts[0], "name", _INTERRUPT_NAME) == _PROBE_NAME
        prior = interview.get("questions") or []
        next_id = max((q.get("id", 0) for q in prior), default=0) + 1

        question = {
            "id": next_id,
            "text": question_text,
            "is_coding_question": bool(payload.get("is_coding")),
            "language": (payload.get("language") or None),
            "expected_depth": payload.get("expected_depth") or "conceptual",
            "kind": "probe" if is_probe else "question",
        }
        if is_probe:
            # The question this presses, and why — the latter stays server-side.
            question["probes_of"] = next(
                (q["id"] for q in reversed(prior) if q.get("kind") != "probe"), None
            )
            question["targets"] = str(payload.get("targets", "") or "")

        set_fields = {
            "current_interrupt_id": interrupts[0].id,
            "status": "in_progress",
        }
        if not is_probe:
            # A probe is not a new question, so it must not consume the budget.
            set_fields["turn_count"] = next_id
            interview["turn_count"] = next_id

        await col_interviews().update_one(
            {"interview_id": interview_id},
            {"$push": {"questions": question}, "$set": set_fields},
        )
        interview["questions"] = [*prior, question]
        interview["current_interrupt_id"] = interrupts[0].id
```

Then emit without the internal field:

```python
        yield {
            "type": "question",
            **{k: v for k, v in question.items() if k != "targets"},
            "max_questions": _max_questions(interview),
        }
```

> Note: `next_id` now derives from the stored questions rather than `turn_count`, because
> probes append rows without moving `turn_count`. For a probe-free interview the two are
> identical, so existing behaviour is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_interview_probes.py tests/test_interview_agent.py -v`
Expected: all pass — including the pre-existing `test_stream_start_asks_first_question` and `test_hard_cap_forces_finish`

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/interview_agent.py backend/tests/test_interview_probes.py
git commit -m "feat(interview): persist probe turns without spending the question budget"
```

---

### Task 4: The `probe_defensibility` rubric and `evaluate_probe`

**Files:**
- Modify: `backend/app/prompts/interview_scorer.yaml`, `backend/app/agents/course_planner.py`
- Test: `backend/tests/test_interview_probes.py`

**Interfaces:**
- Consumes: stored probe rows from Task 3
- Produces: `course_planner.evaluate_probe(interview_id: str, question_id: int, answer_text: str) -> dict` returning `{"question_id": int, "answer_text": str, "kind": "probe", "verdict": str, "note": str}`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_interview_probes.py`:

```python
import pytest

import app.agents.course_planner as cp


async def test_evaluate_probe_grades_defensibility_only(monkeypatch):
    """One axis: did they defend their own claim? Never a re-grade of correctness."""
    stored = {
        "interview_id": "iv-1",
        "module_title": "SQL",
        "context": {},
        "questions": [
            {"id": 1, "text": "Explain joins.", "kind": "question"},
            {"id": 2, "text": "When are they not cheap?", "kind": "probe",
             "probes_of": 1, "targets": "their claim that joins are cheap"},
        ],
    }
    col = MagicMock()
    col.find_one = AsyncMock(return_value=stored)
    col.update_one = AsyncMock()
    monkeypatch.setattr(cp, "col_interviews", lambda: col)
    monkeypatch.setattr(
        cp, "_chat",
        lambda *a, **k: '{"verdict": "defended", "note": "Named the hash-join spill case."}',
    )

    got = await cp.evaluate_probe("iv-1", 2, "When the build side spills to disk.")

    assert got["verdict"] == "defended"
    assert got["kind"] == "probe"
    assert got["question_id"] == 2
    assert got["answer_text"] == "When the build side spills to disk."
    assert "score" not in got, "a probe must not produce a numeric score"


@pytest.mark.parametrize("raw", ["not json at all", '{"verdict": "nonsense"}', "{}"])
async def test_an_unparseable_or_invalid_verdict_falls_back_to_partial(monkeypatch, raw):
    """Never fail the candidate because the grader misbehaved."""
    stored = {
        "interview_id": "iv-1", "module_title": "SQL", "context": {},
        "questions": [{"id": 2, "text": "Why?", "kind": "probe", "probes_of": 1}],
    }
    col = MagicMock()
    col.find_one = AsyncMock(return_value=stored)
    col.update_one = AsyncMock()
    monkeypatch.setattr(cp, "col_interviews", lambda: col)
    monkeypatch.setattr(cp, "_chat", lambda *a, **k: raw)

    got = await cp.evaluate_probe("iv-1", 2, "some answer")
    assert got["verdict"] == "partial"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: FAIL with `AttributeError: module 'app.agents.course_planner' has no attribute 'evaluate_probe'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/prompts/interview_scorer.yaml` (note the doubled braces in the JSON block — this section is rendered via `render_prompt`):

```yaml
probe_defensibility: |
  ## Role

  You are an interview assessor for Atelier, an AI tutoring platform. The candidate gave an
  answer, and the interviewer pressed them on one specific claim inside it. You judge only
  what that follow-up revealed.

  ## Task

  Decide whether the candidate defended the claim they themselves made.

  <original_claim>{targets}</original_claim>
  <follow_up_question>{question_text}</follow_up_question>
  <candidate_response>{answer_text}</candidate_response>

  ## Guidelines

  - You are NOT re-grading correctness. The original answer already has a score.
  - `defended` — they went deeper on their own terms: a concrete mechanism, a named
    trade-off, a real example, a boundary condition. Brevity is fine; ownership is the test.
  - `partial` — they restated the original claim in different words, or answered a nearby
    question instead of the one asked, or hedged without adding anything.
  - `abandoned` — they contradicted their own claim, said they did not know, or produced
    fluent text that contains no information about the specific thing asked.
  - Confident, fluent prose that never touches the specific claim is `abandoned`, not
    `partial`. Fluency is not evidence.
  - Judge only the response. Never speculate about how the candidate produced their answer,
    and never mention cheating, AI, or dishonesty in the note.

  ## Output format

  Return ONLY this JSON object:

  {{"verdict": "defended | partial | abandoned", "note": "<one sentence, addressed to the candidate>"}}
```

Add to `backend/app/agents/course_planner.py`, directly after `evaluate_answer`:

```python
_PROBE_VERDICTS = frozenset({"defended", "partial", "abandoned"})


async def evaluate_probe(
    interview_id: str, question_id: int, answer_text: str
) -> dict:
    """Grade a follow-up on one axis: did the candidate defend their own claim?

    Deliberately produces no numeric score. The original answer already carries one, and
    the whole point of a probe is that it tests ownership rather than correctness.
    """
    interview = await col_interviews().find_one({"interview_id": interview_id})
    if not interview:
        raise ValueError("Interview not found")

    question = next((q for q in interview["questions"] if q["id"] == question_id), None)
    if not question:
        raise ValueError("Question not found")

    prompt = render_prompt(
        "interview_scorer",
        "probe_defensibility",
        targets=question.get("targets", "") or "the claim in their previous answer",
        question_text=question["text"],
        answer_text=answer_text,
    )

    t0 = time.perf_counter()
    text = await asyncio.to_thread(_chat, prompt, 200, 0.1)
    parsed = extract_json(text) or {}

    verdict = str(parsed.get("verdict", "")).strip().lower()
    if verdict not in _PROBE_VERDICTS:
        # A grader that returns nothing usable must not decide against the candidate.
        verdict = "partial"

    result = {
        "question_id": question_id,
        "answer_text": answer_text,
        "kind": "probe",
        "verdict": verdict,
        "note": str(parsed.get("note", "") or ""),
    }
    log.info(
        "probe_evaluated",
        interview_id=interview_id,
        q_id=question_id,
        verdict=verdict,
        latency_ms=round((time.perf_counter() - t0) * 1000),
    )

    await col_interviews().update_one(
        {"interview_id": interview_id},
        {"$push": {"answers": result}},
    )
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts/interview_scorer.yaml backend/app/agents/course_planner.py backend/tests/test_interview_probes.py
git commit -m "feat(interview): probe_defensibility rubric and evaluate_probe"
```

---

### Task 5: Route a probe's answer through the probe rubric

**Files:**
- Modify: `backend/app/agents/interview_agent.py` (`stream_answer`)
- Test: `backend/tests/test_interview_probes.py`

**Interfaces:**
- Consumes: `evaluate_probe` (Task 4), probe rows (Task 3)
- Produces: a `probe_result` wire event `{"type": "probe_result", "question_id": int, "verdict": str, "note": str}`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_interview_probes.py`:

```python
async def test_answering_a_probe_uses_the_probe_rubric(monkeypatch):
    _mock_col(monkeypatch)
    interview = _interview(
        questions=[
            {"id": 1, "text": "Explain joins.", "kind": "question"},
            {"id": 2, "text": "When are they not cheap?", "kind": "probe", "probes_of": 1},
        ],
        current_interrupt_id="int-2",
        turn_count=1,
    )

    called = {}

    async def _fake_probe(iid, qid, text):
        called["probe"] = (iid, qid, text)
        return {"question_id": qid, "kind": "probe", "verdict": "defended", "note": "Good."}

    async def _fake_answer(*a, **k):
        raise AssertionError("a probe must not go through evaluate_answer")

    monkeypatch.setattr("app.agents.course_planner.evaluate_probe", _fake_probe)
    monkeypatch.setattr("app.agents.course_planner.evaluate_answer", _fake_answer)
    monkeypatch.setattr(ia, "build_interview_agent", lambda iv: _FakeAgent([{"result": _FakeResult(None)}]))

    out = [w async for w in ia.stream_answer(interview, 2, "Because the build side spills.")]

    assert called["probe"] == ("iv-1", 2, "Because the build side spills.")
    ev = next(w for w in out if w["type"] == "probe_result")
    assert ev["verdict"] == "defended"
    assert not any(w["type"] == "evaluation" for w in out), "a probe yields no score event"


async def test_answering_a_normal_question_still_uses_evaluate_answer(monkeypatch):
    """Regression guard for the untouched path."""
    _mock_col(monkeypatch)
    interview = _interview(current_interrupt_id="int-1", turn_count=1)

    async def _fake_answer(iid, qid, text):
        return {"question_id": qid, "score": 8, "feedback": "Good", "key_points_covered": []}

    monkeypatch.setattr("app.agents.course_planner.evaluate_answer", _fake_answer)
    monkeypatch.setattr(ia, "build_interview_agent", lambda iv: _FakeAgent([{"result": _FakeResult(None)}]))

    out = [w async for w in ia.stream_answer(interview, 1, "An inner join keeps matches.")]
    assert next(w for w in out if w["type"] == "evaluation")["score"] == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: FAIL — `AssertionError: a probe must not go through evaluate_answer`

- [ ] **Step 3: Write minimal implementation**

At the top of `stream_answer`, replace the scoring block:

```python
async def stream_answer(
    interview: dict, question_id: int, answer_text: str
) -> AsyncIterator[dict]:
    """Score the submitted answer, then resume the agent for its next move."""
    from app.agents.course_planner import evaluate_answer, evaluate_probe

    interview_id = interview["interview_id"]
    question = next(
        (q for q in (interview.get("questions") or []) if q.get("id") == question_id),
        None,
    )
    is_probe = bool(question and question.get("kind") == "probe")

    # 1) Grade it. A probe is judged on defensibility only and carries no score, so the
    #    final grade keeps being computed from the real questions alone.
    try:
        if is_probe:
            evaluation = await evaluate_probe(interview_id, question_id, answer_text)
        else:
            evaluation = await evaluate_answer(interview_id, question_id, answer_text)
    except Exception as e:  # noqa: BLE001
        log.error(
            "interview_evaluate_failed", interview_id=interview_id, error=str(e)[:200]
        )
        yield {"type": "error", "message": "Could not score that answer — try again."}
        return

    interview["answers"] = [*(interview.get("answers") or []), evaluation]

    if is_probe:
        yield {
            "type": "probe_result",
            "question_id": question_id,
            "verdict": evaluation.get("verdict"),
            "note": evaluation.get("note", ""),
        }
    else:
        yield {
            "type": "evaluation",
            "question_id": question_id,
            "score": evaluation.get("score"),
            "feedback": evaluation.get("feedback", ""),
            "key_points_covered": evaluation.get("key_points_covered", []),
            "answered_count": sum(
                1 for a in interview["answers"] if a.get("kind") != "probe"
            ),
            "max_questions": _max_questions(interview),
        }
```

Leave the rest of `stream_answer` (the resume block) unchanged — the agent is resumed the
same way whichever tool paused it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_interview_probes.py tests/test_interview_agent.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/interview_agent.py backend/tests/test_interview_probes.py
git commit -m "feat(interview): route probe answers to the defensibility rubric"
```

---

### Task 6: Defensibility in the final review, excluded from scoring

**Files:**
- Modify: `backend/app/agents/pipelines/interview_review.py`, `backend/app/agents/course_planner.py` (`interview_state`)
- Test: `backend/tests/test_interview_probes.py`

**Interfaces:**
- Consumes: probe answer rows (Task 5)
- Produces: `interview_review.defensibility_of(answers: list[dict]) -> float | None`; persisted `interview["defensibility"]`; `interview_state()["defensibility"]`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_interview_probes.py`:

```python
from app.agents.pipelines.interview_review import defensibility_of


def test_defensibility_is_none_without_probes():
    assert defensibility_of([{"question_id": 1, "score": 7}]) is None


def test_defensibility_averages_probe_verdicts():
    answers = [
        {"question_id": 1, "score": 7},
        {"question_id": 2, "kind": "probe", "verdict": "defended"},
        {"question_id": 3, "kind": "probe", "verdict": "abandoned"},
    ]
    assert defensibility_of(answers) == 0.5


def test_unknown_verdicts_are_ignored_rather_than_scored_zero():
    answers = [
        {"question_id": 2, "kind": "probe", "verdict": "defended"},
        {"question_id": 3, "kind": "probe", "verdict": "???"},
    ]
    assert defensibility_of(answers) == 1.0


async def test_probe_rows_are_excluded_from_final_scoring(monkeypatch):
    """The grade must keep being computed from the real questions only."""
    import app.agents.pipelines.interview_review as ir

    stored = {
        "interview_id": "iv-1",
        "module_title": "SQL",
        "module_topics": ["joins"],
        "bar": 6.0,
        "context": {},
        "questions": [
            {"id": 1, "text": "Q1", "kind": "question"},
            {"id": 2, "text": "P1", "kind": "probe", "probes_of": 1},
        ],
        "answers": [
            {"question_id": 1, "score": 7, "answer_text": "a1"},
            {"question_id": 2, "kind": "probe", "verdict": "defended", "answer_text": "p1"},
        ],
    }
    col = MagicMock()
    col.find_one = AsyncMock(return_value=stored)
    col.update_one = AsyncMock()
    monkeypatch.setattr("app.db.mongo.col_interviews", lambda: col)

    seen = {}

    def _fake_scoring(title, topics, questions, transcriptions, bar):
        seen["transcriptions"] = transcriptions
        return {"final_score": 7.0, "passed": True, "scoring_matrix": [], "summary": "ok"}

    monkeypatch.setattr("app.agents.interview_scorer.run_scoring_agent", _fake_scoring)
    monkeypatch.setattr(ir, "_update_module_interview", AsyncMock(), raising=False)

    await ir.run_interview_review("iv-1", "plan-1", "mod-1")

    assert [t["question_id"] for t in seen["transcriptions"]] == [1]
    persisted = col.update_one.await_args_list[0].args[1]["$set"]
    assert persisted["defensibility"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: FAIL with `ImportError: cannot import name 'defensibility_of'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/agents/pipelines/interview_review.py`, above `run_interview_review`:

```python
# A probe verdict as a number, for averaging only. This is REPORTED beside the score,
# never subtracted from it — bar.py keeps owning pass/fail, and a figure that silently
# discounted a grade would be exactly the unbacked UI the 2026-08-15 audit removed.
_VERDICT_VALUE = {"defended": 1.0, "partial": 0.5, "abandoned": 0.0}


def defensibility_of(answers: list[dict]) -> float | None:
    """Mean of this interview's probe verdicts, or None when no probe was raised."""
    values = [
        _VERDICT_VALUE[a["verdict"]]
        for a in (answers or [])
        if a.get("kind") == "probe" and a.get("verdict") in _VERDICT_VALUE
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 2)
```

In `run_interview_review`, change the transcription build so probes are excluded, and
persist the new field:

```python
        answers = interview.get("answers", [])
        graded = [a for a in answers if a.get("kind") != "probe"]
        if not graded:
            raise ValueError("No answers submitted")
        transcriptions = [
            {
                "question_id": a.get("question_id"),
                "answer_text": a.get("answer_text", ""),
            }
            for a in graded
        ]
```

and in the `$set` that persists the result:

```python
                    "defensibility": defensibility_of(answers),
```

In `course_planner.interview_state`, add to the returned dict (the candidate may see their
own result; `targets` and the rubric `note` stay internal):

```python
        "defensibility": interview.get("defensibility"),
```

and filter probes out of the projected `answers` list so the transcript the client renders
keeps matching the scored questions:

```python
        "answers": [
            ...
            for a in answers
            if a.get("kind") != "probe"
        ],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest -q`
Expected: full suite green

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/pipelines/interview_review.py backend/app/agents/course_planner.py backend/tests/test_interview_probes.py
git commit -m "feat(interview): report defensibility beside the score, never inside it"
```

---

### Task 7: Teach the agent when to probe

**Files:**
- Modify: `backend/app/agents/interview_agent.py` (`_system_prompt`)
- Test: `backend/tests/test_interview_probes.py`

**Interfaces:**
- Consumes: `_may_probe` (Task 2)
- Produces: probe guidance in the system prompt, present only when a probe is available

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_interview_probes.py`:

```python
def test_probe_guidance_appears_only_when_a_probe_is_available():
    available = ia._system_prompt(_interview())
    assert "probe_candidate" in available
    assert "fluent" in available.lower()

    spent = ia._system_prompt(_interview(questions=[
        {"id": 1, "kind": "question"},
        {"id": 2, "kind": "probe", "probes_of": 1},
    ]))
    assert "probe_candidate" not in spent, (
        "offering a tool the agent does not have wastes tokens and invites a failed call"
    )


def test_probe_guidance_never_frames_probing_as_catching_someone():
    prompt = ia._system_prompt(_interview())
    lowered = prompt.lower()
    for word in ("cheat", "cheating", "dishonest", "plagiar", "caught"):
        assert word not in lowered, f"probe guidance must not frame this as policing: {word}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: FAIL — `assert 'probe_candidate' in available`

- [ ] **Step 3: Write minimal implementation**

In `_system_prompt`, append this block when `_may_probe(interview)` is true:

```python
    probe_guidance = ""
    if _may_probe(interview):
        probe_guidance = (
            "\n\n## Following up\n"
            "You also have `probe_candidate`, which asks ONE follow-up on something the "
            "candidate just claimed, in their own words.\n"
            "- Use it when an answer was fluent, complete and textbook-shaped but gave no "
            "sign they own the material — no specifics, no trade-offs, no experience "
            "behind it, and noticeably stronger than their other answers.\n"
            "- Ask them to go one level into a claim THEY made: a mechanism, a boundary "
            "condition, a case where it stops being true.\n"
            "- Do NOT follow up on a weak answer. That candidate needs teaching, and "
            "pressing them tells you nothing.\n"
            "- Do NOT follow up on an answer already grounded in their own concrete "
            "experience, and never on your final question.\n"
            "- A follow-up does not count against your question budget, but you may raise "
            "very few, so spend them where the answer is strong and unowned.\n"
            "- Put the specific claim you are testing in `targets`. This is for the "
            "assessor and is never shown to the candidate.\n"
            "- Frame it as depth and curiosity, the way a good interviewer digs into a "
            "promising answer. Never suggest you doubt them."
        )
```

and include `probe_guidance` in the returned prompt string, after the existing
question-design guidance.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_interview_probes.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/interview_agent.py backend/tests/test_interview_probes.py
git commit -m "feat(interview): teach the agent when a follow-up is worth spending"
```

---

### Task 8: Frontend — render a follow-up and its result

**Files:**
- Modify: `frontend/src/components/interview/InterviewRunner.tsx`, `frontend/src/lib/api.ts`
- Test: `e2e/interview_flow.py`

**Interfaces:**
- Consumes: `question` events carrying `kind`/`probes_of`, and `probe_result` events (Tasks 3, 5)
- Produces: a "Follow-up" turn in the runner; a defensibility line on the result screen

- [ ] **Step 1: Extend the E2E to assert the probe leg**

In `e2e/interview_flow.py`, inside the `[5] next turn` section after the existing checks:

```python
        # A follow-up, when the agent raises one, must read as depth — never as an accusation.
        body = page.inner_text("body")
        if "Follow-up" in body:
            check("follow-up is framed as depth", True, "probe turn rendered")
            for word in ("cheat", "suspicious", "plagiar", "dishonest"):
                check(f"follow-up copy avoids '{word}'", word not in body.lower())
        else:
            print("        (no probe raised this run — adaptive, not a failure)")
```

- [ ] **Step 2: Run it to see the current behaviour**

Run (with both servers up, from `backend/`):

```bash
E2E_BASE_URL=http://localhost:5173 E2E_EMAIL=admin@test.com E2E_PASSWORD='admin@1234' \
E2E_PLAN_ID=<plan> E2E_MODULE_ID=<module> uv run python ../e2e/interview_flow.py
```

Expected: passes, printing the "no probe raised this run" line — probes are adaptive, so the
harness must not require one.

- [ ] **Step 3: Render the probe turn**

In `frontend/src/lib/api.ts`, extend the interview question type with the additive fields:

```ts
  kind?: 'question' | 'probe'
  probes_of?: number | null
```

and the state type with:

```ts
  defensibility?: number | null
```

In `InterviewRunner.tsx`, in `toQuestion`, carry `kind` and `probes_of` through. Where the
question card renders, add above the question text:

```tsx
{currentQuestion?.kind === 'probe' && (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
    <Badge size="xs" tone="neutral">Follow-up</Badge>
    <span className="t-xs fg-3">On your previous answer</span>
  </div>
)}
```

Handle the new event in `evaluateAnswer`'s stream callback, beside the `evaluation` branch:

```tsx
} else if (event.type === 'probe_result') {
  // A follow-up carries no score — show what it showed, then move on.
  setCurrentEval({
    question_id: Number(event.question_id),
    score: null,
    feedback: String(event.note ?? ''),
    answer_text: answerText,
    key_points_covered: [],
  })
  setPhase('feedback')
}
```

> `score: null` requires widening `AnswerResult.score` to `number | null`; the feedback card
> must render its score chip only when `score != null`.

- [ ] **Step 4: Show defensibility on the result**

Where the final result renders, beside the score:

```tsx
{finalResult?.defensibility != null && (
  <div className="t-sm fg-2" style={{ marginTop: 6 }}>
    {finalResult.defensibility >= 0.75
      ? 'Held up under follow-up'
      : finalResult.defensibility >= 0.4
        ? 'Partially defended under follow-up'
        : "Couldn't extend under follow-up"}
  </div>
)}
```

- [ ] **Step 5: Verify and commit**

```bash
cd frontend && npm run lint && npm run build
```
Expected: both clean.

```bash
git add frontend/src/components/interview/InterviewRunner.tsx frontend/src/lib/api.ts e2e/interview_flow.py
git commit -m "feat(interview): render follow-up turns and defensibility"
```

---

### Task 9: Documentation

**Files:**
- Modify: `.claude/CLAUDE.md`
- Create: `/Users/atharvakale/.claude/projects/-Users-atharvakale-Desktop-Propjects-ai-tutor/memory/feature_probe_turns.md`
- Modify: `/Users/atharvakale/.claude/projects/-Users-atharvakale-Desktop-Propjects-ai-tutor/memory/MEMORY.md`

- [ ] **Step 1: Add the gotcha to CLAUDE.md**

Beside the other interview entries:

```markdown
- **A probe is a turn, not a question.** `probe_candidate` raises the same interrupt as `ask_candidate` (both in `_INTERRUPT_NAMES`) but stores `kind: "probe"` and does NOT increment `turn_count`, so follow-ups never eat the question budget. Budget is enforced by *withholding the tool* in `build_interview_agent` when `_may_probe` is false — a model cannot call a tool it does not have. A probe's answer routes to `course_planner.evaluate_probe` (rubric `interview_scorer.yaml::probe_defensibility`), which returns a verdict and no score; probe rows are excluded from the `transcriptions` `run_interview_review` scores, and `defensibility` is reported beside `final_score`, never subtracted from it. `targets` is internal and must never reach the wire or `interview_state`.
```

- [ ] **Step 2: Write the memory file**

```markdown
---
name: feature_probe_turns
description: "Interview integrity is designed in, not surveilled: the agent probes claims and a rubric grades whether the candidate defended them"
metadata:
  type: project
---

Atelier's pitch is "a rating for what you know", and until 2026-08 nothing defended that
rating — a candidate could paste every answer. Three approaches were weighed (surveillance
signals, visible deterrence, unfakeable assessment); the user chose the third.

**Why:** it is the only one that works against a tool you cannot detect, and it reframes
anti-cheat as a learning feature — "how well does your understanding hold up when pushed?"
is real feedback for an honest learner and the exact thing a pasted answer fails.

**How to apply:** never frame a probe as policing, in prompts or UI. The verdict is
reported beside the score, never subtracted from it. See [[feature_live_interview_agent]]
and [[feedback_dont_ship_unbacked_ui]].
```

- [ ] **Step 3: Add the index line and commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: probe turns"
```

---

## Self-Review

**Spec coverage:** §1 probe turn → Tasks 1-3. §2 when to probe → Task 7. §3 defensibility →
Tasks 4-6. §4 candidate-facing → Task 8. Data-model table → Tasks 3, 4, 6. Testing section →
tests in every task plus the E2E leg in Task 8. Out-of-scope items are absent, as intended.

**Placeholder scan:** no TBD/TODO; every code step carries real code; the two placeholders in
Task 8's E2E command (`<plan>`, `<module>`) are runtime arguments the executor supplies, not
unwritten design.

**Type consistency:** `_probe_count` / `_may_probe` / `_PROBE_NAME` / `_INTERRUPT_NAMES` are
defined in Tasks 1-2 and used with the same names in 3, 5 and 7. `evaluate_probe`'s return
shape defined in Task 4 matches what Task 5 reads (`verdict`, `note`) and what Task 6 averages
(`kind`, `verdict`). `defensibility_of` is defined in Task 6 and used only there. The
`probe_result` wire event's fields match between Tasks 5 and 8.

**One known ripple:** Task 3 changes `next_id` from `turn_count + 1` to `max(question ids) + 1`.
For any interview without probes these are identical, and `tests/test_interview_agent.py`
covers that path — run it in Task 3 Step 4 to confirm.
