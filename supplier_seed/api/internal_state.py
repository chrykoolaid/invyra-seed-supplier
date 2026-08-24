from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from supplier_seed.api.internal_app import StoredMutationReceipt


class JsonFileInternalMutationStateStore:
    """Durable nonce and idempotency state for the server-only internal API.

    The store is only considered LIVE-durable when the deployment operator has
    explicitly attested that ``path`` is backed by persistent storage and the
    deployment itself has passed the later R3-S3 certification gate. Merely
    pointing at a writable container filesystem is not sufficient.
    """

    SCHEMA_VERSION = 1
    _path_locks: dict[str, threading.RLock] = {}
    _path_locks_guard = threading.Lock()

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        durability_attested: bool = False,
        deployment_certified: bool = False,
    ) -> None:
        self.path = Path(path)
        self.durable = bool(durability_attested and deployment_certified)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._load_payload()
        else:
            self._write_payload(self._empty_payload())

    @classmethod
    def _lock_for_path(cls, path: Path) -> threading.RLock:
        key = str(path.resolve())
        with cls._path_locks_guard:
            return cls._path_locks.setdefault(key, threading.RLock())

    @contextmanager
    def _process_lock(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.01)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "nonces": {},
            "receipts": {},
        }

    def _load_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid internal mutation state file") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("Unsupported internal mutation state schema")
        if not isinstance(payload.get("nonces"), dict) or not isinstance(payload.get("receipts"), dict):
            raise ValueError("Invalid internal mutation state shape")
        return payload

    def _write_payload(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, sort_keys=True, indent=2)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, self.path)

    def _with_locked_payload(self):
        return self._lock_for_path(self.path), self._process_lock()

    @staticmethod
    def _receipt_from_dict(payload: Any) -> StoredMutationReceipt:
        if not isinstance(payload, dict):
            raise ValueError("Invalid mutation receipt")
        fingerprint = payload.get("fingerprint")
        status_code = payload.get("status_code")
        response_payload = payload.get("payload")
        if not isinstance(fingerprint, str) or not isinstance(status_code, int) or not isinstance(response_payload, dict):
            raise ValueError("Invalid mutation receipt")
        return StoredMutationReceipt(
            fingerprint=fingerprint,
            status_code=status_code,
            payload=json.loads(json.dumps(response_payload)),
        )

    @staticmethod
    def _receipt_to_dict(receipt: StoredMutationReceipt) -> dict[str, Any]:
        return {
            "fingerprint": receipt.fingerprint,
            "status_code": receipt.status_code,
            "payload": json.loads(json.dumps(receipt.payload)),
        }

    def claim_nonce(self, nonce: str, expires_at: int) -> bool:
        now = int(time.time())
        thread_lock, process_lock = self._with_locked_payload()
        with thread_lock:
            with process_lock:
                payload = self._load_payload()
                nonces = {
                    str(value): int(expiry)
                    for value, expiry in payload["nonces"].items()
                    if int(expiry) >= now
                }
                if nonce in nonces:
                    return False
                nonces[nonce] = int(expires_at)
                payload["nonces"] = nonces
                self._write_payload(payload)
                return True

    def get_receipt(self, idempotency_key: str) -> StoredMutationReceipt | None:
        thread_lock, process_lock = self._with_locked_payload()
        with thread_lock:
            with process_lock:
                payload = self._load_payload()
                stored = payload["receipts"].get(idempotency_key)
                return self._receipt_from_dict(stored) if stored is not None else None

    def save_receipt(
        self,
        idempotency_key: str,
        fingerprint: str,
        status_code: int,
        payload: dict[str, Any],
    ) -> StoredMutationReceipt:
        thread_lock, process_lock = self._with_locked_payload()
        with thread_lock:
            with process_lock:
                state = self._load_payload()
                existing = state["receipts"].get(idempotency_key)
                if existing is not None:
                    return self._receipt_from_dict(existing)
                receipt = StoredMutationReceipt(
                    fingerprint=fingerprint,
                    status_code=int(status_code),
                    payload=json.loads(json.dumps(payload)),
                )
                state["receipts"][idempotency_key] = self._receipt_to_dict(receipt)
                self._write_payload(state)
                return receipt


__all__ = ["JsonFileInternalMutationStateStore"]
