from dataclasses import replace
from supplier_seed.domain.enums import SupplierMode, GovernanceEventType
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.results import GovernanceServiceResult

class ProvenanceService:
    def capture_seeded_provenance(self, supplier, seeded_source, seeded_source_reference, actor=None):
        updated = replace(supplier, seeded_source=seeded_source.strip(), seeded_source_reference=seeded_source_reference.strip()).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.PROVENANCE_SEEDED_CAPTURED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))

    def record_manual_origin(self, supplier, actor=None):
        if supplier.mode == SupplierMode.SEEDED:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("provenance.manual_origin.seeded_supplier_invalid"),), ())
        event = GovernanceEventRecord.for_supplier(supplier.supplier_id, GovernanceEventType.PROVENANCE_MANUAL_RECORDED, actor=actor)
        return GovernanceServiceResult(True, supplier.with_updated_metadata(actor), (), (event,))
