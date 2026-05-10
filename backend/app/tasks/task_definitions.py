import asyncio
import structlog
from app.tasks.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="app.tasks.task_definitions.regenerate_curriculum", bind=True, max_retries=3)
def regenerate_curriculum(self, learner_id: str | None = None):
    log.info("task_regenerate_curriculum_start", learner_id=learner_id)
    try:
        from app.db.mongo import col_learners
        query = {"id": learner_id} if learner_id else {}
        learners = list(col_learners().find(query, {"_id": 0}).limit(100))
        log.info("curriculum_regenerated", count=len(learners))
    except Exception as exc:
        log.error("task_regenerate_curriculum_error", error=str(exc))
        self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.tasks.task_definitions.process_quiz_results", bind=True, max_retries=3)
def process_quiz_results(self, quiz_session_id: str):
    log.info("task_process_quiz_start", quiz_session_id=quiz_session_id)
    try:
        from app.db.mongo import col_quizzes
        quiz = col_quizzes().find_one({"id": quiz_session_id}, {"_id": 0})
        if quiz and quiz.get("score") is not None:
            log.info("quiz_results_processed", quiz_id=quiz_session_id, score=quiz["score"])
    except Exception as exc:
        log.error("task_process_quiz_error", error=str(exc))
        self.retry(exc=exc, countdown=30)


