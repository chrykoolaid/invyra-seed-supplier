"""Thin source adapters for supplier candidate ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Protocol

from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput


class SupplierCandidateSource(Protocol):
    def list_candidates(self) -> Iterable[SupplierCandidateInput]:
        """Return supplier candidates in engine-native input form."""


class StaticSupplierCandidateSource:
    def __init__(self, candidates: Iterable[SupplierCandidateInput]) -> None:
        self._candidates = tuple(candidates)

    def list_candidates(self) -> Iterable[SupplierCandidateInput]:
        return self._candidates


class JsonFileSupplierCandidateSource:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list_candidates(self) -> Iterable[SupplierCandidateInput]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Candidate source JSON must contain a list of candidate objects.")
        return tuple(self._parse_candidate(item) for item in payload)

    @staticmethod
    def _parse_candidate(payload: object) -> SupplierCandidateInput:
        if not isinstance(payload, dict):
            raise ValueError("Each candidate payload must be an object.")

        region_payload = payload.get("region_context") or {}
        if not isinstance(region_payload, dict):
            raise ValueError("Candidate region_context must be an object when present.")

        return SupplierCandidateInput(
            name=payload["name"],
            mode=SupplierMode(payload["mode"]),
            region_context=SupplierRegionContext(
                region_code=region_payload.get("region_code"),
                market_code=region_payload.get("market_code", "PH"),
                pilot_name=region_payload.get("pilot_name"),
                pilot_enabled=bool(region_payload.get("pilot_enabled", False)),
            ),
            created_by=payload.get("created_by"),
            seeded_source=payload.get("seeded_source"),
            seeded_source_reference=payload.get("seeded_source_reference"),
            contact_email=payload.get("contact_email"),
            contact_phone=payload.get("contact_phone"),
            website_url=payload.get("website_url"),
            tax_identifier=payload.get("tax_identifier"),
            supplier_code=payload.get("supplier_code"),
            external_reference=payload.get("external_reference"),
        )
