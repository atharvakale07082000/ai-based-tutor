"""The Evidence Ledger — one append-only record per graded event.

Every claim Atelier makes about a learner ("you're at 740 on SQL", "you cleared the
senior coding bar") is an aggregate over rows in this collection. Rows are written
once and never updated or deleted: a score that can be edited after the fact is not
evidence, and a public profile built on mutable rows could not honestly call itself
verified.

Each row carries a ``content_hash`` over its canonical tuple, so a row that was
tampered with in the database no longer matches its own hash.

Callers use :func:`record_evidence` — never build a row inline (same convention as
``db/mongo.py::PROJ`` and ``agents/progress.py::MASTERY_ELO``). Recording is
best-effort by design: a ledger write must never fail the request that produced the
score, because the learner already earned it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

import structlog

from app.db.mongo import col_evidence

log = structlog.get_logger()

EvidenceKind = Literal["quiz", "module_interview", "interview_round"]

# Scores are stored normalized to 0-1 so a quiz (0-1), a module interview (0-10) and a
# loop round (0-10) are directly comparable without the reader knowing the source.
_HASH_FIELDS = (
    "learner_id",
    "skill",
    "kind",
    "score_0_1",
    "bar_0_1",
    "passed",
    "occurred_at",
    "source",
)


def _content_hash(row: dict) -> str:
    """SHA-256 over the row's canonical tuple, with stable key ordering."""
    canonical = json.dumps(
        {k: row.get(k) for k in _HASH_FIELDS}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_evidence(
    *,
    learner_id: str,
    skill: str,
    kind: EvidenceKind,
    score_0_1: float,
    bar_0_1: float,
    source_collection: str,
    source_id: str,
    context: dict | None = None,
    occurred_at: str | None = None,
) -> dict:
    """Build a complete, hashed evidence row. Pure — no I/O, unit-testable."""
    score = round(max(0.0, min(1.0, float(score_0_1))), 4)
    bar = round(max(0.0, min(1.0, float(bar_0_1))), 4)
    row = {
        "id": str(uuid.uuid4()),
        "learner_id": learner_id,
        "skill": skill,
        "kind": kind,
        "score_0_1": score,
        "bar_0_1": bar,
        "passed": score >= bar,
        "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
        "source": {"collection": source_collection, "id": source_id},
        "context": context or {},
    }
    row["content_hash"] = _content_hash(row)
    return row


def verify_evidence(row: dict) -> bool:
    """True if a stored row still matches its own hash."""
    return bool(row.get("content_hash")) and row["content_hash"] == _content_hash(row)


async def record_evidence(**kwargs) -> dict | None:
    """Append one evidence row. Returns the row, or ``None`` if recording failed.

    Never raises: the caller has already graded the learner, and losing a ledger row is
    strictly better than losing the score itself.
    """
    try:
        row = build_evidence(**kwargs)
        await col_evidence().insert_one({**row})
        return row
    except Exception as e:  # noqa: BLE001 - the ledger must never break its caller
        log.warning(
            "evidence_record_failed",
            skill=kwargs.get("skill"),
            kind=kwargs.get("kind"),
            error=str(e)[:200],
        )
        return None
