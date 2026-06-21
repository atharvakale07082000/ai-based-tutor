"""
Full API test suite for ai-tutor backend.
Tests every route: auth → learner → agents → content → quiz → progress → feed → misc.
Generates a markdown report at /tmp/api_test_report.md
Run: PYTHONPATH=. uv run python scripts/api_test_report.py
"""

import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx

BASE = "http://localhost:8000"
TIMEOUT = 60  # seconds — LLM endpoints can be slow

# ── Test result container ─────────────────────────────────────────────────────


@dataclass
class Result:
    name: str
    method: str
    url: str
    status: int | str
    passed: bool
    latency_ms: int
    notes: str = ""
    response_snippet: str = ""


results: list[Result] = []


def record(
    name: str,
    method: str,
    url: str,
    status: int | str,
    passed: bool,
    latency_ms: int,
    notes: str = "",
    snippet: str = "",
) -> Result:
    r = Result(
        name=name,
        method=method,
        url=url,
        status=status,
        passed=passed,
        latency_ms=latency_ms,
        notes=notes,
        response_snippet=snippet,
    )
    results.append(r)
    icon = "✅" if passed else "❌"
    print(f"  {icon}  {name:55s}  {status}  {latency_ms}ms  {notes or ''}")
    return r


def call(
    client: httpx.Client,
    method: str,
    path: str,
    name: str,
    expect: int = 200,
    snippet_keys: list[str] | None = None,
    **kwargs,
) -> tuple[httpx.Response | None, bool]:
    url = BASE + path
    t0 = time.monotonic()
    try:
        resp = client.request(method, url, timeout=TIMEOUT, **kwargs)
        ms = int((time.monotonic() - t0) * 1000)
        passed = resp.status_code == expect
        notes = "" if passed else f"expected {expect}"
        try:
            body = resp.json()
            if snippet_keys and isinstance(body, dict):
                snip = {k: body.get(k) for k in snippet_keys if k in body}
            else:
                snip = body
            snippet = json.dumps(snip, default=str)[:200]
        except Exception:
            snippet = resp.text[:200]
        record(name, method, url, resp.status_code, passed, ms, notes, snippet)
        return resp, passed
    except httpx.TimeoutException:
        ms = int((time.monotonic() - t0) * 1000)
        record(name, method, url, "TIMEOUT", False, ms, "request timed out")
        return None, False
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        record(name, method, url, "ERR", False, ms, str(e)[:120])
        return None, False


def call_sse(client: httpx.Client, path: str, name: str, json_body: dict) -> tuple[list[dict], bool, int]:
    """Stream an SSE endpoint; collect all events; return (events, passed, ms).

    Handles two SSE formats used in this backend:
    - v1 doubts: {'token': '...'} + bare 'data: [DONE]'
    - v2/v3/assistant: {'type': 'token'|'done'|'routing'|..., ...} structured events
    """
    url = BASE + path
    events: list[dict] = []
    done_seen = False
    t0 = time.monotonic()
    try:
        with client.stream("POST", url, json=json_body, timeout=TIMEOUT) as resp:
            if resp.status_code != 200:
                body_text = resp.read().decode(errors="replace")[:200]
                ms = int((time.monotonic() - t0) * 1000)
                record(name, "POST", url, resp.status_code, False, ms, "expected 200", body_text)
                return [], False, ms
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                # bare [DONE] sentinel used by doubts/stream
                if payload.strip() == "[DONE]":
                    done_seen = True
                    events.append({"type": "done"})
                    continue
                try:
                    obj = json.loads(payload)
                    # Normalise v1 doubts format: {'token': '...'} → {'type': 'token', 'content': '...'}
                    if isinstance(obj, dict) and "token" in obj and "type" not in obj:
                        obj = {"type": "token", "content": obj["token"]}
                    if isinstance(obj, dict) and obj.get("type") == "done":
                        done_seen = True
                    events.append(obj)
                except Exception:
                    pass
        ms = int((time.monotonic() - t0) * 1000)
        has_done = done_seen or any(e.get("type") == "done" for e in events)
        has_token = any(e.get("type") == "token" for e in events)
        passed = has_done and len(events) > 0
        types_seen = sorted({e.get("type", "?") for e in events})
        snippet = json.dumps(
            {"events": len(events), "types": types_seen, "has_token": has_token, "has_done": has_done}
        )[:200]
        notes = "" if passed else "no done event received"
        r = Result(
            name=name,
            method="POST",
            url=url,
            status=200,
            passed=passed,
            latency_ms=ms,
            notes=notes,
            response_snippet=snippet,
        )
        results.append(r)
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {name:55s}  200  {ms}ms  events={len(events)} types={types_seen}")
        return events, passed, ms
    except httpx.TimeoutException:
        ms = int((time.monotonic() - t0) * 1000)
        record(name, "POST", url, "TIMEOUT", False, ms, "request timed out")
        return [], False, ms
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        record(name, "POST", url, "ERR", False, ms, str(e)[:120])
        return [], False, ms


