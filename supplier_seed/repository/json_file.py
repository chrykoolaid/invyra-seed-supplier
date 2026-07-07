from supplier_seed.repository.memory_impl import InMemorySupplierRepository

class JsonFileSupplierRepository(InMemorySupplierRepository):
    def __init__(self, path=None):
        super().__init__()
        self.path = path
