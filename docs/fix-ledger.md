# Fix Ledger — copy, vocabulary and agent-facing text

Source findings: [platform-audit.md](platform-audit.md) — the *Copy, vocabulary & product
surface* table (C1–C13) plus two agent-layer findings (G2, G7). Nothing here is
implemented. Statuses are honest: three fixes already shipped in an earlier session and
are recorded as `done` rather than re-proposed.

## Four things the brief assumes that this repo does not have

Flagging these first because three of them change what "mechanical" means.

1. **There is no string catalogue and no i18n layer.** No `i18next`, `react-intl`,
   `lingui`, no locale files, no translation keys — confirmed against `package.json` and
   the whole of `frontend/src`. Every user-facing string is inline in TSX. So
   "extract hardcoded strings to the catalogue" is **not** mechanical here: the catalogue
   has to be designed and created first (FIX-M5), and that is a structural decision, not
   a move.
2. **"Never change translation keys" doesn't apply**, because there are none. The
   equivalent hazard in this codebase is different and worth naming: changing a
   **persisted Zustand key** (`ai-tutor-learner`, `atelier.interview.<planId>.<moduleId>`),
   an **API field**, or a **Mongo value**. Those are the things a "copy-only" rename can
   silently break, and they are what I'll self-review for.
3. **`docs/content-system.md` does not exist.** C3 asks me to land guardrails "from" it.
   It has to be written first; I've made it the deliverable of the final batch rather
   than pretending to draw on it.
4. **Track A / Track B were never run in this conversation as named tracks.** I'm treating
   `docs/platform-audit.md` as Track A. There is no Track B document, so nothing here
   implements a product decision — where one is needed, the fix stops at a spec.

**Also:** you asked me to run the tests and then interrupted the run, so **the suite has
not been run since that request**. Last known state, from before the interruption: 332
backend passed / 4 skipped, 8 frontend passed, lint and build clean.

---

## Ledger

Status key: `proposed` · `approved` · `done` · `rejected`.
String counts are occurrences, measured — not estimates.

