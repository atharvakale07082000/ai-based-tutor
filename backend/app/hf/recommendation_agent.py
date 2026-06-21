"""
Semantic Content Recommendation Agent — HuggingFace all-MiniLM-L6-v2.

Scores each content item against a learner's profile using cosine similarity
of sentence embeddings, then returns ranked items with `is_ai_recommended` flag.
"""

from __future__ import annotations

import asyncio

import structlog

from app.hf.embeddings import cosine_similarity, get_embeddings
from app.hf.utils import BoundedCache

log = structlog.get_logger()

# Thread-safe LRU embedding cache (max 512 entries ≈ 200 MB)
_embed_cache: BoundedCache = BoundedCache(max_size=512)


async def _cached_embed(text: str) -> list[float]:
    """Return an embedding vector from the LRU cache, computing it on a miss."""
    cached = _embed_cache.get(text)
    if cached is not None:
        return cached
    result = await get_embeddings(text)
    _embed_cache.set(text, result)
    return result


def _build_learner_query(
    goal_vector: list[str],
    weak_topics: list[str],
    top_topics: list[str],
) -> str:
    """
    Construct a natural language summary of the learner profile for embedding.
    Weak topics get higher weight by repeating them.
    """
    parts: list[str] = []
    if goal_vector:
        parts.append("Learning goals: " + ", ".join(goal_vector[:5]))
    if weak_topics:
        # Repeat weak topics to boost their embedding weight
        parts.append("Needs improvement: " + ", ".join(weak_topics * 2))
    if top_topics:
        parts.append("Strong in: " + ", ".join(top_topics[:3]))
    return ". ".join(parts) or "general learning"


async def rank_content_for_learner(
    content_items: list[dict],
    goal_vector: list[str],
    topic_proficiency: dict[str, float],
    top_n_recommended: int = 4,
) -> list[dict]:
    """
    Rank content items by semantic relevance to the learner profile.
    Marks the top `top_n_recommended` items as `is_ai_recommended=True`.

    Returns the items list with updated `is_ai_recommended` flags and
    an added `_relevance_score` for debugging.
    """
    if not content_items:
        return content_items

    sorted_prof = sorted(topic_proficiency.items(), key=lambda x: x[1], reverse=True)
    top_topics = [t for t, _ in sorted_prof[:3]]
    weak_topics = [t for t, elo in sorted_prof if elo < 600][:4]

    learner_query = _build_learner_query(goal_vector, weak_topics, top_topics)
    log.info("recommendation_agent_start", query=learner_query[:80], n_items=len(content_items))

    try:
        learner_emb = await _cached_embed(learner_query)

        # Embed all items concurrently (cap at 20 for latency)
        items_to_score = content_items[:20]
        item_texts = [
            f"{item.get('title', '')} {item.get('topic', '')} {item.get('subtopic', '')}" for item in items_to_score
        ]

        embeddings = await asyncio.gather(*[_cached_embed(t) for t in item_texts])

        scored: list[tuple[int, float]] = []
        for idx, emb in enumerate(embeddings):
            sim = cosine_similarity(learner_emb, emb)
            # Bonus for items matching weak topics (most valuable to learn next)
            item = items_to_score[idx]
            topic_lower = item.get("topic", "").lower()
            if any(wt.lower() in topic_lower for wt in weak_topics):
                sim += 0.15
            scored.append((idx, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_indices = {idx for idx, _ in scored[:top_n_recommended]}

        # Apply flags
        result = []
        for i, item in enumerate(items_to_score):
            updated = dict(item)
            updated["is_ai_recommended"] = i in top_indices
            updated["_relevance_score"] = (
                float(round(scored[next(j for j, (idx, _) in enumerate(scored) if idx == i)][1], 4))
                if i < len(scored)
                else 0.0
            )
            result.append(updated)

        # Append remaining items (beyond 20) unchanged
        result.extend(content_items[20:])
        log.info("recommendation_agent_done", top_indices=list(top_indices))
        return result

    except Exception as e:
        log.warning("recommendation_agent_error", error=str(e))
        return content_items
