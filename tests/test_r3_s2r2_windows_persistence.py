import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import supplier_seed.repository.json_file as json_file_module
from supplier_seed.repository.json_file import JsonFileSupplierRepository


class R3S2R2WindowsPersistenceTests(unittest.TestCase):
    def test_transient_windows_permission_error_is_retried(self):
        repository = JsonFileSupplierRepository()
        attempts = []

        def transient_operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise PermissionError(13, "Permission denied")
            return "ok"

        with (
            mock.patch.object(json_file_module, "_IS_WINDOWS", True),
            mock.patch.object(json_file_module.time, "sleep"),
        ):
            result = repository._retry_windows_permission_error(transient_operation)

        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 3)

    def test_snapshot_replace_recovers_from_transient_windows_permission_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repository = JsonFileSupplierRepository(snapshot_path)
            real_replace = os.replace
            replace_attempts = []

            def transient_replace(source, target):
                replace_attempts.append((Path(source), Path(target)))
                if len(replace_attempts) < 3:
                    raise PermissionError(13, "Permission denied")
                return real_replace(source, target)

            with (
                mock.patch.object(json_file_module, "_IS_WINDOWS", True),
                mock.patch.object(json_file_module.os, "replace", side_effect=transient_replace),
                mock.patch.object(json_file_module.time, "sleep"),
            ):
                repository._replace_snapshot_file('{"schema_version": 4, "snapshot_revision": 99}')

            self.assertEqual(len(replace_attempts), 3)
            self.assertEqual(snapshot_path.read_text(encoding="utf-8"), '{"schema_version": 4, "snapshot_revision": 99}')
            self.assertEqual(list(snapshot_path.parent.glob(f".{snapshot_path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
