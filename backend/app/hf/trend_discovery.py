"""
Trend Discovery Agent — discovers 24 trending tech topics every 24 hours.

Flow:
  1. DDGS searches across IT, Data Engineering, DevOps, Cloud, AI domains
  2. HF LLM classifies + deduplicates raw results into canonical trending topics
  3. Returns TrendResult (topics for curriculum + feed items with URLs)
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import TypedDict

import structlog
from ddgs import DDGS

from app.hf.client import get_hf_client
from app.hf.models import HF_MODELS

log = structlog.get_logger()

# ── Domain search queries ──────────────────────────────────────────────────────

_DOMAIN_QUERIES: list[tuple[str, str]] = [
    ("Data Engineering", "data engineering trends tools 2025"),
    ("Data Engineering", "apache kafka spark flink dbt tutorial 2025"),
    ("DevOps", "devops platform engineering tools 2025"),
    ("DevOps", "kubernetes gitops ci cd best practices 2025"),
    ("Cloud Computing", "cloud architecture aws gcp azure trends 2025"),
    ("Cloud Computing", "serverless edge computing cloud native 2025"),
    ("Machine Learning", "machine learning MLOps LLMOps 2025"),
    ("Deep Learning", "deep learning computer vision NLP research 2025"),
    ("Data Science", "data science analytics python tools 2025"),
    ("Cybersecurity", "cybersecurity zero trust threat detection 2025"),
    ("AI Engineering", "AI agents RAG vector database LLM deployment 2025"),
    ("Software Engineering", "software architecture microservices system design 2025"),
]

TARGET_TOPICS = 24


class TrendTopic(TypedDict):
    id: str
    domain: str
    subtopic: str
    description: str
    is_trending: bool
    discovered_at: str


class FeedItem(TypedDict):
    id: str
    title: str
    summary: str
    url: str
    source: str
    domain: str
    subtopic: str
    content_type: str  # "article" | "video" | "course" | "news"
    is_trending: bool
    is_ai_recommended: bool
    estimated_minutes: int
    difficulty: float
    discovered_at: str
    expires_at: str  # 24h window


class TrendResult(TypedDict):
    topics: list[TrendTopic]
    feed_items: list[FeedItem]
    discovered_at: str


def _search_one(query: str, max_results: int = 5) -> list[dict]:
    """Synchronous DDGS search — wrapped in to_thread by caller."""
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        log.warning("ddgs_search_error", query=query, error=str(e))
        return []


def _infer_type(url: str, title: str) -> str:
    lower = (url + title).lower()
    if any(k in lower for k in ("youtube", "youtu.be", "video", "watch")):
        return "video"
    if any(k in lower for k in ("course", "udemy", "coursera", "pluralsight")):
        return "course"
    return "article"


def _estimate_minutes(body: str) -> int:
    words = len(body.split()) if body else 300
    return max(5, min(45, words // 200 * 5))


def _extract_source(url: str) -> str:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        return host.replace("www.", "").split(".")[0]
    except Exception:
        return "web"


def _llm_distill(raw_items: list[dict]) -> list[dict]:
    """
    Use HF LLM to extract 24 canonical trending topics from raw search results.
    Returns list[{domain, subtopic, description}].
    """
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    client = get_hf_client(model_cfg["provider"])

    # Build compact summary of raw results
    snippets = "\n".join(
        f"- [{item.get('domain', '')}] {item.get('title', '')} | {item.get('body', '')[:120]}"
        for item in raw_items[:40]
    )

    prompt = f"""You are a tech curriculum expert. Below are recent search results about trending IT topics.

Extract exactly {TARGET_TOPICS} distinct, actionable learning subtopics that are trending right now across:
Data Engineering, DevOps, Cloud Computing, Machine Learning, Deep Learning, Data Science, Cybersecurity, AI Engineering, Software Engineering.

Search results:
{snippets}

Return ONLY valid JSON array, no explanation:
[
  {{"domain": "Data Engineering", "subtopic": "Apache Kafka Streams", "description": "Real-time stream processing with Kafka Streams API"}},
  ...
]

