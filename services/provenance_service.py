"""Provenance governance services.

This service records origin/provenance actions without introducing
repository or persistence concerns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from supplier_seed.domain.enums import GovernanceEventType, ValidationSeverity
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.results import GovernanceServiceResult


UTC = timezone.utc
SOURCE = "services.provenance"


class ProvenanceService:
    def record_manual_origin(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str] = None,
        at: Optional[datetime] = None,
        entry_channel: str = "manual_entry",
    ) -> GovernanceServiceResult:
        if not supplier.is_manual:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=(
                    ValidationIssue(
                        code="provenance.manual_origin.seeded_supplier_invalid",
                        field="mode",
                        message="Manual origin can only be recorded for manual suppliers.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=actor,
            at=timestamp,
            provenance_last_updated_at=timestamp,
            provenance_last_updated_by=actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.PROVENANCE_MANUAL_RECORDED,
            occurred_at=timestamp,
            actor=actor,
            source=SOURCE,
            summary="Manual supplier origin was recorded.",
            metadata={"entry_channel": entry_channel},
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,))

    def capture_seeded_provenance(
        self,
        supplier: SupplierRecord,
        *,
        seeded_source: str,
        seeded_source_reference: str,
        actor: Optional[str] = None,
        at: Optional[datetime] = None,
    ) -> GovernanceServiceResult:
        if not supplier.is_seeded:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=(
                    ValidationIssue(
                        code="provenance.seeded_capture.manual_supplier_invalid",
                        field="mode",
                        message="Seeded provenance can only be captured for seeded suppliers.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        if not seeded_source.strip() or not seeded_source_reference.strip():
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=(
                    ValidationIssue(
                        code="provenance.seeded_capture.source_required",
                        field="seeded_source_reference",
                        message="Seeded provenance requires both a source and a source reference.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=actor,
            at=timestamp,
            seeded_source=seeded_source,
            seeded_source_reference=seeded_source_reference,
            provenance_last_updated_at=timestamp,
            provenance_last_updated_by=actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.PROVENANCE_SEEDED_CAPTURED,
            occurred_at=timestamp,
            actor=actor,
            source=SOURCE,
            summary="Seeded supplier provenance was captured.",
            metadata={
                "seeded_source": seeded_source,
                "seeded_source_reference": seeded_source_reference,
            },
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,))
