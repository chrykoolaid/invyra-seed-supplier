from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from uuid import uuid4
from supplier_seed.domain.enums import GovernanceEventType

@dataclass(frozen=True)
class GovernanceEventRecord:
    event_id: str
    supplier_id: str
    event_type: GovernanceEventType
    occurred_at: datetime = field(default_factory=datetime.utcnow)
    actor: Optional[str] = None
    source: Optional[str] = None
    summary: str = ""
    metadata: dict = field(default_factory=dict)

    @classmethod
    def for_supplier(cls, supplier_id, event_type, actor=None, source=None, summary="", metadata=None):
        return cls(str(uuid4()), supplier_id, GovernanceEventType(event_type), datetime.utcnow(), actor, source, summary, metadata or {})