| FIX-ID | Class | Finding | Files touched | Strings | What changes | Why | How verified | Rollback | Risk if wrong | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| FIX-M1 | M | C8 | 18 | ~38 | Normalise error phrasing: `Failed to…` → `Could not…` (1 site), and one punctuation rule (full stops on sentences, none on fragments) | Same failure ships two phrasings and the same message exists with and without a full stop | diff + `npm run build`; grep asserts zero `Failed to` remain | single revert | Low — display text only | proposed |
| FIX-M2 | M | C8 | 4 | 4 | De-duplicate the two strings that exist twice in different forms (`Name must be at least 2 characters[.]`, `Could not generate quiz[ — try again]`) | Identical failure, two wordings, by accident | diff; grep for each variant returns one form | single revert | Low | proposed |
| FIX-M3 | M | C12 | ~12 | ~14 | Action labels → sentence case (`Take Quiz` → `Take quiz`). **Product names excluded** (`Job Tracker`, `Interview Coach`, `Agent Evals`…) | Title and sentence case are mixed on adjacent buttons | diff against an approved include/exclude list | single revert | Medium — the exclusion list is a judgement call inside a mechanical fix; needs sign-off before it counts as M | proposed |
| FIX-M5 | M | new | 1 new | 0 | Create `frontend/src/lib/copy.ts` — structure only, no wording changes, no migrations | Nothing can be centralised until somewhere exists to centralise into | file exists, exports typed; build clean | delete file | Low (additive) | proposed |
| FIX-M6 | M | C2 | 3 | ~20 | Move nav + command-palette labels into `copy.ts` **verbatim**, both surfaces reading one source | The two surfaces can then never drift again; the wording fix is separate (FIX-J6) | diff shows moved-not-edited; a test asserts both read the same constants | single revert | Medium — a label is also a route key in places; must move display text only | proposed |
| FIX-M7 | M | C1 | 12 | 33 | Apply the noun chosen in FIX-J6 across all remaining occurrences | Nine names for one object | grep: variants collapse to one; build clean | single revert | Medium — must not rename `coursesAPI`, the `/courses` route, or the `course_plans` collection | proposed |
| FIX-J1a | J | C7 | 9 (highest-traffic) | ~30 | Rewrite error copy to name a cause and a next step. `Could not analyze the job` → cause + action. Delete `Discovery failed` | 22 of 38 errors are the failed action restated, with no cause and no recovery | manual trigger of each class (429, timeout, refusal, transport) | per-file revert | Medium — wording is a choice; needs sign-off | proposed |
| FIX-J1b | J | C7 | 9 (remainder) | ~36 | Same, for the lower-traffic surfaces | as above | as above | per-file revert | Medium | proposed |
| FIX-J2 | J | C10 | 2 | 4 | Give the two action-less empty states an `action` (the prop exists and is unused there), and rewrite both bodies to invite rather than describe | Dead ends on screens a new user lands on first | visual check; `EmptyState` renders a button | single revert | Low | proposed |
| FIX-J3 | J | C11 | 2 | 4 | Replace `Restricted` with a message that says what the page is and who it's for | Reads as a permissions error, not a product boundary | visual check as a non-superuser | single revert | Low | proposed |
| FIX-J4 | J | C9 | 4 | ~7 | System vocabulary → user vocabulary: `Agent config updated`, `AI Model Status`, `Test Model`, `Trend discovery started`, and the empty state that explains the sampling implementation | Names things by how the system is built, not by what the person controls | diff; grep for the retired terms | single revert | Low | proposed |
| FIX-J5 | J | C6 | ~15 | ~30 | Apply one voice to the success toasts. **Blocked on the voice decision** (recommendation: first person in the two conversational surfaces, neutral system voice elsewhere) | Three narrators — system, first-person AI, cheerleader | diff read end-to-end in one sitting | per-file revert | Medium — tone is the product's character | proposed |
| FIX-J6 | J | C1, C2 | 3 | ~12 | **Choose the noun** for the generated plan, the `/doubts` surface and the `/learn` surface, and apply it to nav + palette only | Sidebar says `Career Paths`, palette says `My Courses` and `Plan a new course` tagged `Learning Path`; `/doubts` has three names | grep: nav and palette agree for all 8 destinations | single revert | High-ish — renaming the core object touches marketing language; **product sign-off required** | proposed |
| FIX-J7 | J | new | 3 | 11 | Rewrite the learner-facing error strings emitted by agent code (`handler.py`, `interview_agent.py`, `steps.py`, `stream_adapter.py`) to match the FIX-J1 rules | These bypass the frontend error work entirely and are the ones a learner sees mid-stream | backend tests; grep | single revert | Medium — strings only, no logic | proposed |
| FIX-B1 | B | C7 | 1 | 1 | Reword the guardrail refusal at `routers/chat.py:105` | Guardrail message — Class B by definition | side-by-side prompt-injection inputs, old vs new | single revert | Medium — must stay a refusal, not become negotiable | proposed |
| FIX-B2 | B | C6 | 1 (`react_agent.yaml`) | 5 roles | Align the five specialist persona prompts with the chosen voice (FIX-J5) | If the UI voice changes and the persona doesn't, the product contradicts itself mid-turn | 10 inputs, old vs new, side by side | single revert | **High** — persona changes affect every chat turn and cannot be proved by diff | proposed |
| FIX-B3 | B | new | 1 (`react_agent.yaml`) | 1 block | Review `reasoning_protocol` wording against the voice decision | Same reason; it is injected into every specialist | as above | single revert | **High** | proposed |
| FIX-B4 | B | new | 1 (`learner_context.py`) | ~10 directives | Review the personalisation directives I wrote this session against the voice decision | They are prompt text and were never voice-reviewed | A/B by profile, old vs new | single revert | **High** | proposed |
| FIX-B5 | B | new | 1 (`tools.py`) | 14 docstrings | Review tool descriptions for accuracy and consistency | Tool descriptions steer tool choice; wording changes behaviour | trajectory evals (needs a live NIM key) | single revert | **High** — mis-worded descriptions cause wrong tool selection | proposed |
| FIX-U1 | U | C13 | — | — | **Spec only.** Where an AI-limitation caveat sits under generated lessons, interview grades and the rating readout | No caveat exists anywhere; a graded Elo marketed as "A rating for what you know" is the platform's biggest trust gap | n/a — design deliverable | n/a | n/a | proposed |
| FIX-U2 | U | new | — | — | **Spec only.** Chat regenerate/edit shows a disclosure saying the model still remembers the superseded turn. The copy exists to paper over the missing backend session-truncation path | Copy cannot fix this; only a real rewind can | n/a | n/a | n/a | proposed |
| FIX-U3 | U | U2 (audit) | — | — | **Spec only.** Doubt chat has no stop/regenerate; its error copy compensates for affordances that aren't there | Same shape — a UI gap wearing a copy patch | n/a | n/a | n/a | proposed |
| FIX-M4 | M | C3 | 2 | 2 | Landing numbers derived from source, pinned by a backend test | Two false numbers on the highest-traffic page | `test_platform_facts.py` (5 tests) | — | — | **done** |
| FIX-J8 | J | C4 | 1 | 1 | Removed the "about 10 seconds" promise the rate limiter cannot keep | Made a normal busy period look broken | — | — | — | **done** |
| FIX-J9 | J | C5 | 1 | 2 | Split loading from empty on the leaderboard | Empty board showed a permanent fake spinner | — | — | — | **done** |
| FIX-M8 | M | G7 | 3 | 6 | Retired the two admin sliders backed by nothing | A control that reported success and changed nothing | `test_agent_settings.py` | — | — | **done** |

