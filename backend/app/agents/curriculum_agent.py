import structlog

from app.agents.state import AgentState
from app.agents.tools import call_tool
from app.prompts.loader import get_curriculum_config
from app.tracing import get_tracer

log = structlog.get_logger()


def _load_topic_graph() -> dict[str, list[str]]:
    return get_curriculum_config()["topic_graph"]


def _load_settings() -> dict:
    return get_curriculum_config()["settings"]


def _enrich_with_trending(topic_graph: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Inject the latest trending subtopics from the discovery agent into the
    topic_graph so curriculum paths include up-to-date industry skills.
    Only adds subtopics not already present; doesn't remove existing ones.
    """
    try:
        from app.db.mongo import col_trending_topics
        # Get the most recent batch of trending topics
        latest = col_trending_topics().find_one({}, {"_id": 0, "discovered_at": 1}, sort=[("discovered_at", -1)])
        if not latest:
            return topic_graph

        batch_time = latest["discovered_at"]
        trends = list(col_trending_topics().find(
            {"discovered_at": batch_time}, {"_id": 0, "domain": 1, "subtopic": 1}
        ))

        enriched = {k: list(v) for k, v in topic_graph.items()}
        for t in trends:
            domain = t.get("domain", "")
            subtopic = t.get("subtopic", "")
            if not domain or not subtopic:
                continue
            if domain not in enriched:
                enriched[domain] = []
            if subtopic not in enriched[domain]:
                enriched[domain].append(subtopic)

        log.info("curriculum_trending_enriched", added=len(trends))
        return enriched
    except Exception as e:
        log.warning("curriculum_trending_enrich_error", error=str(e))
        return topic_graph


async def curriculum_agent_node(state: AgentState) -> dict:
    """
    Build a personalized curriculum path for the learner.

    Delegation: calls the `classify_topic` tool (topic-classifier sub-agent)
    to map free-text goals to canonical curriculum domains.
    """
    tracer = get_tracer()
    learner_id = state["learner_id"]

    with tracer.trace(
        "curriculum_agent",
        input={
            "learner_id": learner_id,
            "goals": state.get("learner_profile", {}).get("goal_vector", []),
            "topic_proficiency": state.get("topic_proficiency", {}),
        },
    ) as span:
        log.info("curriculum_agent_start", learner_id=learner_id)
        try:
            result = await _build_curriculum(state)
            span.update(output={"path_length": len(result.get("curriculum_path", []))})
            return result
        except Exception as e:
            log.error("curriculum_agent_error", error=str(e))
            span.update(output={"error": str(e)})
            return {"curriculum_path": [], "error": str(e)}


async def _build_curriculum(state: AgentState) -> dict:
    profile = state.get("learner_profile", {})
    proficiency = state.get("topic_proficiency", {})
    goals = profile.get("goal_vector", [])

    topic_graph = _enrich_with_trending(_load_topic_graph())
    settings = _load_settings()

    curriculum_path: list[dict] = []

    if goals:
        for goal in goals:
            # Delegate to classify_topic sub-agent to map goal text → domain
            try:
                classification = await call_tool("classify_topic", text=goal)
                domain = classification["labels"][0] if classification["labels"] else "Python Programming"
            except Exception:
                domain = "Python Programming"

            subtopics = topic_graph.get(domain, topic_graph["Python Programming"])

            # Sort by proficiency gap — lowest Elo (most room to grow) first
            ordered = sorted(subtopics, key=lambda t: proficiency.get(t, 500.0))
            curriculum_path.extend([
                {
                    "domain": domain,
                    "subtopic": st,
                    "priority": idx,
                    "elo": proficiency.get(st, 500.0),
                }
                for idx, st in enumerate(ordered)
            ])
    else:
        # New learner: bootstrap with top-N default domains
        default_domains = settings["default_domains"]
        n = settings["default_subtopics_per_domain"]
        for domain in default_domains:
            subtopics = topic_graph.get(domain, [])
            curriculum_path.extend([
                {"domain": domain, "subtopic": st, "priority": idx, "elo": 500.0}
                for idx, st in enumerate(subtopics[:n])
            ])

    # Deduplicate preserving order, cap at max_path_length
    max_len = settings["max_path_length"]
    seen: set[str] = set()
    unique_path: list[dict] = []
    for item in curriculum_path:
        key = f"{item['domain']}:{item['subtopic']}"
        if key not in seen:
            seen.add(key)
            unique_path.append(item)

    final_path = unique_path[:max_len]
    log.info("curriculum_agent_done", path_length=len(final_path))

    mastered = sum(1 for item in final_path if proficiency.get(item["subtopic"], 0) >= 700)
    report = {
        "agent": "curriculum",
        "summary": (
            f"Built {len(final_path)} topics across "
            f"{len({i['domain'] for i in final_path})} domains. "
            f"{mastered} already mastered. "
            f"Next: {final_path[0]['subtopic'] if final_path else 'none'}."
        ),
    }
    return {"curriculum_path": final_path, "error": None, "agent_reports": [report]}
