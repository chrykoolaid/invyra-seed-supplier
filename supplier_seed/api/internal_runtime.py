from __future__ import annotations

import os
from pathlib import Path

from supplier_seed import JsonFileSupplierRepository, SupplierSeedEngine
from supplier_seed.api.internal_app import (
    InMemoryInternalMutationStateStore,
    InternalSupplierApiSettings,
    create_internal_app,
)
from supplier_seed.api.internal_state import JsonFileInternalMutationStateStore


REPOSITORY_PATH_ENV = "SUPPLIER_SEED_INTERNAL_REPOSITORY_PATH"
STATE_PATH_ENV = "SUPPLIER_SEED_INTERNAL_STATE_PATH"
DURABILITY_ATTESTED_ENV = "SUPPLIER_SEED_INTERNAL_DURABLE_STORAGE_ATTESTED"
DEPLOYMENT_CERTIFIED_ENV = "SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _absolute_env_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path


def create_internal_runtime_app_from_env():
    """Build the deployable R3-S2 internal application.

    R3-S2 supplies restart-safe nonce/idempotency state, but LIVE creation
    remains fail-closed until a later deployment phase explicitly certifies
    the persistent storage mount and sets ``DEPLOYMENT_CERTIFIED_ENV``.
    """

    settings = InternalSupplierApiSettings.from_env()
    durability_attested = _env_flag(DURABILITY_ATTESTED_ENV, False)
    deployment_certified = _env_flag(DEPLOYMENT_CERTIFIED_ENV, False)

    if not settings.enabled:
        return create_internal_app(settings=settings)

    try:
        repository_path = _absolute_env_path(REPOSITORY_PATH_ENV)
        state_path = _absolute_env_path(STATE_PATH_ENV)
        if repository_path is None or state_path is None:
            raise ValueError("Durable repository and mutation-state paths are required")
        if repository_path.resolve() == state_path.resolve():
            raise ValueError("Supplier repository and mutation-state paths must be separate")

        repository = JsonFileSupplierRepository(repository_path)
        engine = SupplierSeedEngine(repository=repository)
        state_store = JsonFileInternalMutationStateStore(
            state_path,
            durability_attested=durability_attested,
            deployment_certified=deployment_certified,
        )
        return create_internal_app(
            engine,
            settings=settings,
            state_store=state_store,
        )
    except (OSError, ValueError):
        # Fail closed. Preserve the HMAC configuration so authenticated
        # capability checks can see that creation is unavailable, while
        # preventing writes against partially initialized persistence.
        return create_internal_app(
            settings=settings,
            state_store=InMemoryInternalMutationStateStore(),
        )


app = create_internal_runtime_app_from_env()


__all__ = [
    "DEPLOYMENT_CERTIFIED_ENV",
    "DURABILITY_ATTESTED_ENV",
    "REPOSITORY_PATH_ENV",
    "STATE_PATH_ENV",
    "app",
    "create_internal_runtime_app_from_env",
]
