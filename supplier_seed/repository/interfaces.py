class SupplierRepository:
    def save(self, supplier):
        raise NotImplementedError
    def get(self, supplier_id):
        raise NotImplementedError
    def list(self):
        raise NotImplementedError

class SupplierReadRepository(SupplierRepository):
    pass

class SupplierAuditRepository:
    def append_events(self, events):
        raise NotImplementedError
    def list_events(self, supplier_id=None):
        raise NotImplementedError
