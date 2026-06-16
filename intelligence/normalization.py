"""Supplier normalization helpers for deterministic matching."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from supplier_seed.domain.models import SupplierRecord


LEGAL_SUFFIX_TOKENS = frozenset({
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "llc",
})


@dataclass(frozen=True, slots=True)
class NormalizedSupplierProfile:
    supplier_id: str
    normalized_name: str
    comparable_name: str
    name_tokens: tuple[str, ...]
    normalized_email: Optional[str] = None
    normalized_phone: Optional[str] = None
    normalized_website_host: Optional[str] = None
    normalized_tax_identifier: Optional[str] = None
    normalized_seeded_reference: Optional[str] = None
    region_code: Optional[str] = None


class SupplierNormalizer:
    """Normalizes supplier fields into deterministic matching profiles."""

    def normalize_supplier(self, supplier: SupplierRecord) -> NormalizedSupplierProfile:
        normalized_name = self.normalize_name(supplier.name)
        comparable_name = self.normalize_comparable_name(supplier.name)
        return NormalizedSupplierProfile(
            supplier_id=supplier.identity.supplier_id,
            normalized_name=normalized_name,
            comparable_name=comparable_name,
            name_tokens=tuple(comparable_name.split()) if comparable_name else (),
            normalized_email=self.normalize_email(supplier.contact_email),
            normalized_phone=self.normalize_phone(supplier.contact_phone),
            normalized_website_host=self.normalize_website_host(supplier.website_url),
            normalized_tax_identifier=self.normalize_tax_identifier(supplier.tax_identifier),
            normalized_seeded_reference=self.normalize_seeded_reference(
                supplier.seeded_source,
                supplier.seeded_source_reference,
            ),
            region_code=supplier.region_context.region_code.lower() if supplier.region_context.region_code else None,
        )

    @staticmethod
    def normalize_name(value: Optional[str]) -> str:
        if not value:
            return ""
        text = SupplierNormalizer._ascii_fold(value).lower().strip()
        text = text.replace("&", " and ")
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def normalize_comparable_name(cls, value: Optional[str]) -> str:
        normalized = cls.normalize_name(value)
        tokens = normalized.split()
        while tokens and tokens[-1] in LEGAL_SUFFIX_TOKENS:
            tokens.pop()
        return " ".join(tokens)

    @staticmethod
    def normalize_email(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        email = value.strip().lower()
        return email or None

    @staticmethod
    def normalize_phone(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        digits = re.sub(r"\D+", "", value)
        if not digits:
            return None
        if digits.startswith("63") and len(digits) == 12:
            return f"+{digits}"
        if digits.startswith("0") and len(digits) == 11:
            return f"+63{digits[1:]}"
        if len(digits) == 10 and digits.startswith("9"):
            return f"+63{digits}"
        return digits

    @staticmethod
    def normalize_website_host(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        text = value.strip().lower()
        if not text:
            return None
        candidate = text if "://" in text else f"https://{text}"
        parsed = urlparse(candidate)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host or None

    @staticmethod
    def normalize_tax_identifier(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        digits = re.sub(r"\D+", "", value)
        return digits or None

    @staticmethod
    def normalize_seeded_reference(source: Optional[str], reference: Optional[str]) -> Optional[str]:
        if not source or not reference:
            return None
        normalized_source = SupplierNormalizer.normalize_name(source)
        normalized_reference = SupplierNormalizer.normalize_name(reference)
        if not normalized_source or not normalized_reference:
            return None
        return f"{normalized_source}|{normalized_reference}"

    @staticmethod
    def _ascii_fold(value: str) -> str:
        return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
