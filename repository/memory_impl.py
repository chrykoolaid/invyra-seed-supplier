"""In-memory repository implementation for tests and non-persistent local wiring."""

from __future__ import annotations

from typing import Iterable, Optional

from supplier_seed.domain.models import SupplierRecord
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.repository.serialization import OperationReceipt


class InMemorySupplierRepository:
    def __init__(self, suppliers: Optional[Iterable[SupplierRecord]] = None) -> None:
        self._suppliers: dict[str, SupplierRecord] = {}
        self._events: list[GovernanceEventRecord] = []
        self._operation_receipts: dict[tuple[str, str], OperationReceipt] = {}
        for supplier in suppliers or ():
            self.save_supplier(supplier)

    def list_suppliers(self) -> Iterable[SupplierRecord]:
        return tuple(self._suppliers.values())

    def get_supplier(self, supplier_id: str) -> Optional[SupplierRecord]:
        return self._suppliers.get(supplier_id)

    def save_supplier(self, supplier: SupplierRecord) -> SupplierRecord:
        self._suppliers[supplier.identity.supplier_id] = supplier
        return supplier

    def append_audit_events(self, events: Iterable[GovernanceEventRecord]) -> tuple[GovernanceEventRecord, ...]:
        stored_events = tuple(events)
        self._events.extend(stored_events)
        return stored_events

    def list_audit_events(self, supplier_id: Optional[str] = None) -> Iterable[GovernanceEventRecord]:
        if supplier_id is None:
            return tuple(self._events)
        return tuple(event for event in self._events if event.supplier_id == supplier_id)

    def get_operation_receipt(self, idempotency_key: str, *, action_name: str) -> Optional[OperationReceipt]:
        return self._operation_receipts.get((action_name, idempotency_key))

    def save_operation_receipt(self, receipt: OperationReceipt) -> OperationReceipt:
        self._operation_receipts[(receipt.action_name, receipt.idempotency_key)] = receipt
        return receipt

    def save_supplier_with_events(
        self,
        supplier: SupplierRecord,
        *,
        events: Iterable[GovernanceEventRecord] = (),
    ) -> SupplierRecord:
        return self.save_supplier_with_events_and_receipt(supplier, events=events, receipt=None)

    def save_supplier_with_events_and_receipt(
        self,
        supplier: SupplierRecord,
        *,
        events: Iterable[GovernanceEventRecord] = (),
        receipt: Optional[OperationReceipt] = None,
    ) -> SupplierRecord:
        stored_events = tuple(events)
        if any(event.supplier_id != supplier.identity.supplier_id for event in stored_events):
            raise ValueError("All audit events must belong to the supplier being saved.")
        self.save_supplier(supplier)
        self.append_audit_events(stored_events)
        if receipt is not None:
            self.save_operation_receipt(receipt)
        return supplier

    def append_audit_events_with_receipt(
        self,
        events: Iterable[GovernanceEventRecord],
        *,
        receipt: Optional[OperationReceipt] = None,
    ) -> tuple[GovernanceEventRecord, ...]:
        stored_events = self.append_audit_events(events)
        if receipt is not None:
            self.save_operation_receipt(receipt)
        return stored_events
