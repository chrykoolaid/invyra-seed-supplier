from dataclasses import dataclass

@dataclass(frozen=True)
class GovernanceServiceResult:
    allowed: bool
    supplier: object
    issues: tuple = ()
    events: tuple = ()

@dataclass(frozen=True)
class EngineActionResult:
    allowed: bool
    supplier: object = None
    issues: tuple = ()
    events: tuple = ()
    receipt: object = None
