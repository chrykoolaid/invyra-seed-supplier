# Invyra Supplier Seed System

Governed Supplier Seed System with a read-only enterprise API and Python SDK.

## Supported environment

- Python 3.11 and 3.12
- FastAPI v1 read contracts
- Synchronous and asynchronous Python clients
- Typed Pydantic SDK resources

## Install for development

```bash
python -m pip install -e ".[test]"
python -m pytest
```

## Synchronous SDK

```python
from supplier_seed.sdk import SupplierSeedReadClient

with SupplierSeedReadClient("http://localhost:8000") as client:
    capabilities = client.capabilities()
    suppliers = list(client.iter_suppliers(page_size=100))

print(capabilities.enterprise_api_read_only)
print(len(suppliers))
```

## Typed synchronous SDK

```python
from supplier_seed.sdk import SupplierSeedTypedReadClient

with SupplierSeedTypedReadClient("http://localhost:8000") as client:
    resources = list(client.iter_supplier_resources(page_size=100))

for supplier in resources:
    print(supplier.supplier_id, supplier.name, supplier.lifecycle_status)
```

## Asynchronous SDK

```python
import asyncio

from supplier_seed.sdk import SupplierSeedAsyncTypedReadClient


async def main() -> None:
    async with SupplierSeedAsyncTypedReadClient("http://localhost:8000") as client:
        async for supplier in client.iter_supplier_resources(page_size=100):
            print(supplier.supplier_id, supplier.name)


asyncio.run(main())
```

## Governed error handling

```python
from supplier_seed.sdk import SupplierSeedApiError, SupplierSeedReadClient

with SupplierSeedReadClient("http://localhost:8000") as client:
    try:
        client.get_supplier("missing-supplier")
    except SupplierSeedApiError as error:
        print(error.status_code, error.code, error.detail)
```

## Governance boundary

The enterprise API and SDK are read-only. They may inspect supplier records, queues, audit events, pilot reports, capabilities, and runbook information. They do not activate suppliers, approve moderation, verify suppliers, accept legal terms, enable pilot access, or perform any other mutation.

Mutation authority remains exclusively in the governed domain and service layers.

## Packaging certification

The `SDK Package Certification` GitHub Actions workflow builds the wheel and source distribution, validates metadata, verifies the PEP 561 typing marker, installs the wheel on Python 3.11 and 3.12, and smoke-imports the public SDK namespace. It does not publish a package.