# ── Main test runner ──────────────────────────────────────────────────────────


def run():
    print(f"\n{'=' * 70}")
    print("  AI TUTOR — Full API Test Suite")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}\n")

    client = httpx.Client(follow_redirects=True)

    # ── 0. Health checks ──────────────────────────────────────────────────────
    print("── Health Checks ─────────────────────────────────────────────────")
    call(client, "GET", "/health", "GET /health")
    call(client, "GET", "/ready", "GET /ready")

    # ── 1. Auth ───────────────────────────────────────────────────────────────
    # POST /auth/login auto-creates the user on the first call (upsert behaviour).
    print("\n── Auth ──────────────────────────────────────────────────────────")
    test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    test_password = "TestPass123"  # >= 6 chars

    login_resp, login_ok = call(
        client,
        "POST",
        "/api/v1/auth/login",
        "POST /auth/login  [auto-register + login]",
        expect=200,
        json={"email": test_email, "password": test_password},
        snippet_keys=["access_token", "user"],
    )
    token = ""
    if login_ok and login_resp:
        token = login_resp.json().get("access_token", "")

    # Second call — must succeed (idempotent)
    login2_resp, _ = call(
        client,
        "POST",
        "/api/v1/auth/login",
        "POST /auth/login  [same user — idempotent]",
        expect=200,
        json={"email": test_email, "password": test_password},
        snippet_keys=["access_token"],
    )
    if login2_resp and login2_resp.status_code == 200:
        token = login2_resp.json().get("access_token", token)

    # Wrong password must be rejected
    call(
        client,
        "POST",
        "/api/v1/auth/login",
        "POST /auth/login  [wrong password → 401]",
        expect=401,
        json={"email": test_email, "password": "wrongpassword"},
    )

    auth_headers = {"Authorization": f"Bearer {token}"}
    authed = httpx.Client(headers=auth_headers, follow_redirects=True)

    call(authed, "POST", "/api/v1/auth/refresh", "POST /auth/refresh", expect=200, snippet_keys=["access_token"])

    # ── 2. Learner ────────────────────────────────────────────────────────────
    print("\n── Learner ───────────────────────────────────────────────────────")
    call(
        authed,
        "POST",
        "/api/v1/learner/onboard",
        "POST /learner/onboard  [name + goals]",
        expect=200,
        json={
            "name": "Test Runner",
            "goals": ["Machine Learning", "Python", "Deep Learning"],
            "hoursPerWeek": 5,
            "difficulty": "balanced",
        },
        snippet_keys=["name"],
    )

    call(
        authed, "GET", "/api/v1/learner/profile", "GET  /learner/profile", snippet_keys=["name", "email", "goal_vector"]
    )

    call(
        authed,
        "PUT",
        "/api/v1/learner/profile",
        "PUT  /learner/profile  [update name]",
        json={"name": "Test Runner Updated"},
    )

    # ── 3. Curriculum ─────────────────────────────────────────────────────────
    print("\n── Curriculum ────────────────────────────────────────────────────")
    call(authed, "GET", "/api/v1/curriculum", "GET  /curriculum", snippet_keys=["topics", "total"])
    call(authed, "GET", "/api/v1/curriculum/graph", "GET  /curriculum/graph", snippet_keys=["nodes", "edges"])
    call(
        authed,
        "POST",
        "/api/v1/curriculum/generate",
        "POST /curriculum/generate  [ML fundamentals]",
        json={"goal": "Learn machine learning fundamentals"},
        snippet_keys=["topics", "goal"],
    )

    # ── 4. Content ────────────────────────────────────────────────────────────
    print("\n── Content ───────────────────────────────────────────────────────")
    content_resp, _ = call(authed, "GET", "/api/v1/content", "GET  /content", snippet_keys=["total", "items"])
    content_id = ""
    if content_resp and content_resp.status_code == 200:
        items = content_resp.json().get("items", [])
        if items:
            content_id = items[0].get("id", "")

    if content_id:
        call(
            authed,
            "GET",
            f"/api/v1/content/{content_id}",
            "GET  /content/{id}",
            snippet_keys=["title", "topic", "body"],
        )
        call(authed, "POST", f"/api/v1/content/{content_id}/regenerate", "POST /content/{id}/regenerate")
    else:
        print("  ⚠️   No content items found — skipping /content/{id} tests")

    # ── 5. Quiz ───────────────────────────────────────────────────────────────
    print("\n── Quiz ──────────────────────────────────────────────────────────")
    quiz_resp, quiz_ok = call(
        authed,
        "POST",
        "/api/v1/quiz/generate",
        "POST /quiz/generate  [Python list comprehensions]",
        json={"topic": "Python list comprehensions", "bloom_level": "understand"},
        snippet_keys=["quiz_id", "topic", "questions"],
    )
    quiz_id = ""
    if quiz_ok and quiz_resp:
        quiz_id = quiz_resp.json().get("quiz_id", "")

    if quiz_id:
        call(authed, "GET", f"/api/v1/quiz/{quiz_id}", "GET  /quiz/{quiz_id}", snippet_keys=["topic", "questions"])
        call(
            authed,
            "POST",
            f"/api/v1/quiz/{quiz_id}/submit",
            "POST /quiz/{quiz_id}/submit",
            json={"answers": [0, 1, 0, 2, 1]},
        )

    # flashcards uses Query params, not JSON body
    call(
        authed,
        "POST",
        "/api/v1/quiz/flashcards",
        "POST /quiz/flashcards  [5 cards via query params]",
        params={"topic": "Python basics", "count": 5},
        snippet_keys=["flashcards"],
    )

    # ── 6. Progress ───────────────────────────────────────────────────────────
    print("\n── Progress ──────────────────────────────────────────────────────")
    call(authed, "GET", "/api/v1/progress", "GET  /progress", snippet_keys=["topics_studied", "xp"])
    call(authed, "GET", "/api/v1/progress/due-topics", "GET  /progress/due-topics", snippet_keys=["due"])
    call(authed, "GET", "/api/v1/progress/report", "GET  /progress/report", snippet_keys=["streak", "xp"])
    call(
        authed,
        "POST",
        "/api/v1/progress/study-session",
        "POST /progress/study-session",
        json={"topic": "Python basics", "minutes": 10, "score": 0.8},
    )

    # ── 7. Doubts (streaming) ─────────────────────────────────────────────────
    print("\n── Doubts ────────────────────────────────────────────────────────")
    call(authed, "GET", "/api/v1/doubts/sessions", "GET  /doubts/sessions", snippet_keys=["sessions", "total"])

    call_sse(
        authed,
        "/api/v1/doubts/stream",
        "POST /doubts/stream  [explain backpropagation]",
        {
            "question": "Explain backpropagation in simple terms.",
            "topic_context": "Deep Learning",
            "session_id": uuid.uuid4().hex,
        },
    )

    # ── 8. Feed ───────────────────────────────────────────────────────────────
    print("\n── Feed ──────────────────────────────────────────────────────────")
    feed_resp, _ = call(authed, "GET", "/api/v1/feed", "GET  /feed", snippet_keys=["items", "total"])
    call(authed, "GET", "/api/v1/feed/trending", "GET  /feed/trending", snippet_keys=["topics"])
    call(authed, "GET", "/api/v1/feed/scheduled", "GET  /feed/scheduled", snippet_keys=["items"])

    feed_item_id = ""
    if feed_resp and feed_resp.status_code == 200:
        items = feed_resp.json().get("items", [])
        if items:
            feed_item_id = items[0].get("id", "")
    if feed_item_id:
        from datetime import timedelta, timezone

        scheduled_dt = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        call(
            authed,
            "POST",
            f"/api/v1/feed/{feed_item_id}/schedule",
            "POST /feed/{id}/schedule",
            json={"scheduled_for": scheduled_dt},
        )
        call(authed, "POST", f"/api/v1/feed/{feed_item_id}/snooze", "POST /feed/{id}/snooze", json={"hours": 24})

    # ── 9. Courses ────────────────────────────────────────────────────────────
    print("\n── Courses ───────────────────────────────────────────────────────")
    plan_resp, plan_ok = call(
        authed,
        "POST",
        "/api/v1/courses/plan",
        "POST /courses/plan  [ML in 3 months]",
        json={"goal": "Master machine learning in 3 months"},
        snippet_keys=["plan_id", "title", "modules"],
    )
    plan_id = ""
    if plan_ok and plan_resp:
        plan_id = plan_resp.json().get("plan_id", "")

    call(authed, "GET", "/api/v1/courses/", "GET  /courses/", snippet_keys=["plans", "total"])
    if plan_id:
        call(authed, "GET", f"/api/v1/courses/{plan_id}", "GET  /courses/{plan_id}", snippet_keys=["title", "modules"])

    # ── 10. Session ───────────────────────────────────────────────────────────
    print("\n── Session ───────────────────────────────────────────────────────")
    sess_resp, sess_ok = call(
        authed,
        "POST",
        "/api/v1/session/start",
        "POST /session/start",
        json={"topic": "Python basics", "goal": "understand"},
        snippet_keys=["session_id", "quiz_questions"],
    )
    # session_id doubles as quiz_id for /session/advance
    quiz_id_for_advance = ""
    if sess_ok and sess_resp:
        quiz_id_for_advance = sess_resp.json().get("session_id", "")
    if quiz_id_for_advance:
        # SessionAdvanceRequest: quiz_id (=session_id), answers (list[int]), reflection
        call(
            authed,
            "POST",
            "/api/v1/session/advance",
            "POST /session/advance  [submit quiz answers]",
            json={"quiz_id": quiz_id_for_advance, "answers": [0, 1, 0, 2, 1], "reflection": "Felt good!"},
        )

    # ── 11. HF / Admin ────────────────────────────────────────────────────────
    print("\n── HF / Admin ────────────────────────────────────────────────────")
    call(authed, "GET", "/api/v1/hf/status", "GET  /hf/status", snippet_keys=["models", "status"])
    call(authed, "GET", "/api/v1/admin/config", "GET  /admin/config")
    call(authed, "GET", "/api/v1/admin/learners", "GET  /admin/learners")

    # ── 12. Evals ─────────────────────────────────────────────────────────────
    print("\n── Evals ─────────────────────────────────────────────────────────")
    call(authed, "GET", "/api/v1/evals/summary", "GET  /evals/summary")
    call(authed, "GET", "/api/v1/evals/results", "GET  /evals/results")

    # ── 13. Profile ───────────────────────────────────────────────────────────
    print("\n── Profile ───────────────────────────────────────────────────────")
    call(authed, "GET", "/api/v1/profile/activity-logs", "GET  /profile/activity-logs", snippet_keys=["logs", "total"])
    call(authed, "GET", "/api/v1/profile/activity-stats", "GET  /profile/activity-stats", snippet_keys=["stats"])

    # ── 14. Leaderboard ───────────────────────────────────────────────────────
    print("\n── Leaderboard ───────────────────────────────────────────────────")
    call(authed, "GET", "/api/v1/leaderboard", "GET  /leaderboard", snippet_keys=["entries", "rank"])

    # ── 15. Agent: v1 Assistant (SSE) ─────────────────────────────────────────
    print("\n── Agent: v1 Assistant (SSE) ─────────────────────────────────────")
    call_sse(
        authed,
        "/api/v1/assistant/chat",
        "POST /assistant/chat  [gradient descent]",
        {"message": "What is gradient descent in simple terms?", "history": []},
    )

    # ── 16. Agent: v2 Chat (SSE + routing) ────────────────────────────────────
    print("\n── Agent: v2 Chat (SSE + routing trace) ─────────────────────────")
    v2_events, _, _ = call_sse(
        authed,
        "/api/v2/chat",
        "POST /v2/chat  [explain transformers]",
        {"message": "Can you explain how transformer models work?", "session_id": uuid.uuid4().hex, "context": {}},
    )
    routing_v2 = next((e for e in v2_events if e.get("type") == "routing"), None)
    if routing_v2:
        print(f"        v2 routed → {routing_v2.get('display_name', routing_v2.get('agent', '?'))}")

    # ── 17. Agent: v3 DeepAgent (SSE + CoT, all 4 sub-agents) ────────────────
    print("\n── Agent: v3 DeepAgent (SSE + CoT, all sub-agents) ──────────────")
    v3_queries = [
        ("doubt", "Explain what backpropagation does in a neural network."),
        ("quiz", "Quiz me on Python list comprehensions with 3 questions."),
        ("curriculum", "Create a learning path for someone new to data science."),
        ("progress", "How is my learning going? What should I focus on next?"),
    ]
    for agent_label, query in v3_queries:
        events, _, _ = call_sse(
            authed,
            "/api/v3/chat",
            f"POST /v3/chat  [{agent_label}]",
            {"message": query, "session_id": uuid.uuid4().hex, "context": {}},
        )
        cot_steps = sum(1 for e in events if e.get("type") == "cot_step")
        routing = next((e for e in events if e.get("type") == "routing"), None)
        display = routing.get("display_name", routing.get("agent", "?")) if routing else "no routing event"
        print(f"        routed→{display}  cot_steps={cot_steps}")
        time.sleep(2)  # throttle — respect LLM rate limits

    # ── 18. Auth: Logout (invalidates token — must be last) ───────────────────
    print("\n── Auth: Logout ──────────────────────────────────────────────────")
    call(authed, "POST", "/api/v1/auth/logout", "POST /auth/logout", expect=200)
    # JWT is stateless — logout clears client-side token only; server still honours
    # the existing token until it expires. Expect 200 (not 401).
    call(authed, "GET", "/api/v1/learner/profile", "GET  /learner/profile  [post-logout — JWT still valid]", expect=200)

    generate_report()


