from dataclasses import dataclass

@dataclass(frozen=True)
class OperationReceipt:
    supplier_id: str
    event_count: int = 0
    accepted: bool = True

@dataclass(frozen=True)
class RepositorySnapshot:
    suppliers: tuple
    audit_events: tuple = ()