@celery_app.task(name="app.tasks.task_definitions.send_progress_digest", bind=True, max_retries=3)
def send_progress_digest(self, learner_id: str | None = None):
    """
    Weekly Friday digest: email each learner their progress summary,
    topics mastered, top trending topics in their domains, and due reviews.
    SMTP config is hardcoded — uses Gmail with app-password.
    """
    log.info("task_send_progress_digest_start", learner_id=learner_id)

    # ── Hardcoded SMTP configuration ──────────────────────────────────────────
    SMTP_HOST     = "smtp.gmail.com"
    SMTP_PORT     = 587
    SMTP_USER     = "akale6201@gmail.com"
    SMTP_PASSWORD = "hvwj xhnz ykpl vbrm"   # Gmail app-password (16-char)
    FROM_ADDRESS  = f"Atelier AI Tutor <{SMTP_USER}>"

    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from app.db.mongo import col_learners, col_users, col_quizzes, col_trending_topics

        query = {"id": learner_id} if learner_id else {}
        learners = list(col_learners().find(query, {"_id": 0}).limit(500))

        # Fetch latest trending topics once
        latest_trend = col_trending_topics().find_one({}, {"_id": 0, "discovered_at": 1}, sort=[("discovered_at", -1)])
        trending = []
        if latest_trend:
            trending = list(col_trending_topics().find(
                {"discovered_at": latest_trend["discovered_at"]},
                {"_id": 0, "domain": 1, "subtopic": 1},
            ).limit(5))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)

            sent = 0
            for learner in learners:
                user = col_users().find_one({"id": learner.get("user_id", "")}, {"_id": 0, "email": 1})
                if not user or not user.get("email"):
                    continue

                email = user["email"]
                name = (learner.get("name") or "Learner").split()[0]
                xp = learner.get("xp", 0)
                streak = learner.get("streak", 0)
                proficiency = learner.get("topic_proficiency_map") or {}
                mastered = [t for t, e in proficiency.items() if e >= 700]
                quizzes = list(col_quizzes().find(
                    {"learner_id": learner["id"], "completed_at": {"$ne": None}},
                    {"_id": 0, "score": 1},
                ).sort("completed_at", -1).limit(5))
                avg_score = round(sum(q.get("score", 0) for q in quizzes) / max(len(quizzes), 1) * 100)

                trending_html = "".join(
                    f"<li><b>{t['subtopic']}</b> <span style='color:#888'>({t['domain']})</span></li>"
                    for t in trending
                )
                mastered_html = "".join(f"<li>✅ {t}</li>" for t in mastered[:5]) or "<li>Keep going — mastery at Elo ≥ 700!</li>"

                html = f"""
<html><body style="font-family:Georgia,serif;max-width:560px;margin:auto;color:#2C2416;background:#FDFAF5;padding:32px">
  <div style="font-size:11px;letter-spacing:0.12em;color:#888;text-transform:uppercase;margin-bottom:4px">Atelier · Weekly Digest</div>
  <h1 style="font-size:28px;font-weight:400;margin:0 0 8px;letter-spacing:-0.01em">Your week in review, {name}.</h1>
  <p style="color:#666;font-size:14px;margin-bottom:24px">Here's what you accomplished and what's trending in your domains.</p>

  <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
    <tr>
      <td style="padding:12px;background:#fff;border:1px solid #E8E2D8;border-radius:8px;text-align:center">
        <div style="font-size:11px;color:#888;text-transform:uppercase">XP</div>
        <div style="font-size:26px;font-weight:600">{xp:,}</div>
      </td>
      <td style="width:8px"></td>
      <td style="padding:12px;background:#fff;border:1px solid #E8E2D8;border-radius:8px;text-align:center">
        <div style="font-size:11px;color:#888;text-transform:uppercase">Streak</div>
        <div style="font-size:26px;font-weight:600">{streak}d 🔥</div>
      </td>
      <td style="width:8px"></td>
      <td style="padding:12px;background:#fff;border:1px solid #E8E2D8;border-radius:8px;text-align:center">
        <div style="font-size:11px;color:#888;text-transform:uppercase">Avg score</div>
        <div style="font-size:26px;font-weight:600">{avg_score}%</div>
      </td>
    </tr>
  </table>

  <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:0.08em;color:#888;margin:0 0 8px">Topics Mastered</h3>
  <ul style="font-size:14px;line-height:1.8;padding-left:18px;margin-bottom:24px">{mastered_html}</ul>

  <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:0.08em;color:#888;margin:0 0 8px">Trending This Week</h3>
  <ul style="font-size:14px;line-height:1.8;padding-left:18px;margin-bottom:32px">{trending_html}</ul>

  <a href="https://ai-based-tutor.vercel.app/dashboard"
     style="display:inline-block;padding:10px 24px;background:#2C2416;color:#FDFAF5;text-decoration:none;border-radius:6px;font-size:14px">
    Open Atelier →
  </a>
  <p style="font-size:11px;color:#aaa;margin-top:24px">You're receiving this because you enrolled at Atelier AI Tutor.</p>
</body></html>"""

                msg = MIMEMultipart("alternative")
                msg["Subject"] = f"Your week in review, {name} · {xp:,} XP"
                msg["From"] = FROM_ADDRESS
                msg["To"] = email
                msg.attach(MIMEText(html, "html"))
                smtp.sendmail(SMTP_USER, email, msg.as_string())
                sent += 1

        log.info("progress_digest_sent", count=sent)
    except Exception as exc:
        log.error("task_send_digest_error", error=str(exc))
        self.retry(exc=exc, countdown=120)


@celery_app.task(name="app.tasks.task_definitions.discover_trending_topics", bind=True, max_retries=3)
def discover_trending_topics(self):
    """
    Daily task: discover 24 trending tech topics and AI-curated feed items.
    Runs at 03:00 UTC every day via Celery beat.
    """
    log.info("task_discover_trending_topics_start")
    try:
        from app.hf.trend_discovery import discover_trends
        from app.db.mongo import col_trending_topics, col_feed_items

        result = asyncio.run(discover_trends())

        # Persist trending topics
        if result["topics"]:
            col_trending_topics().insert_many(result["topics"])

        # Persist feed items (deduplicate by URL)
        inserted = 0
        for item in result["feed_items"]:
            r = col_feed_items().update_one(
                {"url": item["url"]},
                {"$setOnInsert": item},
                upsert=True,
            )
            if r.upserted_id:
                inserted += 1

        log.info(
            "task_discover_trending_topics_done",
            topics=len(result["topics"]),
            feed_items_new=inserted,
            discovered_at=result["discovered_at"],
        )
    except Exception as exc:
        log.error("task_discover_trending_topics_error", error=str(exc))
        self.retry(exc=exc, countdown=300)
