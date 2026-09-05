# Platform Plan — Atelier (ai-tutor)

Phased remediation for the findings in [platform-audit.md](platform-audit.md).
Finding IDs (A*, U*, C*) refer to that document.

**Rules this plan follows:** every phase ships independently and `main` stays green. No
rewrites — consolidation and incremental migration only. Model-facing changes are called out
because their regressions are silent; where a deterministic assertion isn't possible, the
verification method says how to check anyway.

**Ordering:** by (user impact × reuse count) / effort. Phase 0 is the safety net and gates
Phases 3, 6, and 7.

---

## Status — 2026-09-05

| Phase | State | Notes |
|---|---|---|
| 0 — Safety net | **Shipped (partial)** | Vitest + golden byte-split SSE fixtures landed (`npm test`). mypy report-mode and the Langfuse baseline are **not** done. |
| 1 — One SSE client/emitter | **Shipped** | A1, A2, A3, A4 all closed. |
| 2 — Error taxonomy + wording | Not started | Blocked: needs product sign-off on the five error classes. |
| 2b — Vocabulary, voice, numbers | **Partial** | C3, C4, C5 shipped. C1/C2/C6/C13 blocked on naming + voice + caveat sign-off. C9–C12 not started. |
| 3 — Make the wait legible | **Shipped** | A5 closed; `guardrail` handling (U1) shipped alongside it. |
| 4 — Delete dormant subsystems | Not started | Blocked: keep-or-drop decision on the weekly digest. |
| 5 — Contract hardening | Not started | Unblocked, 4 dev-days. |
| 6 — Chat parity + a11y | Not started | Blocked: design sign-off on stop/regenerate placement. |
| 7 — Styling consolidation | Not started | Opportunistic by design. |

**Verified at time of writing:** 288 backend tests pass (4 skipped, the deepeval-gated
suite), 8 frontend tests pass, `npm run lint` clean, `npm run build` succeeds.

**One audit correction:** C3 claimed "6 agents on call" was wrong because `SPECIALISTS`
holds 5. That reading was too narrow — the landing page lists six named agents and the
interview coach is a real Strands agent, so the count is defensible. The genuinely wrong
number was the sub-skill count (32 stated, 108 actual), which appeared in two places. The
hero count now renders from the roster the page displays, so it cannot drift.

---

## Phase 0 — Safety net

**Goal:** make streaming and shared-UI changes verifiable before touching them.

**Files:** new `frontend/vitest.config.ts`, `frontend/src/lib/__tests__/sse.test.ts`;
`backend/pyproject.toml` (mypy, report-only). No application code.

- Vitest + React Testing Library, wired into CI alongside `npm run lint` — not blocking yet.
- **Golden SSE fixtures.** Record one chat turn and one interview turn, then replay each
  through the reader **byte-split at every offset**. This is the deterministic test that pins
  A3/A4 and guards Phase 1: frame-splitting is pure string handling, so it is fully testable
  even though the payload originates from a model.
- mypy in report-only mode with a baseline. No gate yet.
- **Baseline capture for model-facing work:** 20 chat turns and 5 interviews through Langfuse,
  recording routed agent, latency, and token counts. This is the before/after reference for
  any later change that can't be asserted.

**What could break:** nothing — additive only.
**Rollback:** delete the config files.
**Verify:** `npm test` green; mypy report generated; Langfuse baseline saved.
**Size:** 2 dev-days. **No sign-off needed.**

---

## Phase 1 — One SSE client, one SSE server helper

**Clears A3, A4, A1, A2.** Highest (impact × reuse)/effort in the audit: all three reported
pains touch this code, and it is reused by every streaming surface.

**Goal:** exactly one browser SSE reader and one server SSE emitter.

**Files:** `frontend/src/lib/api.ts` (fold `streamChat` into `streamSSE`),
`frontend/src/pages/DoubtChatPage.tsx` (delete the inline reader),
`backend/app/routers/doubts.py` and `chat.py` (adopt `app/sse.py`).

**Migration order**

1. Give `streamSSE` an auth-refresh path: on 401, call `/auth/refresh` once, retry, else
   `_forceLogout()` — mirroring the axios interceptor at `api.ts:145-170`. → **A1**
