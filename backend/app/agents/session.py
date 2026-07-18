"""
Study-session engine — replaces the v1 LangGraph supervisor for /session and
/curriculum/generate.

The old supervisor's routing was already deterministic (build path → pick first
unmastered topic → generate quiz → on progress, update Elo then advance); this
module ports that logic as plain async functions. ``run_session(state)`` keeps the
same ``ainvoke(state) -> final_state`` contract the routers expect, so the routers
barely change.
"""

from __future__ import annotations

import structlog

from app.agents.progress import calculate_elo_update
from app.agents.state import MASTERY_THRESHOLD_DEFAULT
from app.guardrails import sanitize_quiz_batch
from app.prompts.loader import get_curriculum_config
from app.tools import tool_registry

log = structlog.get_logger()

# Elo band -> Bloom level (ported from the v1 quiz agent).
BLOOM_LEVEL_BY_ELO: list[tuple[tuple[int, int], str]] = [
    ((0, 300), "remember"),
    ((300, 450), "understand"),
    ((450, 600), "apply"),
    ((600, 720), "analyze"),
    ((720, 870), "evaluate"),
    ((870, 1001), "create"),
]
_BLOOM_LEVELS = [lvl for _, lvl in BLOOM_LEVEL_BY_ELO]


def get_bloom_level(elo: float) -> str:
    for (low, high), level in BLOOM_LEVEL_BY_ELO:
        if low <= elo < high:
            return level
    return "understand"


async def _tool(name: str, **args) -> dict:
    result = await tool_registry.call(name, args)
    return result.result if result.result is not None else {}


# ─── Curriculum building (ported from curriculum_agent) ───────────────────────


async def _enrich_with_trending(
    topic_graph: dict[str, list[str]],
) -> dict[str, list[str]]:
    try:
        from app.db.mongo import col_trending_topics

        latest = await col_trending_topics().find_one(
            {}, {"_id": 0, "discovered_at": 1}, sort=[("discovered_at", -1)]
        )
        if not latest:
            return topic_graph
        trends = await (
            col_trending_topics()
            .find(
                {"discovered_at": latest["discovered_at"]},
                {"_id": 0, "domain": 1, "subtopic": 1},
            )
            .limit(100)
        ).to_list(length=None)
        enriched = {k: list(v) for k, v in topic_graph.items()}
        for t in trends:
            domain, subtopic = t.get("domain", ""), t.get("subtopic", "")
            if not domain or not subtopic:
                continue
            enriched.setdefault(domain, [])
            if subtopic not in enriched[domain]:
                enriched[domain].append(subtopic)
        return enriched
    except Exception as e:  # noqa: BLE001
        log.warning("curriculum_trending_enrich_error", error=str(e))
        return topic_graph


async def build_curriculum(
    goals: list[str], proficiency: dict[str, float]
) -> list[dict]:
    """Build a personalized, ordered curriculum path (ported from _build_curriculum)."""
    cfg = get_curriculum_config()
    topic_graph = await _enrich_with_trending(cfg["topic_graph"])
    settings = cfg["settings"]

    path: list[dict] = []
    if goals:
        for goal in goals:
            try:
                classification = await _tool("classify_topic", text=goal)
                labels = classification.get("labels") or []
                domain = labels[0] if labels else "Python Programming"
            except Exception as e:  # noqa: BLE001
                log.warning("curriculum_classify_failed", goal=goal[:60], error=str(e))
                domain = "Python Programming"
            subtopics = topic_graph.get(domain) or topic_graph.get(
                "Python Programming", []
            )
            ordered = sorted(subtopics, key=lambda t: proficiency.get(t, 500.0))
            path.extend(
                {
                    "domain": domain,
                    "subtopic": st,
                    "priority": idx,
                    "elo": proficiency.get(st, 500.0),
                }
                for idx, st in enumerate(ordered)
            )
    else:
        for domain in settings["default_domains"]:
            subtopics = topic_graph.get(domain, [])
            path.extend(
                {"domain": domain, "subtopic": st, "priority": idx, "elo": 500.0}
                for idx, st in enumerate(
                    subtopics[: settings["default_subtopics_per_domain"]]
                )
            )

    seen: set[str] = set()
    unique: list[dict] = []
    for item in path:
        key = f"{item['domain']}:{item['subtopic']}"
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[: settings["max_path_length"]]


