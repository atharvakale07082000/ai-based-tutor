# Probe turns: integrity by design in the interview agent

**Status:** approved design, not yet implemented
**Date:** 2026-08-23
**Area:** `backend/app/agents/interview_agent.py`, `interview_scorer`, `components/interview/InterviewRunner.tsx`

---

## Why

Atelier's pitch is "a rating for what you know." Today nothing defends that rating: a
candidate can paste every interview answer from an LLM and the tuned rubric will score the
prose exactly as well as it deserves on its own merits. The product's central claim is the
one thing it does not back.

Three anti-cheat philosophies were considered — surveillance signals (paste, focus loss,
timing), visible deterrence (warnings, lockdown), and making the assessment itself
unfakeable. The third was chosen because it is the only one that works against a tool you
cannot detect (a second device), and because this codebase is unusually ready for it: the
interview is already an interrupt-driven agent that resumes with the candidate's answer and
its calibrated evaluation, then adaptively decides what to ask next.

It also reframes the feature. "How well does your understanding hold up when pushed?" is
real feedback for an honest learner, and simultaneously the thing a pasted answer cannot
survive. Nobody is accused of anything.

## Invariant this design must not break

**The agent chooses questions; the tuned YAML rubrics own grading.** `interview_agent.py`
states this explicitly ("The agent never assigns the numeric score; it only chooses good
questions"). Probing splits the same way: the agent decides *whether and what* to probe; a
rubric decides *how well the probe was answered*.

Two related rules carry over unchanged:

- Pass thresholds come from `agents/bar.py`, never a bare number.
- Interview state is projected to the client by whitelist (`course_planner.interview_state`),
  so anything internal stays internal by default.

---

## 1 · The probe turn

### Tool

A second interrupt tool beside `ask_candidate`:

```python
@tool
def probe_candidate(question: str, targets: str = "") -> str:
    """Press the candidate on something they just claimed, in their own words."""
```

`targets` is the specific claim being tested (e.g. `"their assertion that NumPy arrays are
cache-friendly"`). It is stored for the rubric and never shown to the candidate.

### Mechanics

`InterviewInterruptHook._pause_for_answer` currently matches a single tool name via the
module constant `_INTERRUPT_NAME`. That becomes a set of both tool names, so a probe raises
the same Strands interrupt, persists to the same `FileSessionManager` session, and resumes
through the same path. **No new turn machinery.**

`_drive` gains one branch: when the interrupt came from `probe_candidate`, the persisted
question carries `kind: "probe"` and `probes_of: <question_id>`, and `turn_count` is **not**
incremented — a probe is not a new question. It appends to `questions[]` like any other turn
so `interview_state` resume keeps working untouched.

The existing blank-question guard (`interview_blank_question`) applies to probes too.

### Budget

| Setting | Default | Meaning |
|---|---|---|
| `INTERVIEW_MAX_PROBES` | 3 | Hard cap per interview |
| — | 1 | Probes per question (enforced in `_drive`, not configurable) |

Both caps are enforced in code, not prompt text, because a model that ignores its budget
would otherwise be able to run an interview indefinitely. When the cap is reached, the
`probe_candidate` tool is not registered on the agent for that turn, so it cannot be called.

`_max_questions` / `_min_questions` are untouched: probes live in their own budget so a
probed interview still asks the same number of real questions.

## 2 · When the agent probes

Prompt guidance in `prompts/react_agent.yaml`'s interview section and the per-round
`SKILL.md` rubrics — deliberately *not* a threshold in code. The agent holds the whole
transcript and every calibrated evaluation, so it can judge "this answer is polished but
unowned" better than arithmetic can.

Probe when an answer is **fluent, complete, textbook-shaped, and notably stronger than the
candidate's other answers** — the profile of recall rather than understanding.

Do **not** probe:

- a weak answer (that candidate needs teaching, and pressing them is unkind and uninformative)
- an answer already grounded in specifics the candidate clearly owns (their own project,
  a named incident, a concrete trade-off they made)
- the final question, where there is no room to recover

A hard latency signal (submitted-in-8-seconds for 300 words) can later feed the same
decision without redesigning anything; it is deliberately out of scope for v1.

## 3 · How defensibility reaches the score

### The rubric

A new `probe_defensibility` section in `prompts/interview_scorer.yaml`, joining the existing
`analyze_answers` / `scoring_matrix` / `final_summary` / `code_review` sections and following
the same house style (`## Role` / `## Task` / `## Guidelines` / `## Output format`, XML data
tags, "candidate" as the graded person).

It grades **one axis only** — did the candidate defend, extend, or abandon their own claim?
It does not re-grade correctness; the original answer already has a score.

```json
{"verdict": "defended" | "partial" | "abandoned", "note": "<one line>"}
```

### Routing

`stream_answer` currently sends every answer to `course_planner.evaluate_answer`. It gains a
branch on `question["kind"]`: a probe's answer goes to a new
`course_planner.evaluate_probe(interview_id, question_id, answer_text)`, which mirrors
`evaluate_answer`'s shape (load interview → find question → render prompt → parse JSON via
`agents/json_utils.extract_json`) but renders `probe_defensibility`.

