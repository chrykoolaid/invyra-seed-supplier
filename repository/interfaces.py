"""Repository interfaces for supplier storage.

Part E makes the repository contract explicit about supplier snapshots and audit persistence
so later database adapters can preserve governed state changes consistently.
Part O extends the contract with optional idempotency receipts so replay-safe mutation
retries can be enforced at the persistence boundary rather than in UI code.
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol

from supplier_seed.domain.models import SupplierRecord
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.repository.serialization import OperationReceipt


class SupplierReadRepository(Protocol):
    def list_suppliers(self) -> Iterable[SupplierRecord]:
        """Return all currently stored supplier snapshots."""

    def get_supplier(self, supplier_id: str) -> Optional[SupplierRecord]:
        """Return a supplier by ID, or None if it is not present."""


class SupplierWriteRepository(Protocol):
    def save_supplier(self, supplier: SupplierRecord) -> SupplierRecord:
        """Persist the supplier snapshot and return the saved record."""


class SupplierAuditRepository(Protocol):
    def append_audit_events(self, events: Iterable[GovernanceEventRecord]) -> tuple[GovernanceEventRecord, ...]:
        """Persist audit events in insertion order and return the stored events."""

    def list_audit_events(self, supplier_id: Optional[str] = None) -> Iterable[GovernanceEventRecord]:
        """Return audit events, optionally filtered to a single supplier."""


class SupplierIdempotencyRepository(Protocol):
    def get_operation_receipt(self, idempotency_key: str, *, action_name: str) -> Optional[OperationReceipt]:
        """Return a previously stored idempotent operation receipt, if present."""

    def save_operation_receipt(self, receipt: OperationReceipt) -> OperationReceipt:
        """Persist an idempotent operation receipt without mutating supplier state."""


class SupplierRepository(
    SupplierReadRepository,
    SupplierWriteRepository,
    SupplierAuditRepository,
    SupplierIdempotencyRepository,
    Protocol,
):
    def save_supplier_with_events(
        self,
        supplier: SupplierRecord,
        *,
        events: Iterable[GovernanceEventRecord] = (),
    ) -> SupplierRecord:
        """Persist a supplier snapshot and its audit events as one repository-level mutation contract."""

    def save_supplier_with_events_and_receipt(
        self,
        supplier: SupplierRecord,
        *,
        events: Iterable[GovernanceEventRecord] = (),
        receipt: Optional[OperationReceipt] = None,
    ) -> SupplierRecord:
        """Persist a supplier snapshot, audit events, and an idempotency receipt atomically."""

    def append_audit_events_with_receipt(
        self,
        events: Iterable[GovernanceEventRecord],
        *,
        receipt: Optional[OperationReceipt] = None,
    ) -> tuple[GovernanceEventRecord, ...]:
        """Persist audit events and an idempotency receipt atomically."""
