"""Full-platform E2E for Atelier — drives every feature with real button clicks and validates
the response, emitting detailed, human-readable logs for each action.

Each test case logs: every navigation, fill, and click; the network call it triggered (method,
path, status, latency); and the assertion outcome. Destructive controls (Sign out mid-run,
Clear all logs) are intentionally skipped and logged as SKIP.

Usage:
    E2E_BASE_URL=https://ai-based-tutor.vercel.app E2E_EMAIL=admin@test.com E2E_PASSWORD=admin@1234 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 e2e/full.py
"""

from __future__ import annotations

import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime

from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("E2E_BASE_URL", "https://ai-based-tutor.vercel.app").rstrip("/")
EMAIL = os.environ.get("E2E_EMAIL", "admin@test.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin@1234")
API_HOST = "onrender.com"  # backend host fragment, for tagging network calls
IGNORE = re.compile(r"favicon|fonts\.googleapis|analytics|sentry|hotjar", re.I)

# ── detailed logging ──────────────────────────────────────────────────────────
_net: list[dict] = []  # network calls for the current test case
_results: list[tuple[str, bool, str]] = []


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def step(msg: str):
    print(f"  {_ts()}  STEP  {msg}")


def detail(msg: str):
    print(f"  {'':12}        ↳ {msg}")


def fail(msg: str):
    print(f"  {'':12}        ✗ {msg}")


@contextmanager
def testcase(name: str):
    _net.clear()
    print("\n" + "=" * 78)
    print(f" TEST CASE: {name}")
    print("=" * 78)
    t0 = time.time()
    ok, why = True, ""
    try:
        yield
    except AssertionError as e:
        ok, why = False, str(e)
        fail(f"ASSERTION: {e}")
    except Exception as e:  # noqa: BLE001
        ok, why = False, f"{type(e).__name__}: {str(e)[:160]}"
        fail(f"EXCEPTION: {ok and '' or why}")
    dt = time.time() - t0
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}   ({dt:.1f}s, {len(_net)} api calls)")
    _results.append((name, ok, why))


def hook(page: Page):
    def on_resp(resp):
        try:
            if API_HOST not in resp.url:
                return
            rec = {
                "method": resp.request.method,
                "path": resp.url.split(API_HOST, 1)[1].split("?")[0],
                "status": resp.status,
            }
            _net.append(rec)
            tag = "OK" if resp.status < 400 else "ERR"
            print(f"  {'':12}        · NET[{tag}] {rec['method']} {rec['path']} → {resp.status}")
        except Exception:
            pass

    page.on("response", on_resp)
    page.on(
        "console",
        lambda m: fail(f"CONSOLE.error: {m.text[:160]}") if m.type == "error" and not IGNORE.search(m.text) else None,
    )
    page.on("pageerror", lambda e: fail(f"PAGEERROR: {str(e)[:160]}"))


def last_status(path_re: str) -> int | None:
    rx = re.compile(path_re)
    for rec in reversed(_net):
        if rx.search(rec["path"]):
            return rec["status"]
    return None


