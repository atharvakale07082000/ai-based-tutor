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

    import os
    SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER     = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    FROM_ADDRESS  = os.environ.get("SMTP_FROM", f"Atelier AI Tutor <{SMTP_USER}>")

    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("smtp_not_configured_skipping_digest")
        return

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

                trending_rows = "".join(f"""
                    <tr>
                      <td style="padding:10px 0;border-bottom:1px solid #EDE8DF;">
                        <span style="font-size:13px;font-weight:600;color:#1A1209;">{t['subtopic']}</span>
                      </td>
                      <td style="padding:10px 0;border-bottom:1px solid #EDE8DF;text-align:right;">
                        <span style="font-size:11px;color:#888;background:#F4F0E8;padding:2px 8px;border-radius:20px;">{t['domain']}</span>
                      </td>
                    </tr>""" for t in trending)

                mastered_rows = "".join(f"""
                    <tr>
                      <td style="padding:8px 0;border-bottom:1px solid #EDE8DF;">
                        <table cellpadding="0" cellspacing="0" style="width:100%"><tr>
                          <td style="width:20px;vertical-align:middle;">
                            <div style="width:8px;height:8px;background:#3D7A5E;border-radius:50%;"></div>
                          </td>
                          <td style="font-size:13px;color:#1A1209;font-weight:500;">{t}</td>
                          <td style="text-align:right;font-size:11px;color:#3D7A5E;font-weight:600;">Mastered</td>
                        </tr></table>
                      </td>
                    </tr>""" for t in mastered[:5]) or """
                    <tr><td style="padding:12px 0;font-size:13px;color:#888;font-style:italic;">
                      Keep going — mastery unlocks at Elo 700.
                    </td></tr>"""

                # Elo progress bar (capped at 1000)
                top_topics = sorted(proficiency.items(), key=lambda x: x[1], reverse=True)[:4]
                progress_rows = "".join(f"""
                    <tr><td style="padding:6px 0;">
                      <table cellpadding="0" cellspacing="0" style="width:100%"><tr>
                        <td style="font-size:12px;color:#444;width:160px;white-space:nowrap;overflow:hidden;">{topic[:22]}</td>
                        <td style="padding:0 10px;">
                          <div style="height:5px;background:#EDE8DF;border-radius:3px;overflow:hidden;">
                            <div style="width:{min(int(elo/10), 100)}%;height:100%;background:{'#2C2416' if elo>=700 else '#A8895A'};border-radius:3px;"></div>
                          </div>
                        </td>
                        <td style="font-size:11px;color:#888;text-align:right;white-space:nowrap;">{int(elo)} elo</td>
                      </tr></table>
                    </td></tr>""" for topic, elo in top_topics)

                from datetime import datetime as _dt
                week_label = _dt.now().strftime("%B %d, %Y")

                html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Atelier Weekly Digest</title></head>