2. Point `chatAPI.streamChat` at `streamSSE` internally, keeping its public signature. → **A4**
3. Migrate `DoubtChatPage` to `streamSSE`; handle `error` frames explicitly. → **A3**
4. Replace `doubts.py:119`'s `str(e)` with a generic message plus a server-side log, and move
   both `chat.py` and `doubts.py` onto `sse_frame` / `SSE_HEADERS`. → **A2**

**What could break:** doubt chat's frame shape is `{token}`, not `{type}` — and `streamSSE`
skips frames without a `type`. Either emit `{"type":"token", …}` server-side (preferred; it
aligns the two chat surfaces) or add one shim. This is the only real risk in the phase and is
covered by a Phase 0 fixture.
**Rollback:** each of the four steps reverts independently.
**Verify:** Phase 0 byte-split fixtures. Manually: set `ACCESS_TOKEN_EXPIRE_MINUTES=1`, wait
for expiry, then start a chat turn — it should refresh silently rather than fail.
**Size:** 2 dev-days. **No sign-off needed.**

---

## Phase 2 — Errors that say what happened and what to do

**Clears U1, U1b, C7, C8.** The taxonomy and the wording are one job — splitting them means
writing all 38 strings twice.

**Goal:** rate-limit, timeout, refusal, guardrail block, and empty result are visibly
different *and* each names a cause and a next step.

**Files:** new `frontend/src/lib/errors.ts` (status/event → `{kind, title, whatToDo}`); the 66
`toast.error` call sites migrated surface by surface; `AtelierV2Page.tsx` (add the `guardrail`
case and keep the message visible instead of dropping the bubble).

**Copy rules, applied to all 38 messages**

- Name the cause, not the failed action. "Could not analyze the job" → "The job description
  couldn't be read — check it pasted fully, then try again."
- Never ship a message that is only the button label negated. Delete "Discovery failed".
- One phrasing per failure class: "Could not…" everywhere, never "Failed to…". Full stops on
  full sentences, none on fragments — pick one and apply it. → **C8**
- Rate-limit errors say when to come back; the backend already knows the window
  (3/hour, 6/hour, 20/hour).

**Migration order:** ship the mapper and the `guardrail` case first — that alone closes the
"my message vanished" bug — then migrate call sites surface by surface.
**What could break:** nothing structural; the risk is copy regressions.
**Rollback:** revert per surface.
**Verify:** trigger each class by hand — a prompt-injection string (guardrail), exceeding
3/hour on course plan (429), killing the backend mid-stream (transport).
**Size:** 3 dev-days. **Needs product sign-off** on the five error classes and their wording.

---

## Phase 2b — One vocabulary, one voice, honest numbers

**Clears C1, C2, C3, C4, C5, C6, C9, C10, C11, C12, C13.** Almost entirely string edits with
no logic change, and the phase that most changes how finished the platform feels.

**Goal:** every screen names the same thing the same way, in one voice, and states nothing the
product can't back.

**Files:** `Sidebar.tsx`, `CommandPalette.tsx`, `LandingPage.tsx`, `ModulePlayerPage.tsx`,
`DashboardPage.tsx`, `ProfilePage.tsx`, `AdminPage.tsx`, `EvalsDashboardPage.tsx`,
`CoursePlannerPage.tsx`, `InterviewCoachPage.tsx`, plus a new
`frontend/src/lib/vocabulary.ts` holding the agreed noun for each product object.

**Migration order**

1. **Agree the nouns — this is the blocking decision.** One name each for: the generated
   multi-module plan (currently 9 names), the `/doubts` surface (currently 3), the `/learn`
   surface (currently 2). Everything else follows mechanically. → **C1, C2**
2. Land `vocabulary.ts` and repoint `Sidebar` + `CommandPalette` at it, so the two navigation
   surfaces can never drift again. → **C2**
3. **Honest numbers.** Either derive "sub-skills rated" and "agents on call" from their real
   sources (`prompts/curriculum.yaml` topic_graph, `SPECIALISTS`) or drop the counts and keep
   the qualitative claim. Deriving takes about an hour and makes the claim permanently true.
   → **C3**