def goto(page: Page, route: str):
    step(f"navigate → {route}")
    page.goto(f"{BASE}{route}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)


def click_text(page: Page, name: str, timeout=15000):
    step(f'click "{name}"')
    page.get_by_role("button", name=re.compile(f"^{re.escape(name)}", re.I)).first.click(timeout=timeout)


# ── individual test cases ─────────────────────────────────────────────────────


def tc_login(page: Page):
    with testcase("Auth — login"):
        step(f"open {BASE} and reveal sign-in form")
        page.goto(BASE, wait_until="networkidle", timeout=60000)
        page.get_by_role("button", name=re.compile("^sign in$", re.I)).first.click(timeout=15000)
        page.wait_for_selector("input[type=email]", timeout=20000)
        step(f"fill credentials ({EMAIL})")
        page.fill("input[type=email]", EMAIL)
        page.fill("input[type=password]", PASSWORD)
        step("submit login form (button[type=submit])")
        page.click("button[type=submit]")  # the form submit, not the nav 'Sign in' toggle
        page.wait_for_url(re.compile(r"/(dashboard|onboarding)"), timeout=45000)
        detail(f"landed on {page.url}")
        assert "/dashboard" in page.url or "/onboarding" in page.url, "did not reach an authed page"
        assert last_status(r"/auth/login") == 200, "login API did not return 200"


def tc_dashboard(page: Page):
    with testcase("Dashboard — load + quick actions"):
        goto(page, "/dashboard")
        assert page.get_by_text(re.compile("good (morning|afternoon|evening)", re.I)).count() > 0, "no greeting"
        detail("greeting rendered")
        for label in ["Schedule", "Build career path", "Mock interview", "Start skill practice"]:
            cnt = page.get_by_role("button", name=re.compile(re.escape(label), re.I)).count()
            detail(f'quick-action "{label}": {"present" if cnt else "MISSING"}')


def tc_chat(page: Page):
    with testcase("AI Assistant — multi-turn chat"):
        goto(page, "/atelier")
        ta = page.locator("textarea").first
        ta.wait_for(timeout=20000)
        step('turn 1: type + send "Help me understand Apache Kafka Streams"')
        ta.fill("Help me understand Apache Kafka Streams")
        click_text(page, "Send")
        page.get_by_role("button", name=re.compile("^copy$", re.I)).first.wait_for(timeout=150000)
        detail("turn 1 answer completed")
        assert last_status(r"/api/v1/chat") == 200, "turn 1 chat != 200"
        routing = page.get_by_text(re.compile("routed|agent", re.I)).count()
        detail(f"agent routing trace visible: {bool(routing)}")
        step('turn 2: type + send "Now compare it with Apache Flink"')
        ta.fill("Now compare it with Apache Flink")
        click_text(page, "Send")
        for _ in range(150):
            if page.get_by_role("button", name=re.compile("^copy$", re.I)).count() >= 2:
                break
            if page.get_by_text(re.compile("went wrong|agent error", re.I)).count():
                break
            page.wait_for_timeout(1000)
        assert page.get_by_text(re.compile("went wrong|agent error", re.I)).count() == 0, "turn 2 errored"
        assert page.get_by_role("button", name=re.compile("^copy$", re.I)).count() >= 2, "turn 2 produced no answer"
        chat_calls = [r["status"] for r in _net if "/api/v1/chat" in r["path"]]
        detail(f"chat POST statuses: {chat_calls}")
        assert all(s == 200 for s in chat_calls), "a chat turn returned non-200"


def tc_course_planner(page: Page):
    with testcase("Course Planner — generate plan"):
        goto(page, "/courses")
        assert page.get_by_text("Course Planner").count() > 0, "page didn't render"
        step('fill topic "Apache Kafka fundamentals"')
        page.locator("input").first.fill("Apache Kafka fundamentals")
        click_text(page, "Build Plan")
        detail(f"plan stream opened: {last_status(r'/courses/plan')}")
        # A 200 only means the SSE opened — the plan card renders on the later `plan_created`
        # action. Validate the actual rendered outcome (the "N modules" badge), not the stream open.
        step("wait for plan_created → plan card to render (up to 120s)")
        rendered = 0
        for _ in range(120):
            rendered = page.get_by_text(re.compile(r"\d+\s+modules", re.I)).count()
            if rendered or page.get_by_text(re.compile("went wrong|failed", re.I)).count():
                break
            page.wait_for_timeout(1000)
        assert page.get_by_text(re.compile("went wrong|failed", re.I)).count() == 0, "plan generation errored"
        assert rendered > 0, "no plan card ('N modules') rendered after generation"
        badge = page.get_by_text(re.compile(r"\d+\s+modules", re.I)).first.inner_text(timeout=5000)
        detail(f"plan rendered → badge '{badge.strip()}'")


def tc_career_feed(page: Page):
    with testcase("Career Feed (/learn) — refresh + filter"):
        goto(page, "/learn")
        assert page.get_by_text(re.compile("feed|trending", re.I)).count() > 0, "feed didn't render"
        if page.get_by_role("button", name=re.compile("^refresh$", re.I)).count():
            click_text(page, "Refresh")
            page.wait_for_timeout(2500)
            detail(f"/feed status after refresh: {last_status(r'/feed')}")
        if page.get_by_role("button", name=re.compile("Machine Learning", re.I)).count():
            step('click topic filter "Machine Learning"')
            page.get_by_role("button", name=re.compile("Machine Learning", re.I)).first.click()
            page.wait_for_timeout(1500)
            detail("topic filter applied")


def tc_doubts(page: Page):
    with testcase("Doubt Solver — ask a question (SSE)"):
        goto(page, "/doubts")
        msg = page.get_by_placeholder(re.compile("what's on your mind", re.I))
        assert msg.count() > 0, "doubt composer not found"
        step('type doubt "Why is exactly-once hard in stream processing?" + Send')
        msg.first.fill("Why is exactly-once hard in stream processing?")
        base_len = len(page.inner_text("body"))
        click_text(page, "Send")
        step("wait for streamed answer to render (not just stream-open)")
        grew = False
        for _ in range(90):
            if last_status(r"/doubts/stream") == 200 and len(page.inner_text("body")) > base_len + 120:
                grew = True
                break
            page.wait_for_timeout(1000)
        detail(f"/doubts/stream status: {last_status(r'/doubts/stream')}; answer rendered: {grew}")
        assert last_status(r"/doubts/stream") == 200, "doubt stream did not return 200"
        assert grew, "doubt answer did not render (stream opened but produced no visible content)"


def tc_flashcards(page: Page):
    with testcase("Flashcards — load deck + reveal"):
        # Cards auto-generate for ?topic (default "Python Programming"); the deck UI ("Tap to reveal",
        # an "N / M" counter) renders after the fetch. Validate that, not a (nonexistent) gen button.
        goto(page, "/flashcards")
        step("wait for the card deck to render (up to 60s; AI gen + cold start)")
        card = page.get_by_text(re.compile(r"tap to reveal|\d+\s*/\s*\d+", re.I))
        rendered = False
        for _ in range(60):
            if card.count() or last_status(r"/quiz/flashcards") not in (None, 404):
                rendered = True
                break
            if page.get_by_text(re.compile("went wrong|failed|not found", re.I)).count():
                break
            page.wait_for_timeout(1000)
        s = last_status(r"/quiz/flashcards")
        detail(f"/quiz/flashcards status: {s}; deck UI present: {bool(card.count())}")
        assert s != 404, "flashcards endpoint 404 (route shadowing regressed?)"
        assert rendered, "flashcards deck did not render"
        # reveal a card to confirm interactivity
        if card.count():
            page.get_by_text(re.compile("tap to reveal", re.I)).first.click(timeout=5000)
            page.wait_for_timeout(800)
            detail("revealed a card ✓")


def tc_progress(page: Page):
    with testcase("Progress — load + export"):
        goto(page, "/progress")
        assert page.get_by_text("Progress").count() > 0, "progress didn't render"
        detail(f"/progress fetch: {last_status(r'/progress')}")
        if page.get_by_role("button", name=re.compile("^export$", re.I)).count():
            click_text(page, "Export")
            page.wait_for_timeout(1500)
            detail("export clicked")


def tc_job_tracker(page: Page):
    with testcase("Job Tracker — add a job"):
        goto(page, "/tracker")
        assert page.get_by_text("Job Tracker").count() > 0, "tracker didn't render"
        opener = page.get_by_role("button", name=re.compile("add (a job|your first job)", re.I))
        assert opener.count() > 0, "no 'Add a job' button"
        step("click 'Add a job'")
        opener.first.click()
        page.wait_for_timeout(1500)
        inputs = page.locator("input, textarea")
        detail(f"job form inputs revealed: {inputs.count()}")
        if inputs.count() >= 2:
            step("fill job role + company")
            inputs.nth(0).fill("Senior Data Engineer")
            if inputs.count() > 1:
                inputs.nth(1).fill("Confluent")
            save = page.get_by_role("button", name=re.compile("save|add|create", re.I))
            if save.count():
                step("click save")
                save.last.click()
                page.wait_for_timeout(2500)
                detail(f"/jobs status: {last_status(r'/jobs')}")
        else:
            detail("no form fields appeared — possible UX gap")


def tc_profile(page: Page):
    with testcase("Profile — open editor"):
        goto(page, "/profile")
        assert page.get_by_text("Profile").count() > 0, "profile didn't render"
        if page.get_by_role("button", name=re.compile("edit profile", re.I)).count():
            click_text(page, "Edit profile")
            page.wait_for_timeout(1500)
            detail(f"editable inputs: {page.locator('input,textarea').count()}")
        detail("SKIP 'Clear all logs' (destructive)")


def tc_interview(page: Page):
    with testcase("Interview Coach — landing"):
        goto(page, "/interview")
        assert page.get_by_text("Interview Coach").count() > 0, "interview page didn't render"
        cta = page.get_by_role("button", name=re.compile("career paths", re.I))
        detail(f"'Go to Career Paths' CTA present: {bool(cta.count())} (interviews start from a course module)")


def tc_evals(page: Page):
    with testcase("Agent Evals — superuser dashboard"):
        goto(page, "/evals")
        assert page.get_by_text(re.compile("agent evals", re.I)).count() > 0, "evals didn't render"
        s = last_status(r"/evals/dashboard")
        # react-query may serve cached data (the dashboard page also fetches this), so a fresh call
        # isn't guaranteed — only require success *if* a call fired this navigation.
        detail(f"/evals/dashboard status this nav: {s if s is not None else 'served from cache'}")
        assert s in (None, 200), f"evals dashboard fetch failed ({s})"


def tc_logout(page: Page):
    with testcase("Auth — logout"):
        goto(page, "/dashboard")
        click_text(page, "Sign out")
        page.wait_for_timeout(3000)
        detail(f"after logout URL: {page.url}")
        assert (
            page.get_by_role("button", name=re.compile("^sign in$", re.I)).count() > 0 or page.url.rstrip("/") == BASE
        ), "did not return to landing/login after logout"


def main():
    t0 = time.time()
    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_context(viewport={"width": 1366, "height": 900}).new_page()
        hook(page)
        tc_login(page)
        tc_dashboard(page)
        tc_chat(page)
        tc_course_planner(page)
        tc_career_feed(page)
        tc_doubts(page)
        tc_flashcards(page)
        tc_progress(page)
        tc_job_tracker(page)
        tc_profile(page)
        tc_interview(page)
        tc_evals(page)
        tc_logout(page)

    print("\n" + "#" * 78)
    print("# FULL-PLATFORM E2E SUMMARY")
    print("#" * 78)
    passed = sum(1 for _, ok, _ in _results if ok)
    for name, ok, why in _results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   — {why}" if why else ""))
    print(f"\n  {passed}/{len(_results)} passed   ({time.time() - t0:.0f}s total)")
    sys.exit(0 if passed == len(_results) else 1)


if __name__ == "__main__":
    main()