<body style="margin:0;padding:0;background:#F4F0E8;font-family:Georgia,serif;">
<table cellpadding="0" cellspacing="0" style="width:100%;background:#F4F0E8;padding:32px 0;">
  <tr><td align="center">
  <table cellpadding="0" cellspacing="0" style="width:100%;max-width:560px;background:#FDFAF5;border-radius:12px;overflow:hidden;box-shadow:0 2px 24px rgba(44,36,22,0.08);">

    <!-- Header -->
    <tr><td style="background:#2C2416;padding:28px 36px;">
      <table cellpadding="0" cellspacing="0" style="width:100%"><tr>
        <td>
          <div style="font-size:11px;letter-spacing:0.14em;color:#A8895A;text-transform:uppercase;margin-bottom:6px;">Atelier · Weekly Digest</div>
          <div style="font-size:26px;color:#FDFAF5;font-weight:400;letter-spacing:-0.01em;line-height:1.2;">Your week in review,<br><em style="color:#D4B896;">{name}.</em></div>
        </td>
        <td align="right" valign="top">
          <div style="font-size:11px;color:#6B5A42;margin-top:4px;">{week_label}</div>
        </td>
      </tr></table>
    </td></tr>

    <!-- Stats row -->
    <tr><td style="padding:0 36px;">
      <table cellpadding="0" cellspacing="0" style="width:100%;margin:24px 0;">
        <tr>
          <td style="background:#fff;border:1px solid #EDE8DF;border-radius:8px;padding:16px;text-align:center;width:33%;">
            <div style="font-size:10px;letter-spacing:0.1em;color:#AAA;text-transform:uppercase;margin-bottom:6px;">Total XP</div>
            <div style="font-size:28px;font-weight:700;color:#2C2416;letter-spacing:-0.02em;">{xp:,}</div>
          </td>
          <td style="width:8px;"></td>
          <td style="background:#fff;border:1px solid #EDE8DF;border-radius:8px;padding:16px;text-align:center;width:33%;">
            <div style="font-size:10px;letter-spacing:0.1em;color:#AAA;text-transform:uppercase;margin-bottom:6px;">Streak</div>
            <div style="font-size:28px;font-weight:700;color:#2C2416;letter-spacing:-0.02em;">{streak}<span style="font-size:14px;">d</span> &#128293;</div>
          </td>
          <td style="width:8px;"></td>
          <td style="background:#fff;border:1px solid #EDE8DF;border-radius:8px;padding:16px;text-align:center;width:33%;">
            <div style="font-size:10px;letter-spacing:0.1em;color:#AAA;text-transform:uppercase;margin-bottom:6px;">Quiz Avg</div>
            <div style="font-size:28px;font-weight:700;color:#2C2416;letter-spacing:-0.02em;">{avg_score}<span style="font-size:14px;">%</span></div>
          </td>
        </tr>
      </table>
    </td></tr>

    <!-- Divider -->
    <tr><td style="padding:0 36px;"><div style="height:1px;background:#EDE8DF;"></div></td></tr>

    <!-- Skill progress -->
    <tr><td style="padding:20px 36px 4px;">
      <div style="font-size:10px;letter-spacing:0.12em;color:#AAA;text-transform:uppercase;margin-bottom:12px;">Skill Progress</div>
      <table cellpadding="0" cellspacing="0" style="width:100%;">
        {progress_rows or '<tr><td style="font-size:13px;color:#888;font-style:italic;padding:8px 0;">Start a quiz to track your skill Elo.</td></tr>'}
      </table>
    </td></tr>

    <!-- Mastered topics -->
    <tr><td style="padding:20px 36px 4px;">
      <div style="font-size:10px;letter-spacing:0.12em;color:#AAA;text-transform:uppercase;margin-bottom:12px;">Topics Mastered</div>
      <table cellpadding="0" cellspacing="0" style="width:100%;">
        {mastered_rows}
      </table>
    </td></tr>

    <!-- Trending -->
    <tr><td style="padding:20px 36px 4px;">
      <div style="font-size:10px;letter-spacing:0.12em;color:#AAA;text-transform:uppercase;margin-bottom:12px;">Trending This Week</div>
      <table cellpadding="0" cellspacing="0" style="width:100%;">
        {trending_rows or '<tr><td style="font-size:13px;color:#888;font-style:italic;padding:8px 0;">Discovery runs at 03:00 UTC daily.</td></tr>'}
      </table>
    </td></tr>

    <!-- CTA -->
    <tr><td style="padding:28px 36px 36px;">
      <table cellpadding="0" cellspacing="0"><tr>
        <td style="background:#2C2416;border-radius:7px;">
          <a href="https://ai-based-tutor.vercel.app/dashboard"
             style="display:inline-block;padding:12px 28px;color:#FDFAF5;text-decoration:none;font-size:14px;font-family:Georgia,serif;letter-spacing:0.02em;">
            Open Atelier &rarr;
          </a>
        </td>
      </tr></table>
    </td></tr>

    <!-- Footer -->
    <tr><td style="background:#F4F0E8;padding:16px 36px;border-top:1px solid #EDE8DF;">
      <p style="margin:0;font-size:11px;color:#AAA;font-family:Arial,sans-serif;">
        You're receiving this because you enrolled at Atelier AI Tutor.
      </p>
    </td></tr>

  </table>
  </td></tr>
</table>
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
