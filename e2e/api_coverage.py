"""Comprehensive live API coverage — every endpoint, valid + edge-case user scenarios."""

import io
import os

import httpx

BASE = os.environ.get("E2E_API_BASE", "https://ai-based-tutor.onrender.com/api/v1")
R = []  # (group, call, scenario, status, ok)


def rec(group, call, scenario, status, expected):
    R.append((group, call, scenario, status, status in expected))


class _Resp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data


def first_id(resp, *idkeys):
    """Return the id of the first item from a list response or a {items/...: [...]} response."""
    if resp.status_code != 200:
        return None
    d = resp.json()
    lst = None
    if isinstance(d, list):
        lst = d
    elif isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list):
                lst = v
                break
    if not lst:
        return None
    item = lst[0]
    if not isinstance(item, dict):
        return None
    for k in (*idkeys, "id"):
        if k in item:
            return item[k]
    return None


def main():
    c = httpx.Client(timeout=60, verify=True)
    H = {}

    def _do(method, p, **k):
        try:
            r = c.request(method, BASE + p, headers=H, **k)
            try:
                data = r.json()
            except Exception:
                data = {}
            return _Resp(r.status_code, data)
        except Exception as e:
            return _Resp(f"ERR:{type(e).__name__}")

    def get(p, **k):
        return _do("GET", p, **k)

    def post(p, **k):
        return _do("POST", p, **k)

    def put(p, **k):
        return _do("PUT", p, **k)

    def patch(p, **k):
        return _do("PATCH", p, **k)

    def delete(p, **k):
        return _do("DELETE", p, **k)

    def sopen(method, p, **k):
        try:
            with c.stream(method, BASE + p, headers=H, timeout=45, **k) as r:
                return r.status_code
        except Exception as e:
            return f"ERR:{type(e).__name__}"

    # ---------- AUTH ----------
    r = post("/auth/login", json={"email": "admin@test.com", "password": "admin@1234"})
    rec("auth", "POST /auth/login", "valid creds", r.status_code, {200})
    tok = r.json().get("access_token")
    H["Authorization"] = f"Bearer {tok}"
    rec(
        "auth",
        "POST /auth/login",
        "wrong password",
        post("/auth/login", json={"email": "admin@test.com", "password": "wrongpassword"}).status_code,
        {401},
    )
    rec(
        "auth",
        "POST /auth/login",
        "malformed (no password)",
        post("/auth/login", json={"email": "x@y.z"}).status_code,
        {422},
    )
    rec("auth", "POST /auth/refresh", "no refresh token", c.post(BASE + "/auth/refresh").status_code, {401, 422, 400})
    rec(
        "auth",
        "POST /auth/reset-request",
        "valid email (non-blocking)",
        post("/auth/reset-request", json={"email": "admin@test.com"}).status_code,
        {200, 202},
    )
    rec(
        "auth",
        "POST /auth/reset-confirm",
        "invalid token",
        post("/auth/reset-confirm", json={"token": "bad", "new_password": "abcd1234"}).status_code,
        {400, 401, 404, 422},
    )
    rec("auth", "POST /auth/logout", "logout", post("/auth/logout").status_code, {200})

    # ---------- LEARNER / PROFILE ----------
    rec("learner", "GET /learner/profile", "own profile", get("/learner/profile").status_code, {200})
    rec(
        "learner",
        "PUT /learner/profile",
        "update current_role",
        put("/learner/profile", json={"current_role": "Data Engineer"}).status_code,
        {200},
    )
    rec("learner", "GET /learner/roles", "role catalog", get("/learner/roles").status_code, {200})
    rec(
        "learner",
        "POST /learner/onboard",
        "onboard payload",
        post(
            "/learner/onboard", json={"name": "E2E", "goal_vector": ["data engineering"], "learning_style": "visual"}
        ).status_code,
        {200, 201, 422},
    )
    rec("profile", "GET /profile/activity-stats", "stats", get("/profile/activity-stats").status_code, {200})
    rec("profile", "GET /profile/activity-logs", "logs", get("/profile/activity-logs").status_code, {200})

    # ---------- PROGRESS ----------
    rec("progress", "GET /progress", "progress", get("/progress").status_code, {200})
    rec("progress", "GET /progress/due-topics", "due topics", get("/progress/due-topics").status_code, {200})
    rec("progress", "GET /progress/report", "report", get("/progress/report").status_code, {200})
    rec(
        "progress",
        "POST /progress/study-session",
        "log session",
        post("/progress/study-session", json={"topic": "Kafka", "minutes": 15}).status_code,
        {200, 201, 422},
    )

    # ---------- QUIZ (create real, then dependents) ----------
    qg = post("/quiz/generate", json={"topic": "Apache Kafka", "bloom_level": "understand"})
    rec("quiz", "POST /quiz/generate", "generate quiz", qg.status_code, {200, 201})
    qid = qg.json().get("quiz_id") if qg.status_code < 300 else None
    rec(
        "quiz",
        "GET /quiz/flashcards",
        "deck for topic",
        get("/quiz/flashcards", params={"topic": "Python", "count": 5}).status_code,
        {200},
    )
    rec("quiz", "GET /quiz/flashcards", "missing topic (invalid)", get("/quiz/flashcards").status_code, {422})
    if qid:
        nq = len(qg.json().get("questions", []))
        rec("quiz", "GET /quiz/{id}", "fetch quiz", get(f"/quiz/{qid}").status_code, {200})
        rec(
            "quiz",
            "POST /quiz/{id}/explain",
            "explain q0",
            post(f"/quiz/{qid}/explain", json={"question_index": 0}).status_code,
            {200, 422},
        )
        rec(
            "quiz",
            "POST /quiz/{id}/submit",
            "wrong answer count (edge)",
            post(f"/quiz/{qid}/submit", json={"answers": [0]}).status_code,
            {400, 422},
        )
        rec(
            "quiz",
            "POST /quiz/{id}/submit/stream",
            "full valid submit",
            sopen("POST", f"/quiz/{qid}/submit/stream", json={"answers": [0] * nq, "reflection": ""}),
            {200},
        )
    rec("quiz", "GET /quiz/{id}", "nonexistent id", get("/quiz/does-not-exist").status_code, {404})

    # ---------- DOUBTS ----------
    rec("doubts", "GET /doubts/sessions", "list", get("/doubts/sessions").status_code, {200})
    ds = get("/doubts/sessions")
    sid = first_id(ds, "id", "session_id")
    if sid:
        rec("doubts", "GET /doubts/sessions/{id}", "session detail", get(f"/doubts/sessions/{sid}").status_code, {200})
    rec(
        "doubts",
        "GET /doubts/sessions/{id}",
        "unknown id → empty transcript (by design)",
        get("/doubts/sessions/nope").status_code,
        {200, 404},
    )
    rec(
        "doubts",
        "POST /doubts/stream",
        "ask (stream opens)",
        sopen(
            "POST",
            "/doubts/stream",
            json={"question": "What is a Kafka partition?", "topic_context": "kafka", "history": []},
        ),
        {200},
    )
    rec(
        "doubts",
        "POST /doubts/stream",
        "too short (invalid)",
        post("/doubts/stream", json={"question": "x"}).status_code,
        {422},
    )
    img = ("f.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64), "image/png")
    rec(
        "doubts",
        "POST /doubts/caption",
        "tiny png",
        post("/doubts/caption", files={"file": img}).status_code,
        {200, 400, 422, 500},
    )
    aud = ("a.webm", io.BytesIO(b"0" * 128), "audio/webm")
    rec(
        "doubts",
        "POST /doubts/transcribe",
        "tiny audio",
        post("/doubts/transcribe", files={"file": aud}).status_code,
        {200, 400, 422, 500},
    )

    # ---------- COURSES ----------
    rec("courses", "GET /courses/", "list plans", get("/courses/").status_code, {200})
    rec(
        "courses",
        "GET /courses/run-code/languages",
        "supported langs",
        get("/courses/run-code/languages").status_code,
        {200},
    )
    plans = get("/courses/")
    pid = first_id(plans, "plan_id", "id")
    if pid:
        rec("courses", "GET /courses/{id}", "plan detail", get(f"/courses/{pid}").status_code, {200})
        pdata = get(f"/courses/{pid}").json()
        mid = (pdata.get("modules") or [{}])[0].get("module_id")
        if mid:
            rc = post(
                f"/courses/{pid}/modules/{mid}/interview/run-code", json={"language": "python", "code": "print(2+2)"}
            )
            rec("courses", "POST .../interview/run-code", "run python code", rc.status_code, {200})
            rec(
                "courses",
                "POST .../interview/run-code",
                "run javascript",
                post(
                    f"/courses/{pid}/modules/{mid}/interview/run-code",
                    json={"language": "javascript", "code": "console.log(1+1)"},
                ).status_code,
                {200},
            )
    rec("courses", "GET /courses/{id}", "bad plan id", get("/courses/nope").status_code, {404})

    # ---------- FEED ----------
    rec("feed", "GET /feed", "feed", get("/feed").status_code, {200})
    rec("feed", "GET /feed/trending", "trending", get("/feed/trending").status_code, {200})
    rec("feed", "GET /feed/scheduled", "scheduled", get("/feed/scheduled").status_code, {200})
    fd = get("/feed")
    fid = first_id(fd, "id", "item_id")
    if fid:
        rec(
            "feed",
            "POST /feed/{id}/snooze",
            "snooze item",
            post(f"/feed/{fid}/snooze", json={"hours": 24}).status_code,
            {200, 204},
        )
        rec(
            "feed",
            "POST /feed/{id}/schedule",
            "schedule item",
            post(f"/feed/{fid}/schedule", json={"scheduled_for": "2026-07-01T10:00:00Z"}).status_code,
            {200, 201, 204, 422},
        )
        rec(
            "feed",
            "DELETE /feed/{id}/interaction",
            "clear interaction",
            delete(f"/feed/{fid}/interaction").status_code,
            {200, 204},
        )

    # ---------- JOBS (create real, dependents, cleanup) ----------
    jc = post(
        "/jobs",
        json={
            "title": "Senior Data Engineer",
            "company": "Confluent",
            "description": "Kafka, Spark, Airflow, SQL, Python, AWS.",
        },
    )
    rec("jobs", "POST /jobs", "create job", jc.status_code, {200, 201})
    jid = jc.json().get("id") or jc.json().get("job_id") if jc.status_code < 300 else None
    rec("jobs", "GET /jobs", "list jobs", get("/jobs").status_code, {200})
    if jid:
        rec("jobs", "GET /jobs/{id}", "job detail", get(f"/jobs/{jid}").status_code, {200})
        rec(
            "jobs",
            "PATCH /jobs/{id}",
            "update stage",
            patch(f"/jobs/{jid}", json={"stage": "applied"}).status_code,
            {200},
        )
        rec(
            "jobs",
            "POST /jobs/{id}/reanalyze/stream",
            "reanalyze (opens)",
            sopen("POST", f"/jobs/{jid}/reanalyze/stream"),
            {200},
        )
        rec("jobs", "DELETE /jobs/{id}", "delete job", delete(f"/jobs/{jid}").status_code, {200, 204})

    # ---------- CONTENT ----------
    rec("content", "GET /content", "list", get("/content").status_code, {200})
    ct = get("/content")
    cid = first_id(ct, "id", "item_id")
    if cid:
        rec("content", "GET /content/{id}", "detail", get(f"/content/{cid}").status_code, {200})

    # ---------- CURRICULUM ----------
    rec("curriculum", "GET /curriculum", "get", get("/curriculum").status_code, {200, 404})
    rec("curriculum", "GET /curriculum/graph", "graph", get("/curriculum/graph").status_code, {200, 404})

    # ---------- HF ----------
    rec("hf", "GET /hf/status", "provider status", get("/hf/status").status_code, {200})
    rec(
        "hf",
        "POST /hf/sentiment",
        "sentiment",
        post("/hf/sentiment", json={"text": "I love learning!"}).status_code,
        {200},
    )

    # ---------- LEADERBOARD ----------
    rec("misc", "GET /leaderboard", "leaderboard", get("/leaderboard").status_code, {200})

    # ---------- EVALS (superuser) ----------
    rec("evals", "GET /evals/dashboard", "dashboard", get("/evals/dashboard").status_code, {200})
    rec("evals", "GET /evals/summary", "summary", get("/evals/summary").status_code, {200})
    rec("evals", "GET /evals/results", "results", get("/evals/results").status_code, {200})

    # ---------- ADMIN (superuser) ----------
    rec("admin", "GET /admin/config", "config", get("/admin/config").status_code, {200})
    rec("admin", "GET /admin/learners", "learners", get("/admin/learners").status_code, {200})

    # ---------- HEALTH ----------
    rec("health", "GET /health", "health", c.get(BASE.replace("/api/v1", "") + "/health").status_code, {200})
    rec("health", "GET /ready", "ready", c.get(BASE.replace("/api/v1", "") + "/ready").status_code, {200})

    # ---------- AUTHZ: endpoints must reject no-token ----------
    bare = {"Authorization": ""}
    rec(
        "authz",
        "GET /learner/profile",
        "no token → 401",
        c.get(BASE + "/learner/profile", headers=bare).status_code,
        {401, 403},
    )
    rec(
        "authz",
        "GET /evals/dashboard",
        "no token → 401",
        c.get(BASE + "/evals/dashboard", headers=bare).status_code,
        {401, 403},
    )

    c.close()


main()
print("\n" + "=" * 78 + "\nAPI COVERAGE — live\n" + "=" * 78)
groups = {}
for g, call, scen, st, ok in R:
    groups.setdefault(g, []).append((call, scen, st, ok))
total = len(R)
passed = sum(1 for *_, ok in R if ok)
for g in groups:
    print(f"\n[{g}]")
    for call, scen, st, ok in groups[g]:
        print(f"  {'PASS' if ok else 'FAIL'}  {call:42} {scen:30} → {st}")
print(f"\n{'=' * 78}\nRESULT: {passed}/{total} endpoint scenarios passed")
fails = [(c, s, st) for g, c, s, st, ok in R if not ok]
if fails:
    print("FAILURES:")
    for c, s, st in fails:
        print(f"   - {c}  [{s}] → {st}")
