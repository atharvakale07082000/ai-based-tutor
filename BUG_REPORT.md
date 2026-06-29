# Atelier — Full-Platform Sanity Report

**Date:** 2026-06-29
**Target:** live deployment — frontend https://ai-based-tutor.vercel.app, backend https://ai-based-tutor.onrender.com
**Method:** real-browser (Playwright/Chromium) testing as superuser (`admin@test.com`), every interactive control clicked, outputs awaited to completion, light **and** dark mode inspected via full-page screenshots. Run module-wise by 4 parallel agents. **AI Interview module excluded** per request.

## Executive summary

| Severity | Count | Modules |
|---|---|---|
| 🔴 High | 3 | Quiz (2), Doubt Solver (1) |
| 🟠 Medium | 3 | Doubt Solver (2), Auth (1) |
| 🟡 Low / UX | 5 | Dashboard, Landing, Flashcards/cold-start, Job Tracker, Quiz entry |

## ✅ Resolution status (commit `4034abe`)

| ID | Status | Fix |
|---|---|---|
| H1 quiz submit 400 | **Fixed** | `answersRef` so the last answer is never stale ([QuizPage.tsx](frontend/src/pages/QuizPage.tsx)) |
| H2 `/quiz/new` dead | **Fixed** | generate-then-navigate ([ProgressPage.tsx](frontend/src/pages/ProgressPage.tsx)) |
| H3 doubt follow-up 422 | **Fixed** | removed 2000-char history cap ([doubts.py](backend/app/schemas/doubts.py)) |
| M1 doubt dark mode | **Not a bug** | verified renders correctly in dark mode — subagent screenshot fired before repaint |
| M2 doubt error UX | **Resolved by H3** | follow-ups no longer 422 |
| M3 onboarding redirect | **Fixed** | sign-in always → `/dashboard` ([LandingPage.tsx](frontend/src/pages/LandingPage.tsx)) |
| L1 Schedule no-op | **Fixed** | navigates to career feed ([DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx)) |
| L2 dead landing links | **Fixed** | smooth-scroll to agents section |
| L3 cold-start indicator | Deferred | Render free-tier infra; UX nicety, not a code defect |
| L4 readiness 0% | Not a bug | expected — test account has no skill-proficiency data |

Backend + frontend build clean, tests pass. Backend fixes go live on Render redeploy; frontend on Vercel redeploy.

**Overall health: good.** Core platform works — login/logout, all 12 nav routes render, multi-turn **chat works across 3+ turns**, course planner generates real plans, flashcards work, career feed, progress, job tracker (add/analyze/edit/delete), and the evals dashboard (273 evals) are all healthy. The serious issues are concentrated in **Quiz completion** and **Doubt Solver follow-ups** — both block a core user flow.

---

## 🔴 High severity

