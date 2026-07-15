"""Read supplier summaries through the governed asynchronous SDK."""

from __future__ import annotations

import asyncio
import os

from supplier_seed.sdk import SupplierSeedAsyncTypedReadClient


async def main() -> None:
    base_url = os.environ.get("SUPPLIER_SEED_BASE_URL", "http://localhost:8000")
    async with SupplierSeedAsyncTypedReadClient(base_url) as client:
        capabilities = await client.capabilities()
        print(f"API {capabilities.api_version}; read_only={capabilities.enterprise_api_read_only}")
        async for supplier in client.iter_supplier_resources(page_size=100):
            print(supplier.supplier_id, supplier.name, supplier.lifecycle_status)


if __name__ == "__main__":
    asyncio.run(main())
