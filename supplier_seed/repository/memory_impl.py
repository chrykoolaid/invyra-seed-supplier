from __future__ import annotations

class InMemorySupplierRepository:
    def __init__(self):
        self.suppliers = {}
        self.audit_events = []

    def save(self, supplier):
        self.suppliers[supplier.supplier_id] = supplier
        return supplier

    def get(self, supplier_id):
        return self.suppliers.get(supplier_id)

    def list(self):
        return tuple(self.suppliers.values())

    def list_suppliers(self):
        return self.list()

    def append_events(self, events):
        self.audit_events.extend(events)
        return tuple(events)

    def list_events(self, supplier_id=None):
        if supplier_id is None:
            return tuple(self.audit_events)
        return tuple(event for event in self.audit_events if event.supplier_id == supplier_id)
