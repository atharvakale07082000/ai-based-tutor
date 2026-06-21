"""
Semantic Content Recommendation Agent — HuggingFace all-MiniLM-L6-v2.

Scores each content item against a learner's profile using cosine similarity
of sentence embeddings, then returns ranked items with `is_ai_recommended` flag.
"""

from __future__ import annotations

import asyncio

import structlog

from app.hf.client import get_hf_client
from app.hf.embeddings import _embed_cache, _embed_lock, cosine_similarity
from app.hf.models import HF_MODELS

log = structlog.get_logger()


async def _batch_embeddings(texts: list[str]) -> list[list[float]]:
    """Return embeddings for a batch of texts, using the process-wide TTLCache.

    Cache hits are served immediately; only the uncached texts go to the HF API
    in a single batched request (one round-trip instead of N sequential calls).
    """
    results: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int] = []
    miss_texts: list[str] = []

    with _embed_lock:
        for i, text in enumerate(texts):
            cached = _embed_cache.get(text)
            if cached is not None:
                results[i] = cached
            else:
                miss_indices.append(i)
                miss_texts.append(text)

    if miss_texts:
        client = get_hf_client()
        model_id = HF_MODELS["EMBEDDINGS"]["model_id"]
        raw = await asyncio.to_thread(client.feature_extraction, miss_texts, model=model_id)

        # raw may be a 2-D numpy array [batch, dim] or list of lists
        if hasattr(raw, "ndim") and raw.ndim == 2:
            batch_vectors = [[float(x) for x in row.tolist()] for row in raw]
        elif isinstance(raw, list) and raw and isinstance(raw[0], list):
            batch_vectors = [[float(x) for x in row] for row in raw]
        else:
            # Fallback: treat as single vector (single text edge case)
            batch_vectors = [[float(x) for x in raw]]

        with _embed_lock:
            for idx, text, vector in zip(miss_indices, miss_texts, batch_vectors):
                _embed_cache[text] = vector
                results[idx] = vector

    return [r for r in results if r is not None]


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
        # Build all texts (learner query + item texts) and batch-embed in one API call
        items_to_score = content_items[:20]
        item_texts = [
            f"{item.get('title', '')} {item.get('topic', '')} {item.get('subtopic', '')}" for item in items_to_score
        ]
        all_texts = [learner_query] + item_texts
        all_embeddings = await _batch_embeddings(all_texts)
        learner_emb = all_embeddings[0]
        embeddings = all_embeddings[1:]

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