# ─── Quiz generation (ported from quiz_agent) ─────────────────────────────────


async def _generate_quiz(topic: str, elo: float, mood: str) -> tuple[list[dict], str]:
    bloom = get_bloom_level(elo)
    try:
        diff = await _tool("score_difficulty", text=topic)
        difficulty = max(0.0, min(1.0, float(diff.get("score", 0.5))))
        if difficulty > 0.75 and elo < 400 and bloom in _BLOOM_LEVELS:
            bloom = _BLOOM_LEVELS[max(0, _BLOOM_LEVELS.index(bloom) - 1)]
    except Exception as e:  # noqa: BLE001
        log.warning("session_difficulty_check_failed", topic=topic, error=str(e))
    if mood == "NEGATIVE" and bloom in _BLOOM_LEVELS:
        bloom = _BLOOM_LEVELS[max(0, _BLOOM_LEVELS.index(bloom) - 1)]
    result = await _tool("generate_quiz", topic=topic, bloom_level=bloom, count=5)
    questions = sanitize_quiz_batch(result.get("questions", []), bloom)
    return questions, bloom


# ─── Topic selection (ported from supervisor) ─────────────────────────────────


def _first_unmastered(
    path: list[dict], proficiency: dict[str, float], mastery: float
) -> str:
    for item in path:
        st = item["subtopic"]
        if proficiency.get(st, item.get("elo", 500.0)) < mastery:
            return st
    return ""


# ─── Public entry point (mirrors orchestrator.ainvoke) ────────────────────────


async def run_session(state: dict) -> dict:
    """Run one session step. task_type ∈ {'start', 'progress'}; returns the merged state."""
    task_type = state.get("task_type", "start")
    proficiency = dict(state.get("topic_proficiency", {}))
    mastery = state.get("mastery_threshold", MASTERY_THRESHOLD_DEFAULT)
    iteration = state.get("iteration_count", 0) + 1

    result: dict = dict(state)
    result["iteration_count"] = iteration

    # On a progress step, first apply the Elo/mood update for the answered topic.
    mood = "NEUTRAL"
    if task_type == "progress":
        delta_in = state.get("progress_delta", {})
        topic = state.get("current_topic", "")
        score = delta_in.get("score", 0.5)
        old_elo = proficiency.get(topic, 500.0)
        new_elo = calculate_elo_update(old_elo, score)
        proficiency[topic] = new_elo
        out_delta = {
            "topic": topic,
            "old_elo": old_elo,
            "new_elo": new_elo,
            "score": score,
        }
        reflection = delta_in.get("reflection", "")
        if reflection:
            try:
                sentiment = await _tool("analyze_sentiment", text=reflection)
                mood = sentiment.get("label", "NEUTRAL")
                out_delta["mood"] = mood
                out_delta["mood_score"] = sentiment.get("score", 0.5)
            except Exception:  # noqa: BLE001
                out_delta["mood"] = "NEUTRAL"
        out_delta["elo_processed"] = True
        result["topic_proficiency"] = proficiency
        result["progress_delta"] = out_delta
        result["learner_mood"] = out_delta.get("mood", "NEUTRAL")

    # Ensure a curriculum path exists.
    path = state.get("curriculum_path") or []
    if not path:
        goals = state.get("learner_profile", {}).get("goal_vector", [])
        path = await build_curriculum(goals, proficiency)
    result["curriculum_path"] = path

    # Pick the next topic to study (first unmastered).
    next_topic = _first_unmastered(path, proficiency, mastery)
    if not next_topic:
        result["current_topic"] = ""
        result["bloom_level"] = state.get("bloom_level", "understand")
        result["quiz_questions"] = []
        result["session_complete"] = True
        log.info("session_complete", learner_id=state.get("learner_id"))
        return result

    elo = proficiency.get(next_topic, 500.0)
    questions, bloom = await _generate_quiz(next_topic, elo, mood)
    result["current_topic"] = next_topic
    result["bloom_level"] = bloom
    result["quiz_questions"] = questions
    result["session_complete"] = False
    log.info(
        "session_step_done", topic=next_topic, bloom=bloom, questions=len(questions)
    )
    return result