# ── Report generator ──────────────────────────────────────────────────────────


def generate_report():
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    avg_ms = int(sum(r.latency_ms for r in results) / total) if total else 0
    slowest = max(results, key=lambda r: r.latency_ms)

    print(f"\n{'=' * 70}")
    print(f"  RESULTS: {passed}/{total} passed  |  {failed} failed  |  avg {avg_ms} ms")
    print(f"{'=' * 70}")

    lines = [
        "# AI Tutor — API Test Report",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Base URL:** `{BASE}`  ",
        f"**Total routes tested:** {total}  ",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Routes tested | **{total}** |",
        f"| ✅ Passed | **{passed}** |",
        f"| ❌ Failed | **{failed}** |",
        f"| Pass rate | **{100 * passed // total if total else 0}%** |",
        f"| Avg latency | **{avg_ms} ms** |",
        f"| Slowest route | `{slowest.method} {slowest.url.replace(BASE, '')}` — {slowest.latency_ms} ms |",
        "",
        "---",
        "",
        "## Route Results",
        "",
        "| # | Test | Status | Latency | Result | Notes |",
        "|---|------|--------|---------|--------|-------|",
    ]

    for i, r in enumerate(results, 1):
        icon = "✅" if r.passed else "❌"
        lines.append(f"| {i} | `{r.name}` | `{r.status}` | {r.latency_ms} ms | {icon} | {r.notes or '—'} |")

    if failed > 0:
        lines += [
            "",
            "---",
            "",
            "## ❌ Failed Routes",
            "",
            "| Route | Status | Reason |",
            "|-------|--------|--------|",
        ]
        for r in results:
            if not r.passed:
                route = r.url.replace(BASE, "")
                lines.append(f"| `{r.method} {route}` | `{r.status}` | {r.notes or r.response_snippet[:80]} |")

    lines += [
        "",
        "---",
        "",
        "## Response Snippets",
        "",
    ]
    for r in results:
        if r.response_snippet:
            lines.append(f"### `{r.name}`")
            lines.append("```json")
            lines.append(r.response_snippet)
            lines.append("```")
            lines.append("")

    report_path = "/tmp/api_test_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"\n  📄  Report saved → {report_path}\n")

    if failed > 0:
        print("  ❌  FAILED ROUTES:")
        for r in results:
            if not r.passed:
                print(f"       {r.method:6} {r.url.replace(BASE, '')}  →  {r.status}  {r.notes}")
    else:
        print("  🎉  All routes passed!")
    print()


if __name__ == "__main__":
    run()
    sys.exit(1 if any(not r.passed for r in results) else 0)