### H1 — Quiz submission always fails with HTTP 400 (off-by-one; last answer dropped)
- **Where:** Quiz flow → Submit. `POST /api/v1/quiz/{id}/submit/stream` → **400** "Expected 5 answers, got 4".
- **Symptom:** After answering every question, submit fails with a "Could not submit quiz results" toast; the score/results screen **never renders** — the user is stuck. Reproduced deterministically (always N-1 answers).
- **Root cause:** [QuizPage.tsx:109-117](frontend/src/pages/QuizPage.tsx#L109-L117) — `handleFinish()` posts the closure value of `answers`, but the final answer is added via `setAnswers((prev) => [...prev, option])` ([:79](frontend/src/pages/QuizPage.tsx#L79)) and hasn't flushed when `handleNext()`→`handleFinish()` runs on the last question. The stale array (missing the last answer) is sent.
- **Fix:** compute the final answers array explicitly and pass it through, e.g. capture `const final = [...answers]` at reveal time, or have `handleFinish(finalAnswers)` receive the array rather than reading state. Backend `_validate_quiz_answers` is correct to reject the mismatch.
- **Corroboration:** the live evals dashboard shows `quiz format` failing with reason `no_questions` (68% pass) — consistent with broken submissions.

### H2 — "Take a quiz" / "Review" on Progress lead to a dead page (`/quiz/new`)
- **Where:** [ProgressPage.tsx:188](frontend/src/pages/ProgressPage.tsx#L188) and [:280](frontend/src/pages/ProgressPage.tsx#L280) navigate to `/quiz/new` (and `/quiz/new?topic=...`).
- **Symptom:** the only quiz route is `/quiz/:quizId` ([App.tsx:166](frontend/src/App.tsx#L166)), so `/quiz/new` matches `quizId="new"`, and `QuizPage` disables generation for `'new'` → the page hangs on the app spinner / never produces a quiz.
- **Working path (for contrast):** Dashboard → "Start skill practice" calls `quizAPI.generate` then routes to `/quiz/{realId}` (works, ~45s cold start).
- **Fix:** either add a `/quiz/new` handler that generates then redirects, or change the Progress buttons to call `quizAPI.generate({topic})` and navigate to the returned id (mirror the dashboard action).

### H3 — Doubt Solver follow-ups fail with HTTP 422 when a prior answer is long
- **Where:** Doubt Solver → ask a follow-up. `POST /api/v1/doubts/stream` → **422** `string_too_long` on `history[].content`.
- **Symptom:** any follow-up in a session where a previous answer exceeded **2000 chars** fails; user sees only a misleading toast ("I hit a snag — send your question again…"), and resending can't help (history still holds the long answer).
- **Root cause:** [doubts.py schema:10](backend/app/schemas/doubts.py#L10) — `content: str = Field(min_length=1, max_length=2000)`. **This is the same cap that broke multi-turn chat; the fix was applied to chat but the Doubt Solver schema was missed.**
- **Fix:** remove/raise the 2000-char cap on doubt `history[].content` (match the chat fix). Optionally truncate server-side instead of rejecting.

---

## 🟠 Medium severity

### M1 — Doubt Solver does not apply dark mode to the chat panel
- The sidebar/top-bar go dark, but the answer bubbles, empty-state, and composer stay on a **light cream background with dark text** — jarring. `/atelier` themes correctly; `/doubts` does not. Evidence: `/tmp/e2e_chat/12_doubts_realdark.png`, `13_doubts_dark_answer.png`.

### M2 — Doubt Solver error UX is misleading on the 422 (H3)
- On failure the only feedback is a generic "send again" toast — no failed state on the question bubble, and resending cannot succeed. Should surface a real error and recover (after H3 is fixed, this becomes moot, but the retry-can't-help UX is worth hardening).

### M3 — Returning user lands on the onboarding wizard after login
- After a successful login the (already-onboarded) superuser is dropped on `/onboarding` ("STEP 1 OF 4 — What should we call you?", placeholder "Mira") rather than `/dashboard`, on each login. Expected: returning users skip onboarding. Evidence: `/tmp/e2e_shell/final_postlogin.png`. (Onboarding Skip/Continue themselves work.)

---

## 🟡 Low / UX

- **L1 — Dashboard "Schedule" quick action is a no-op** (no nav, no dialog, no API call). "Build career path"→/courses and "Mock interview"→/atelier work. ("Start skill practice" does work but is slow on cold start — one agent saw it as a no-op before the ~45s backend wake.)
- **L2 — Landing page nav not interactive:** "Product / Agents / Pricing" render but aren't link/button roles; a Privacy/Terms/Status footer was not present. CTAs ("Sign in", "Get started", "Start your first lesson") all work.
- **L3 — No cold-start indicator:** on a cold Render backend (~40s), pages (e.g. Flashcards) show only a skeleton with no "waking server" messaging — looks broken. Infra/UX, not a code defect.
- **L4 — Job Tracker readiness shows 0% after analysis** even though all JD skills are extracted — but the test account has no skill-proficiency data, so 0% (every skill a gap) is likely *correct*; flagging to confirm the scoring intent.
- **L5 — Quiz entry naming:** the only reliable quiz entry is Dashboard "Start skill practice"; Progress entry points are broken (see H2).

---

## ✅ Verified working (sanity passed)

- **Auth:** login (valid), wrong-password shows error (400, no crash), empty-submit guarded, logout clears session.
- **Navigation:** all 12 sidebar routes render (no blanks/404s); command palette (⌘K) opens, searches, navigates.
- **AI Assistant (`/atelier`):** multi-turn chat across **3+ turns**, all `POST /chat → 200`; markdown/code rendering; copy button; "new thread" clears; agent step-trace shown; dark mode correct.
- **Course Planner:** fresh plan generated via SSE (`/courses/plan/stream 200`), renders modules with content; suggestion chips populate the input; opening a plan/module works.
- **Career Feed:** load, Refresh, "Discover trends" (`/feed/run-discovery 200`, AI), all topic + content-type filters, Snooze (`/feed/{id}/snooze 200`), Schedule dialog.
- **Flashcards:** deck loads (recent fix confirmed live, `/quiz/flashcards 200`), reveal, rate Easy/Hard/Skip, advance 1→10, completion screen, "Go again"/"Back".
- **Progress:** stats/heatmap/mood render; Export downloads `progress-report.json` (`/progress/report 200`).
- **Quiz (generation half):** questions are **distinct & well-formed** (5/5 unique, valid options — the recent NVIDIA-pin fix confirmed); "Generate deeper explanation" works (`/quiz/{id}/explain 200`). *(Only submission is broken — H1.)*
- **Job Tracker:** add job, "Analyze fit" (`/jobs/analyze/stream 200`) renders skill-gap, save (`/jobs 200`), stage change (`PATCH 200`), delete (`DELETE 200`); dark mode clean.
- **Agent Evals (superuser):** dashboard fully populated (273 evals, 85% pass, by-metric/by-agent/trend/recent), dark mode clean.
- **Dark mode** works correctly across all pages **except** the Doubt Solver panel (M1).

---

## Notes
- Screenshots per module: `/tmp/e2e_shell/`, `/tmp/e2e_learn/`, `/tmp/e2e_chat/`, `/tmp/e2e_quiz/`.
- The AI Interview module was **not** tested (excluded by request).
- The 3 High bugs (H1, H2, H3) are confirmed in source, not just observed — each has a concrete fix location above.
