"""Read supplier summaries through the governed synchronous SDK."""

from __future__ import annotations

import os

from supplier_seed.sdk import SupplierSeedTypedReadClient


def main() -> None:
    base_url = os.environ.get("SUPPLIER_SEED_BASE_URL", "http://localhost:8000")
    with SupplierSeedTypedReadClient(base_url) as client:
        capabilities = client.capabilities()
        print(f"API {capabilities.api_version}; read_only={capabilities.enterprise_api_read_only}")
        for supplier in client.iter_supplier_resources(page_size=100):
            print(supplier.supplier_id, supplier.name, supplier.lifecycle_status)


if __name__ == "__main__":
    main()
