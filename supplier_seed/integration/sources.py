import json
from dataclasses import dataclass
from pathlib import Path

class SupplierCandidateSource:
    def load_candidates(self):
        raise NotImplementedError

@dataclass(frozen=True)
class StaticSupplierCandidateSource(SupplierCandidateSource):
    candidates: tuple
    def load_candidates(self):
        return self.candidates

@dataclass(frozen=True)
class JsonFileSupplierCandidateSource(SupplierCandidateSource):
    path: str
    def load_candidates(self):
        with Path(self.path).open("r", encoding="utf-8") as handle:
            return tuple(json.load(handle))
