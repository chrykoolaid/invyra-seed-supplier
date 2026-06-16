"""Shared result types for governance services and engine-facing UI envelopes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord


@dataclass(frozen=True, slots=True)
class GovernanceServiceResult:
    allowed: bool
    supplier: SupplierRecord
    events: tuple[GovernanceEventRecord, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(issue.severity.value == "error" for issue in self.issues)

    @property
    def has_events(self) -> bool:
        return bool(self.events)


@dataclass(frozen=True, slots=True)
class EngineActionResult:
    action_name: str
    status: str
    allowed: bool
    supplier: Optional[SupplierRecord] = None
    issues: tuple[ValidationIssue, ...] = ()
    events: tuple[GovernanceEventRecord, ...] = ()
    source_result_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def has_events(self) -> bool:
        return bool(self.events)