A probe's result is pushed to `answers[]` with `kind: "probe"` so the transcript stays whole,
and — critically — **is excluded from the `transcriptions` list `run_interview_review` builds**,
because the final grade must keep scoring the real questions only.

### The stored value

`run_interview_review` computes one extra field beside `final_score`:

```python
defensibility = {"defended": 1.0, "partial": 0.5, "abandoned": 0.0}
# mean over probe verdicts, or None when no probes were raised
```

Persisted as `interview["defensibility"]` (a 0-1 float or `None`). It is **reported, never
subtracted** — `final_score` and `passed` keep their current meaning, and `bar.py` keeps
owning the threshold. A number that silently discounted a score would be exactly the kind of
unbacked UI the 2026-08-15 audit removed.

## 4 · What the candidate sees

### During the interview

A probe renders as a normal question turn with one difference: a small label reading
**"Follow-up"** and the original question shown above it for context. The wire event is
`{"type": "question", "kind": "probe", ...}` — an additive field, so an older client that
ignores it degrades to showing a normal question, which is correct behaviour.

Framing is depth, never suspicion: *"You said X — walk me through Y."*

### In the result

Where a probe was raised, the final screen adds one line beside the score:

| verdict | copy |
|---|---|
| `defended` | Held up under follow-up |
| `partial` | Partially defended |
| `abandoned` | Couldn't extend under follow-up |

`interview_state` gains `defensibility` in its whitelist — the candidate is allowed to see
their own result. The per-probe `targets` and the rubric's `note` stay internal, like
`scoring_matrix` justifications already do.

---

## Data model changes

| Where | Field | Type | Note |
|---|---|---|---|
| `questions[]` | `kind` | `"question"` \| `"probe"` | absent = `"question"` for existing docs |
| `questions[]` | `probes_of` | `int \| None` | the question id being pressed |
| `questions[]` | `targets` | `str` | internal; never projected |
| `answers[]` | `kind` | `"answer"` \| `"probe"` | excludes probes from final scoring |
| `answers[]` | `verdict` | `str \| None` | probe rows only |
| interview root | `defensibility` | `float \| None` | 0-1, None when no probes |

All additive. Existing interviews read back unchanged — every new field is optional with a
behaviour-preserving default, so no migration is needed (and this repo has no migration step;
Mongo is the only datastore).

## Testing

Backend, following `tests/test_interview_agent.py`'s `_FakeAgent` harness and the repo's
patch-at-agent-module-level rule:

- a probe interrupt emits a `question` event with `kind: "probe"` and does **not** increment
  `turn_count`
- the per-question and per-interview probe caps hold, including that `probe_candidate` is
  absent from the toolset once the cap is reached
- a probe's answer routes to `evaluate_probe`, not `evaluate_answer`
- probe rows are excluded from the `transcriptions` passed to `run_scoring_agent`
- `defensibility` is `None` when no probe was raised, and the mean of verdicts when some were
- a blank probe is rejected exactly like a blank question
- `interview_state` projects `defensibility` but never `targets` or the rubric note

E2E: extend `e2e/interview_flow.py` with a probe leg — it already drives the real turn loop in
a browser and caught a real bug unaided.

## Out of scope for v1

- Latency, paste and focus signals (the design leaves the slot open; see §2)
- Any effect of `defensibility` on `passed` or on the Elo update
- Publishing defensibility to a public profile — that is direction A of the brainstorm, and
  depends on this landing first
