from dataclasses import dataclass

@dataclass(frozen=True)
class SupplierRequirement:
    code: str
    satisfied: bool
    blocking: bool = False

@dataclass(frozen=True)
class SupplierWorkspaceSummary:
    supplier_id: str
    name: str
    primary_queue: str
    next_step: str

@dataclass(frozen=True)
class SupplierSummaryItem:
    supplier_id: str
    name: str
    mode: object
    primary_queue: str
    next_step: str

@dataclass(frozen=True)
class SupplierWorkspace:
    supplier: object
    summary: SupplierWorkspaceSummary
    requirements: tuple
    timeline: tuple
    activation_allowed: bool
