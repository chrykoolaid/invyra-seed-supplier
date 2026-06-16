"""Structured governance event records returned by service-layer operations.

This module intentionally stops at DTO-level event objects.
It does not implement audit persistence or an event store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from supplier_seed.domain.enums import GovernanceEventType


UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class GovernanceEventRecord:
    event_id: str
    supplier_id: str
    event_type: GovernanceEventType
    occurred_at: datetime
    actor: Optional[str]
    source: Optional[str]
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        *,
        supplier_id: str,
        event_type: GovernanceEventType,
        occurred_at: Optional[datetime],
        actor: Optional[str],
        summary: str,
        source: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "GovernanceEventRecord":
        timestamp = occurred_at or datetime.now(tz=UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)
        return cls(
            event_id=str(uuid4()),
            supplier_id=supplier_id,
            event_type=event_type,
            occurred_at=timestamp,
            actor=actor,
            source=source,
            summary=summary,
            metadata=dict(metadata or {}),
        )