Rules:
- Each subtopic must be a specific, learnable skill (not a vague category)
- No duplicates
- Prioritize topics with high demand in 2025
- Exactly {TARGET_TOPICS} items
"""

    try:
        resp = client.chat_completion(
            model=model_cfg["model_id"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1800,
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        # Extract JSON array
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        log.warning("trend_llm_distill_error", error=str(e))

    return []


async def discover_trends() -> TrendResult:
    """
    Main entry point — discovers trending topics and feed items.
    Runs DDGS searches in parallel, then LLM distillation.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=24)
    now_iso = now.isoformat()
    expires_iso = expires.isoformat()

    log.info("trend_discovery_start")

    # ── Parallel DDGS searches ─────────────────────────────────────────────────
    tasks = [asyncio.to_thread(_search_one, query, 5) for _, query in _DOMAIN_QUERIES]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten + tag with domain
    raw_items: list[dict] = []
    feed_items: list[FeedItem] = []
    seen_urls: set[str] = set()

    for (domain, _), result in zip(_DOMAIN_QUERIES, all_results):
        if isinstance(result, Exception):
            continue
        for r in result:
            url = r.get("href", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = r.get("title", "")
            body = r.get("body", "")
            raw_items.append({"domain": domain, "title": title, "body": body, "url": url})

            feed_items.append(
                FeedItem(
                    id=str(uuid.uuid4()),
                    title=title[:140],
                    summary=body[:300] if body else title,
                    url=url,
                    source=_extract_source(url),
                    domain=domain,
                    subtopic="",  # filled in after distillation
                    content_type=_infer_type(url, title),
                    is_trending=True,
                    is_ai_recommended=True,
                    estimated_minutes=_estimate_minutes(body),
                    difficulty=0.5,
                    discovered_at=now_iso,
                    expires_at=expires_iso,
                )
            )

    log.info("trend_discovery_raw_count", count=len(raw_items))

    # ── LLM distillation ──────────────────────────────────────────────────────
    distilled = await asyncio.to_thread(_llm_distill, raw_items)

    # Fallback: build topics from domain labels if LLM fails
    if not distilled:
        distilled = _fallback_topics()

    # Cap to TARGET_TOPICS
    distilled = distilled[:TARGET_TOPICS]

    topics: list[TrendTopic] = [
        TrendTopic(
            id=str(uuid.uuid4()),
            domain=t.get("domain", "Technology"),
            subtopic=t.get("subtopic", "General"),
            description=t.get("description", ""),
            is_trending=True,
            discovered_at=now_iso,
        )
        for t in distilled
    ]

    # Annotate top feed items with their matching subtopic
    topic_by_domain: dict[str, str] = {t["domain"]: t["subtopic"] for t in topics}
    for fi in feed_items:
        fi["subtopic"] = topic_by_domain.get(fi["domain"], "")

    log.info("trend_discovery_done", topics=len(topics), feed_items=len(feed_items))
    return TrendResult(topics=topics, feed_items=feed_items[:48], discovered_at=now_iso)


def _fallback_topics() -> list[dict]:
    """Hardcoded fallback if LLM call fails."""
    return [
        {
            "domain": "Data Engineering",
            "subtopic": "Apache Kafka Streams",
            "description": "Real-time event streaming with Kafka",
        },
        {
            "domain": "Data Engineering",
            "subtopic": "dbt (Data Build Tool)",
            "description": "Analytics engineering with dbt",
        },
        {
            "domain": "Data Engineering",
            "subtopic": "Apache Iceberg",
            "description": "Open table format for huge analytic datasets",
        },
        {
            "domain": "Data Engineering",
            "subtopic": "Medallion Architecture",
            "description": "Bronze/Silver/Gold data lake patterns",
        },
        {
            "domain": "DevOps",
            "subtopic": "Platform Engineering",
            "description": "Internal developer platforms and golden paths",
        },
        {"domain": "DevOps", "subtopic": "GitOps with ArgoCD", "description": "Git-driven Kubernetes deployments"},
        {"domain": "DevOps", "subtopic": "OpenTelemetry Observability", "description": "Unified traces, metrics, logs"},
        {"domain": "DevOps", "subtopic": "Helm Chart Development", "description": "Kubernetes package management"},
        {
            "domain": "Cloud Computing",
            "subtopic": "Serverless Containers",
            "description": "AWS Fargate, Cloud Run, and beyond",
        },
        {
            "domain": "Cloud Computing",
            "subtopic": "FinOps & Cloud Cost",
            "description": "Managing and optimizing cloud spend",
        },
        {
            "domain": "Cloud Computing",
            "subtopic": "Multi-Cloud Networking",
            "description": "Connecting workloads across cloud providers",
        },
        {
            "domain": "AI Engineering",
            "subtopic": "RAG with Vector Databases",
            "description": "Retrieval-augmented generation pipelines",
        },
        {
            "domain": "AI Engineering",
            "subtopic": "LLM Evaluation & Benchmarks",
            "description": "Testing and scoring LLM outputs",
        },
        {
            "domain": "AI Engineering",
            "subtopic": "AI Agent Orchestration",
            "description": "LangGraph, AutoGen, CrewAI patterns",
        },
        {"domain": "AI Engineering", "subtopic": "Model Quantization", "description": "Running LLMs on edge devices"},
        {
            "domain": "Machine Learning",
            "subtopic": "MLflow & Experiment Tracking",
            "description": "ML lifecycle and model registry",
        },
        {
            "domain": "Machine Learning",
            "subtopic": "Feature Stores",
            "description": "Feast, Tecton — sharing ML features",
        },
        {
            "domain": "Deep Learning",
            "subtopic": "Vision Transformers (ViT)",
            "description": "Attention-based vision models",
        },
        {"domain": "Deep Learning", "subtopic": "Multimodal LLMs", "description": "Vision-language models like GPT-4V"},
        {
            "domain": "Data Science",
            "subtopic": "Causal Inference",
            "description": "DoWhy, causal graphs, counterfactuals",
        },
        {
            "domain": "Data Science",
            "subtopic": "Polars DataFrames",
            "description": "Blazing-fast Rust-based dataframes",
        },
        {
            "domain": "Cybersecurity",
            "subtopic": "Zero Trust Architecture",
            "description": "Never trust, always verify access model",
        },
        {
            "domain": "Cybersecurity",
            "subtopic": "Prompt Injection Defense",
            "description": "Securing LLM-powered applications",
        },
        {
            "domain": "Software Engineering",
            "subtopic": "Event-Driven Architecture",
            "description": "CQRS, Event Sourcing, Saga patterns",
        },
    ]