4. **Replace the 10-second promise** with the capacity-notice mechanism that already exists —
   "Preparing your content…" plus the real throttle notice when one fires. → **C4**
5. **Fix the leaderboard empty state** — move "Leaderboard loading…" into the loading branch
   and write a real empty state for a board of one. → **C5**
6. **Pick one voice and apply it.** Recommendation: keep the warm first-person voice in the
   two conversational surfaces where it already reads well, and use the neutral system voice
   everywhere else. Write the rule down in `vocabulary.ts`. → **C6**
7. Pass the `action` prop on the two dead-end empty states; rewrite "Restricted"; rename the
   system-vocabulary labels; normalise button casing to sentence case. → **C9–C12**
8. **Ship the AI limitation disclosure** — one line under generated lesson content, one under
   an interview grade, one on the rating readout. → **C13**

**What could break:** nothing at runtime. But renaming the core object touches marketing copy,
so sign-off is needed *before* step 2, not after.
**Rollback:** per file; every change is a string.
**Verify:** grep that the nine competing nouns collapse to one; walk the sidebar and ⌘K side
by side; confirm both landing numbers now derive from code.
**Size:** 3 dev-days.
**Needs product sign-off:** the object names (step 1), the voice (step 6), the AI caveat
wording (step 8). **Needs design sign-off:** where the caveat sits, so it informs without
undercutting the rating.

---

## Phase 3 — Make the wait legible

**Clears A5.** Best impact-to-effort ratio in the plan.

**Goal:** the chat shows real progress during the tool phase.

**Files:** `AtelierV2Page.tsx` — add `case 'step'` and feed the segments into
`ReasoningStream`. Backend unchanged; it already emits the events.

**What could break:** `ReasoningStream` must not spin forever. The existing `status: 'done'`
convention used by capacity notices already covers this and must be preserved.
**Rollback:** one-line revert of the switch case.
**Verify:** deterministic. The events are server-generated with fixed labels
(`steps.py:68-72`), so a fixture asserting the three named steps render in order is a real
test, not a smoke check.
**Size:** 0.5 dev-days. **No sign-off needed.**

---

## Phase 4 — Delete the dormant subsystems

**Clears A7, A8, A12, U6.** Pure subtraction; simplifies reasoning about everything after it.

**Files:** delete `app/websocket.py`, `app/tasks/`, `backend/ai_tutor.db`,
`backend/pytest.ini`, and the unused `ui/{Tabs,Tooltip,Divider,Kbd}.tsx` (+ their
`ui/index.ts` exports). Edit `main.py` (drop `socket_app`, fix the OpenAPI description),
`admin.py` (the digest endpoint), `pyproject.toml`, `render.yaml`, `docker-compose.yml`,
`CLAUDE.md`, `README.md`.

**Migration order:** UI primitives → SQLite file + `pytest.ini` → Socket.IO → Celery last
(it has one live caller).

**Sequencing note:** run this *after* Phase 2b. The AI-limitation caveat (C13) is a natural
use for `Tooltip`, and the empty-state action buttons (C10) may want `Kbd`. Decide both in
Phase 2b, then delete whatever is still unused — rather than deleting first and rebuilding.

**What could break:** the entrypoint changes from `app.main:socket_app` to `app.main:app`, and
`render.yaml`, `Dockerfile`, `docker-compose.yml`, and `CLAUDE.md` all name it. Missing one
fails the deploy loudly, which is the good failure mode. The digest endpoint must either
become a direct `await` or be removed — **product decision**.
**Rollback:** `git revert`; nothing depends on the deleted code.
**Verify:** `uv run pytest`; boot the app; `/ready` returns 200; `npm run build`.
**Size:** 1.5 dev-days. **Needs product sign-off:** keep or drop the weekly digest.

---

## Phase 5 — Contract hardening

**Clears A9, A10, A11.**

**Files:** `app/routers/*` (add `response_model`, hoist the 16 inline `BaseModel`s into
`app/schemas/`); new `frontend/src/lib/api-types.generated.ts`; `pyproject.toml` (mypy gate).

