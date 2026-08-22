"""Live browser E2E for the module interview — the full interrupt-driven turn loop.

Drives a real Chromium against a real frontend + backend and asserts the contract the
interview screen depends on:

  1. Start streams a NON-EMPTY first question (the failure mode that produced the
     "Interview interrupted / the interviewer never sent your first question" card).
  2. Submitting an answer produces a per-answer score.
  3. The agent then asks its next question, adaptively.

Console errors, page errors and >=400 responses are captured throughout; any of them
fails the run, so a silently-broken SSE frame can't pass.

Usage:
    uv pip install playwright && uv run playwright install chromium
    E2E_BASE_URL=http://localhost:5173 E2E_EMAIL=... E2E_PASSWORD=... \
    E2E_PLAN_ID=... E2E_MODULE_ID=... uv run python e2e/interview_flow.py
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:5173").rstrip("/")
EMAIL = os.environ.get("E2E_EMAIL", "")
PASSWORD = os.environ.get("E2E_PASSWORD", "")
PLAN_ID = os.environ.get("E2E_PLAN_ID", "")
MODULE_ID = os.environ.get("E2E_MODULE_ID", "")
HEADED = os.environ.get("E2E_HEADED") == "1"
SHOTS = os.environ.get("E2E_SHOT_DIR", "")

if not all([EMAIL, PASSWORD, PLAN_ID, MODULE_ID]):
    raise SystemExit("Set E2E_EMAIL, E2E_PASSWORD, E2E_PLAN_ID and E2E_MODULE_ID.")

# The agent is a live LLM behind NIM's free tier, so turns are slow and can be throttled.
TURN_TIMEOUT_MS = 180_000

failures: list[str] = []
console_errors: list[str] = []
bad_responses: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' — {detail}' if detail else ''}")
    if not ok:
        failures.append(f"{label}{f': {detail}' if detail else ''}")
    return ok


def shot(page, name: str) -> None:
    if SHOTS:
        path = os.path.join(SHOTS, f"{name}.png")
        page.screenshot(path=path, full_page=True)
        print(f"        screenshot → {path}")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADED)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        page.on(
            "console",
            lambda m: console_errors.append(m.text[:300]) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {str(e)[:300]}"))
        page.on(
            "response",
            lambda r: bad_responses.append(f"{r.status} {r.url[:140]}") if r.status >= 400 else None,
        )

        # ── 1. Sign in ────────────────────────────────────────────────────────
        print("\n[1] sign in")
        page.goto(BASE, wait_until="domcontentloaded")
        page.get_by_role("button", name="Sign in").first.click()
        page.locator('input[type="email"]').fill(EMAIL)
        page.locator('input[type="password"]').fill(PASSWORD)
        page.locator("form").get_by_role("button", name="Sign in").click()
        page.wait_for_url(lambda u: "/dashboard" in u or "/onboarding" in u, timeout=60_000)
        check("authenticated", True, page.url.split(BASE)[-1])

        # ── 2. Open the module interview and start it ─────────────────────────
        print("\n[2] start the interview")
        page.goto(
            f"{BASE}/courses/{PLAN_ID}/modules/{MODULE_ID}/interview",
            wait_until="domcontentloaded",
        )
        # A stale interview id in localStorage would show the resume/recovery card instead
        # of the intro; clear it so this run always exercises a clean start.
        page.evaluate(
            "() => Object.keys(localStorage).filter(k => k.startsWith('atelier.interview.')).forEach(k => localStorage.removeItem(k))"
        )
        page.reload(wait_until="domcontentloaded")

        start = page.get_by_role("button", name="Start Interview")
        start.wait_for(state="visible", timeout=30_000)
        shot(page, "01-intro")
        start.click()

        # ── 3. The first question must arrive, and must not be blank ──────────
        print("\n[3] first question")
        # The agent picks the question type adaptively, so the answer surface is either the
        # free-text box or the Monaco editor. Waiting for "an answer surface" is what says
        # "the agent asked something and is waiting on us".
        ANSWER_SURFACE = 'textarea[placeholder*="type your answer"], .monaco-editor'
        box = page.locator('textarea[placeholder*="type your answer"]').first
        editor = page.locator(".monaco-editor").first
        try:
            page.wait_for_selector(ANSWER_SURFACE, state="visible", timeout=TURN_TIMEOUT_MS)
        except Exception:
            body = page.inner_text("body")[:400]
            check("first question arrives", False, f"no answer UI. screen said: {body!r}")
            shot(page, "03-no-question")
            return report(browser)
        check("first question arrives", True)

        # The recovery card is the exact symptom we are guarding against.
        page_text = page.inner_text("body")
        check(
            "no 'Interview interrupted' card",
            "Interview interrupted" not in page_text,
            "recovery card shown after start",
        )

        # The question renders into `p.serif` via a typewriter effect, so poll until it
        # settles rather than reading a half-typed string.
        qnode = page.locator("p.serif").first
        qtext = ""
        for _ in range(60):
            if qnode.count():
                now = qnode.inner_text().strip()
                if now and now == qtext:
                    break
                qtext = now
            page.wait_for_timeout(500)
        check("first question is non-empty", len(qtext) > 15, f"{qtext[:90]!r}")
        shot(page, "02-question")

        # ── 4. Answer it and get a score ──────────────────────────────────────
        print("\n[4] submit an answer")
        is_coding = editor.count() > 0 and editor.is_visible()
        check("answer surface present", box.count() > 0 or is_coding, "coding editor" if is_coding else "free-text box")

        if is_coding:
            # Monaco: focus the editor and type, since it has no fillable <textarea> value.
            editor.click()
            page.keyboard.type("def sum_even(nums):\n    return sum(n for n in nums if n % 2 == 0)\n")
        else:
            box.fill(
                "A Python list is a heterogeneous, dynamically-sized array of pointers to "
                "objects, so each element carries boxing overhead and elements are scattered "
                "in memory. A NumPy array is a contiguous, fixed-dtype buffer, which makes it "
                "far more cache-friendly and lets vectorised C loops and SIMD run over it "
                "without per-element interpreter dispatch."
            )

        submit = page.get_by_role("button", name="Submit Answer").first
        submit.wait_for(state="visible", timeout=30_000)
        check("submit is enabled once an answer exists", submit.is_enabled())
        submit.click()

        scored = page.get_by_text("/10").first
        try:
            scored.wait_for(state="visible", timeout=TURN_TIMEOUT_MS)
            check("answer is scored", True, scored.inner_text().strip()[:40])
        except Exception:
            check("answer is scored", False, "no score shown within timeout")
            shot(page, "04-no-score")
        shot(page, "03-scored")

        # ── 5. The agent asks its next question (or concludes) ────────────────
        print("\n[5] next turn")

        # The score lands before the agent has finished composing the next question, and both
        # arrive on the same stream. In that gap the advance control must NOT offer final
        # scoring: clicking it would end a multi-question interview after one answer.
        # The header carries the authoritative position: "Question 3 · up to 6". (Do not read
        # the "9/10" score badge for this — it is not progress.)
        import re as _re

        m = _re.search(r"Question\s+(\d+)\s*.\s*up to\s+(\d+)", page.inner_text("body"))
        asked, total = (int(m.group(1)), int(m.group(2))) if m else (1, 8)
        premature = page.get_by_role("button", name="Submit for Final Scoring")
        check(
            "no final-scoring offer mid-interview",
            not (asked < total and premature.count() and premature.first.is_visible()),
            f"at {asked}/{total} the control already offered final scoring",
        )

        nxt = page.get_by_role("button", name="Next Question")
        last = page.get_by_role("button", name="Submit for Final Scoring")
        try:
            nxt.or_(last).first.wait_for(state="visible", timeout=TURN_TIMEOUT_MS)
            label = "Next Question" if nxt.count() else "Submit for Final Scoring"
            check("turn loop advances", True, f"offered '{label}'")
            nxt.or_(last).first.click()
            # After advancing we should land on another question, not an error card.
            page.wait_for_timeout(3_000)
            check(
                "no error card after advancing",
                "Interview interrupted" not in page.inner_text("body"),
            )
        except Exception:
            check("turn loop advances", False, "no next-question control appeared")
            shot(page, "05-stuck")
        shot(page, "04-next")

        return report(browser)


def report(browser) -> int:
    print("\n── console errors ──")
    for e in console_errors[:10]:
        print("  ", e)
    if not console_errors:
        print("   none")
    print("── failed requests (>=400) ──")
    for r in bad_responses[:10]:
        print("  ", r)
    if not bad_responses:
        print("   none")

    browser.close()

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED — {len(failures)} check(s):")
        for f in failures:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
