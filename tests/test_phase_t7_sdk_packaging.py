import importlib
from pathlib import Path
import tomllib
import unittest


class SupplierSeedPhaseT7PackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        with (self.root / "pyproject.toml").open("rb") as stream:
            self.configuration = tomllib.load(stream)

    def test_project_metadata_declares_supported_python_and_release_dependencies(self) -> None:
        project = self.configuration["project"]

        self.assertEqual(project["name"], "invyra-supplier-seed")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertEqual(project["readme"], "README.md")
        self.assertIn("httpx>=0.27,<1.0", project["dependencies"])
        self.assertIn("build>=1.2,<2.0", project["optional-dependencies"]["build"])
        self.assertIn("Typing :: Typed", project["classifiers"])

    def test_package_declares_pep561_typing_marker(self) -> None:
        package_data = self.configuration["tool"]["setuptools"]["package-data"]

        self.assertIn("py.typed", package_data["supplier_seed"])
        self.assertTrue((self.root / "supplier_seed" / "py.typed").is_file())

    def test_public_sdk_namespace_exports_all_enterprise_clients_and_resources(self) -> None:
        sdk = importlib.import_module("supplier_seed.sdk")
        expected = {
            "AuditEventResource",
            "QueueResource",
            "SupplierDetailResource",
            "SupplierSeedApiError",
            "SupplierSeedAsyncReadClient",
            "SupplierSeedAsyncTypedReadClient",
            "SupplierSeedReadClient",
            "SupplierSeedTypedReadClient",
            "SupplierSummaryResource",
        }

        self.assertTrue(expected.issubset(set(sdk.__all__)))
        for name in expected:
            self.assertIsNotNone(getattr(sdk, name))


if __name__ == "__main__":
    unittest.main()