**Migration order:** one router per PR, highest-traffic first — `chat`, `courses`,
`interview_loops`, `quiz`. Generate TS types from `/openapi.json` and have the hand-written
interfaces extend the generated ones, so drift becomes a **compile error** instead of a
runtime surprise. Turn the mypy gate on per-package as each goes green.

**What could break:** adding `response_model` silently *filters* undeclared fields out of
responses. This is the one way the phase can break the UI — diff each endpoint's payload
before and after.
**Rollback:** per router.
**Verify:** `npm run build` (type errors surface drift), `uv run pytest`.
**Size:** 4 dev-days. **No sign-off needed.**

---

## Phase 6 — Chat parity + accessibility

**Clears U2, U3, U5, U8.**

**Files:** `DoubtChatPage.tsx` (abort/stop, regenerate, use the token module); `ui/Input.tsx`
(bind `id`/`htmlFor`); the 18 unbound labels; `aria-live="polite"` regions on the four
streaming surfaces; confirm dialogs on the two destructive actions.

**What could break:** an `aria-live` region wired to raw tokens will flood a screen reader.
Announce on completion or debounce — never per token.
**Rollback:** per file.
**Verify:** keyboard-only pass over the four surfaces; VoiceOver through one chat turn; axe
DevTools clean on chat and interview.
**Size:** 3 dev-days. **Needs design sign-off** on stop/regenerate placement in doubt chat.

---

## Phase 7 — Styling consolidation (opportunistic, never big-bang)

**Partially clears U4, U7.**

**Rule:** any file already being edited for another reason converts its inline styles to
tokens/utilities. No standalone migration PRs. `InterviewRunner.tsx` is split into runner +
transcript + editor + scoring panel **only** when a feature change requires it.

**What could break:** visual regressions with no snapshot net — so this phase is gated on
Phase 0 existing, and each conversion is reviewed against a screenshot.
**Size:** ongoing, ~0.5 day per file converted.

---

## Do these five first

Four are under a day each and three are pure string edits. The cheapest wins in this audit are
in the copy, not the architecture.

| # | Item | Why first | Size |
|---|---|---|---|
| 1 | **C3, C4, C5 — the three untrue strings.** "6 agents on call" (there are 5), "32 sub-skills rated" (~108, no fixed 32), "takes about 10 seconds" (the throttle can park a call for 60), and a permanent "Leaderboard loading…" on an empty board. | Four edits, all on first-impression screens, all currently false. | 0.5 d |
| 2 | **A3 — the `undefined` in doubt-chat answers.** | Visible text corruption; one-line cause. | 1 h |
| 3 | **A5 — render the `step` events the backend already sends.** | Kills pain #2 with no model change; the data is already on the wire. | 0.5 d |
| 4 | **U1 — the `guardrail` case.** | Stops silently deleting the learner's message. | 2 h |
| 5 | **Phase 0 fixtures, then A1** (auth refresh in the SSE path). | Most likely cause of "it just failed" on long interviews, and the fix that most needs a net under it. | 2.5 d |

**C1/C2 (the nine names) is the highest-impact copy item** but is blocked on naming sign-off,
so it starts as a decision, not a ticket. Raise it in the same meeting as item 1.

## Explicitly not doing

1. **Not unifying the two LLM provider stacks (A6).** ⚠ Model-facing. The two stacks have
   different retry, fallback, and `extra_body` semantics; a regression would be silent and
   un-assertable. Revisit only when a model swap forces it — the four-check protocol in
   `config.py:49-62` is the gate, not a refactor.
2. **Not running a global inline-style → Tailwind migration (U4).** 1,131 call sites with no
   visual regression net is a change whose risk stays invisible until a user reports it.
   Convert opportunistically (Phase 7) instead.
3. **Not adding RAG or a vector store.** No retrieval layer exists and nothing in the product
   asks for one; `goal_vector` is a stored field, not an index. That would be new surface
   area, not debt reduction.

**And one thing not to do inside the copy work:** do not rewrite the landing page. Its voice
— "A rating for what you know", "A studio, not a chatbot", "Find out your number" — is the
strongest, most deliberate writing in the product, and is the reference the rest of the app
should be raised to. Fix the two false numbers on it (C3) and leave the prose alone.