---

## Batches

One class per batch. Safest first. Every batch is a single revert and leaves the app
working if everything after it is abandoned.

| # | Batch | Class | Fixes | Files | Strings | One-line summary |
|---|---|---|---|---|---|---|
| 1 | `copy-mechanics` | M | M1, M2 | 18 | ~42 | One phrasing and one punctuation rule across every error string; kill the duplicate pairs. |
| 2 | `label-casing` | M | M3 | ~12 | ~14 | Action labels to sentence case, product names explicitly excluded. |
| 3 | `copy-scaffold` | M | M5, M6 | 4 | ~20 | Create `lib/copy.ts` and move nav + palette labels into it **verbatim** — no wording changes. |
| 4 | `error-copy-core` | J | J1a | 9 | ~30 | Errors on the busiest surfaces get a cause and a next step. |
| 5 | `error-copy-rest` | J | J1b | 9 | ~36 | The same treatment for the remaining surfaces. |
| 6 | `agent-error-copy` | J | J7 | 3 | 11 | The learner-facing errors emitted by agent code, brought in line. |
| 7 | `empty-and-restricted` | J | J2, J3 | 4 | 8 | Empty states invite an action; "Restricted" says what the page is. |
| 8 | `system-vocabulary` | J | J4 | 4 | ~7 | Stop naming things after the implementation. |
| 9 | `voice` | J | J5 | ~15 | ~30 | One narrator across the success toasts. **Blocked on the voice decision.** |
| 10 | `terminology-decision` | J | J6 | 3 | ~12 | Choose the noun; apply to nav + palette only. **Blocked on product sign-off.** |
| 11 | `terminology-rollout` | M | M7 | 12 | 33 | Apply the chosen noun everywhere else. |
| 12 | `guardrail-message` | B | B1 | 1 | 1 | Reword the guardrail refusal. |
| 13 | `persona-voice` | B | B2, B3 | 1 | 6 | Align the five personas + reasoning protocol with the chosen voice. |
| 14 | `agent-prompt-review` | B | B4, B5 | 2 | ~24 | Personalisation directives and tool descriptions reviewed. |
| 15 | `content-system` | M | new | 3 new | 0 | Write `docs/content-system.md`, add the CI check against new hardcoded strings, put the glossary where the team will see it. |

### Ordering deviations — both need your call

1. **Batch 11 (M) must run after Batch 10 (J).** Your rule is all Class M before all
   Class J. It cannot hold here: the mechanical rename has no target string until the
   naming decision is made. I have not silently reordered — Batch 11 sits after Batch 10
   and I need you to accept that, or split differently.
2. **Batch 3 creates the catalogue before any wording changes**, so that later batches
   have somewhere to land. It is Class M and additive, but it is genuinely new structure
   rather than an extraction.

### Blocked batches

- **9 (`voice`)** and **13 (`persona-voice`)** both need the voice decision, and 13 must
  follow 9 or the UI and the agent will contradict each other.
- **10 (`terminology-decision`)** needs product sign-off on the noun.
- **12, 13, 14 (all Class B)** additionally need the side-by-side output gate, and
  **that gate cannot be fully honoured right now**: the offline trajectory harness needs a
  live `NVIDIA_API_KEY`, so unless one is available I can show prompt diffs and reasoned
  predictions but **not** verified old-vs-new model output. I will say which it was
  rather than implying the change is verified.

### Class U — specs, not patches

FIX-U1 (AI-limitation caveat), FIX-U2 (real chat rewind vs the disclosure that papers over
it), FIX-U3 (doubt chat stop/regenerate). All three produce a short interface spec for
design; none produce a patch.
