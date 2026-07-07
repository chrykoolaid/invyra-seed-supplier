from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class NormalizedSupplierProfile:
    normalized_name: str
    comparable_name: str
    normalized_phone: Optional[str] = None
    normalized_website_host: Optional[str] = None
    normalized_email: Optional[str] = None
    normalized_tax_identifier: Optional[str] = None

def _digits(value):
    return "".join(ch for ch in (value or "") if ch.isdigit())

class SupplierNormalizer:
    suffixes = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited"}

    def normalize_name(self, name):
        replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
        value = (name or "").lower()
        for source, target in replacements.items():
            value = value.replace(source, target)
        cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in value)
        return " ".join(cleaned.split())

    def comparable_name(self, name):
        return " ".join(part for part in self.normalize_name(name).split() if part not in self.suffixes)

    def normalize_supplier(self, supplier):
        phone_digits = _digits(supplier.contact_phone)
        if phone_digits.startswith("0") and len(phone_digits) == 11:
            phone = "+63" + phone_digits[1:]
        elif phone_digits.startswith("63"):
            phone = "+" + phone_digits
        else:
            phone = phone_digits or None
        tax_digits = _digits(supplier.tax_identifier) if supplier.tax_identifier else None
        host = None
        if supplier.website_url:
            host = supplier.website_url.lower().replace("https://", "").replace("http://", "").split("/")[0]
            if host.startswith("www."):
                host = host[4:]
        return NormalizedSupplierProfile(
            normalized_name=self.normalize_name(supplier.name),
            comparable_name=self.comparable_name(supplier.name),
            normalized_phone=phone,
            normalized_website_host=host,
            normalized_email=supplier.contact_email.lower().strip() if supplier.contact_email else None,
            normalized_tax_identifier=tax_digits,
        )
