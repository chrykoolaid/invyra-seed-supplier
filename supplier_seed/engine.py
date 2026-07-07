from supplier_seed.ingestion.ingestion_service import SupplierIngestionService
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.legal_service import LegalService
from supplier_seed.services.moderation_service import ModerationService
from supplier_seed.services.provenance_service import ProvenanceService
from supplier_seed.services.verification_service import VerificationService

class SupplierSeedEngine:
    def __init__(self, repository=None, ingestion_service=None):
        self.repository = repository or InMemorySupplierRepository()
        self.ingestion_service = ingestion_service or SupplierIngestionService()
        self.legal_service = LegalService()
        self.moderation_service = ModerationService()
        self.provenance_service = ProvenanceService()
        self.verification_service = VerificationService()

    def ingest_supplier(self, candidate, context=None):
        result = self.ingestion_service.ingest_supplier(candidate, existing_suppliers=self.repository.list(), context=context)
        if result.accepted_for_staging and result.supplier is not None:
            self.repository.save(result.supplier)
            self.repository.append_events(result.events)
        return result

    def list_suppliers(self):
        return self.repository.list()

    def get_supplier(self, supplier_id):
        return self.repository.get(supplier_id)
