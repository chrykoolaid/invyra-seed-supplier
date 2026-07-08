import json
from dataclasses import dataclass
from pathlib import Path

from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput

class SupplierCandidateSource:
    def load_candidates(self):
        raise NotImplementedError

    def list_candidates(self):
        return self.load_candidates()

@dataclass(frozen=True)
class StaticSupplierCandidateSource(SupplierCandidateSource):
    candidates: tuple
    def load_candidates(self):
        return self.candidates

@dataclass(frozen=True)
class JsonFileSupplierCandidateSource(SupplierCandidateSource):
    path: str

    def _to_candidate(self, payload):
        region_payload = payload.get("region_context", {})
        region_context = SupplierRegionContext(
            region_code=region_payload.get("region_code"),
            market_code=region_payload.get("market_code", "PH"),
            pilot_enabled=region_payload.get("pilot_enabled", False),
        )
        return SupplierCandidateInput(
            name=payload.get("name", ""),
            mode=SupplierMode(payload.get("mode", SupplierMode.MANUAL)),
            region_context=region_context,
            seeded_source=payload.get("seeded_source"),
            seeded_source_reference=payload.get("seeded_source_reference"),
            contact_email=payload.get("contact_email"),
            contact_phone=payload.get("contact_phone"),
            website_url=payload.get("website_url"),
            tax_identifier=payload.get("tax_identifier"),
            created_by=payload.get("created_by"),
        )

    def load_candidates(self):
        with Path(self.path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError("Supplier candidate source must contain a list payload")
        return tuple(self._to_candidate(item) for item in payload)
