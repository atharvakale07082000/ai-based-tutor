"""Live browser E2E smoke test for Atelier (frontend + backend together).

Logs in, runs a multi-turn chat, and loads every authenticated route while capturing console
errors, page errors, and failed (>=400) network requests — then prints a per-route report.

Usage:
    pip install playwright httpx && playwright install chromium
    E2E_BASE_URL=https://ai-based-tutor.vercel.app \
    E2E_EMAIL=admin@test.com E2E_PASSWORD=admin@1234 \
    python e2e/smoke.py

All inputs are env-configurable (defaults target the live site + the superuser dev account).
Exit code is non-zero if any route reports an issue, so it can gate CI.
"""

import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("E2E_BASE_URL", "https://ai-based-tutor.vercel.app").rstrip("/")
EMAIL = os.environ.get("E2E_EMAIL", "admin@test.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin@1234")

ROUTES = [
    "/dashboard",
    "/atelier",
    "/courses",
    "/learn",
    "/doubts",
    "/progress",
    "/flashcards",
    "/profile",
    "/interview",
    "/tracker",
    "/evals",
]
IGNORE = re.compile(r"favicon|fonts\.googleapis|analytics|sentry|hotjar", re.I)

report: dict[str, list[str]] = {}
chat_posts: list[int] = []


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1366, "height": 900}).new_page()
        current = {"route": "/login"}

        def note(msg):
            report.setdefault(current["route"], []).append(msg)

        page.on(
            "console",
            lambda m: (
                note(f"CONSOLE.error: {m.text[:200]}") if m.type == "error" and not IGNORE.search(m.text) else None
            ),
        )
        page.on("pageerror", lambda e: note(f"PAGEERROR: {str(e)[:200]}"))

        def on_response(resp):
            try:
                if resp.status >= 400 and not IGNORE.search(resp.url):
                    note(f"HTTP {resp.status}: {resp.request.method} {resp.url.split('?')[0]}")
                if "/api/v1/chat" in resp.url:
                    chat_posts.append(resp.status)
            except Exception:
                pass

        page.on("response", on_response)

        # Login (form is revealed by the "Sign in" button on the landing page)
        print("→ login")
        page.goto(BASE, wait_until="networkidle", timeout=60000)
        page.get_by_role("button", name=re.compile("^sign in$", re.I)).first.click(timeout=15000)
        page.wait_for_selector("input[type=email]", timeout=20000)
        page.fill("input[type=email]", EMAIL)
        page.fill("input[type=password]", PASSWORD)
        page.click("button[type=submit]")
        try:
            page.wait_for_url(lambda u: "/login" not in u and u.rstrip("/") != BASE, timeout=45000)
        except Exception:
            page.wait_for_timeout(5000)
        print(f"  after login: {page.url}")

        # Multi-turn chat
        print("→ multi-turn chat")
        current["route"] = "/atelier"
        try:
            page.goto(f"{BASE}/atelier", wait_until="domcontentloaded", timeout=60000)
            ta = page.locator("textarea").first

            def send():
                page.get_by_role("button", name=re.compile("send", re.I)).first.click(timeout=15000)

            def copies():
                return page.get_by_role("button", name=re.compile("^copy$", re.I)).count()

            ta.fill("Help me understand Apache Kafka Streams")
            send()
            page.get_by_role("button", name=re.compile("^copy$", re.I)).first.wait_for(timeout=150000)
            ta.fill("Now compare it with Apache Flink")
            send()
            for _ in range(150):
                if copies() >= 2 or page.get_by_text(re.compile("went wrong|agent error", re.I)).count():
                    break
                page.wait_for_timeout(1000)
            if page.get_by_text(re.compile("went wrong|agent error", re.I)).count():
                note("MULTI-TURN: 2nd turn showed an error toast")
            elif copies() < 2:
                note("MULTI-TURN: 2nd turn produced no completed answer")
        except Exception as e:
            note(f"MULTI-TURN: exception {str(e)[:200]}")

        # Route smoke
        for route in ROUTES:
            if route == "/atelier":
                continue
            current["route"] = route
            print(f"→ {route}")
            try:
                page.goto(f"{BASE}{route}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3500)
            except Exception as e:
                note(f"NAV: exception {str(e)[:200]}")
        browser.close()


if __name__ == "__main__":
    t0 = time.time()
    run()
    print("\n" + "=" * 64 + f"\nE2E REPORT — {BASE}\n" + "=" * 64)
    clean = True
    for route in ["/login", "/atelier", *[r for r in ROUTES if r != "/atelier"]]:
        issues = list(dict.fromkeys(report.get(route, [])))
        if issues:
            clean = False
            print(f"\n[{route}]  {len(issues)} issue(s):")
            for i in issues:
                print(f"   - {i}")
        else:
            print(f"[{route}]  OK")
    print(f"\nchat POST statuses: {chat_posts}")
    print(f"\nRESULT: {'no issues detected' if clean else 'ISSUES FOUND'}  ({time.time() - t0:.0f}s)")
    sys.exit(0 if clean else 1)
